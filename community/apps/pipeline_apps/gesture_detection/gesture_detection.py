"""
GStreamer gesture detection app using MediaPipe Blaze models on Hailo-8.

Uses GStreamer for video source/display and the proven blaze Python modules
for inference. Attaches proper Hailo metadata (HailoDetection, HailoLandmarks,
HailoClassification) to each buffer so downstream pipelines can consume results.

Architecture:
  GStreamer source → Python callback (palm detection + hand landmark + gesture) → display

The Python callback runs both models via HailoRT InferVStreams and attaches:
  - HailoDetection("palm", bbox) for each detected palm
  - HailoLandmarks("hand_landmarks", 21 points) on each palm detection
  - HailoClassification("gesture", label) on each palm detection

Usage:
    python -m community.apps.pipeline_apps.gesture_detection.gesture_detection
    python -m community.apps.pipeline_apps.gesture_detection.gesture_detection --input photo.jpg
"""

# region imports
import os

os.environ["GST_PLUGIN_FEATURE_RANK"] = "vaapidecodebin:NONE"

import gi

gi.require_version("Gst", "1.0")

import setproctitle
import numpy as np
import hailo
from hailo_platform import VDevice

from hailo_apps.python.core.common.buffer_utils import get_caps_from_pad, get_numpy_from_buffer
from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.gstreamer.gstreamer_app import GStreamerApp, app_callback_class
from hailo_apps.python.core.common.core import get_pipeline_parser

from community.apps.pipeline_apps.gesture_detection import blaze_base
from community.apps.pipeline_apps.gesture_detection.blaze_palm_detector import BlazePalmDetector
from community.apps.pipeline_apps.gesture_detection.blaze_hand_landmark import BlazeHandLandmark
from community.apps.pipeline_apps.gesture_detection.gesture_recognition import classify_hand_gesture, count_fingers
from community.apps.pipeline_apps.gesture_detection.gesture_detection_standalone import landmarks_to_gesture_points
from community.apps.pipeline_apps.gesture_detection.download_models import ensure_models, get_models_dir

hailo_logger = get_logger(__name__)
# endregion imports

# Hand skeleton connections for hailooverlay drawing
HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (0, 9), (9, 10), (10, 11), (11, 12),
    (0, 13), (13, 14), (14, 15), (15, 16),
    (0, 17), (17, 18), (18, 19), (19, 20),
    (5, 9), (9, 13), (13, 17),
]

HAND_FLAG_THRESHOLD = 0.5


class GestureAppCallback(app_callback_class):
    """Callback class holding the blaze models (shared VDevice)."""

    def __init__(self, arch=None):
        super().__init__()

        # Resolve architecture and ensure models are available
        if arch is None:
            from hailo_apps.python.core.common.installation_utils import detect_hailo_arch
            arch = os.getenv("hailo_arch") or detect_hailo_arch()
            if not arch:
                hailo_logger.error(
                    "Could not detect Hailo architecture. "
                    "Use --arch flag or set the hailo_arch environment variable."
                )
                raise RuntimeError("Hailo architecture detection failed")
        models_dir = ensure_models(arch)
        palm_model = os.path.join(models_dir, "palm_detection_lite.hef")
        hand_model = os.path.join(models_dir, "hand_landmark_lite.hef")

        hailo_logger.info("Loading palm detection model: %s", palm_model)
        hailo_logger.info("Loading hand landmark model: %s", hand_model)

        self.vdevice = VDevice()
        self.palm_detector = BlazePalmDetector(palm_model, vdevice=self.vdevice)
        self.hand_landmark = BlazeHandLandmark(hand_model, vdevice=self.vdevice)
        self.config = blaze_base.PALM_MODEL_CONFIG

        hailo_logger.info("Blaze models loaded successfully.")


def app_callback(element, buffer, user_data):
    """Handoff callback for gesture detection.

    Runs palm detection + hand landmark inference on each frame,
    attaches Hailo metadata (detections, landmarks, classifications)
    to the buffer for downstream consumption (e.g. hailooverlay, other pipelines).
    """
    if buffer is None:
        return

    # Get frame dimensions from element's src pad
    pad = element.get_static_pad("src")
    format_str, width, height = get_caps_from_pad(pad)
    if width is None:
        return

    # Get the frame as numpy array (RGB from GStreamer pipeline)
    frame = get_numpy_from_buffer(buffer, format_str, width, height)
    if frame is None:
        return

    rgb = frame
    config = user_data.config

    # 1. Palm detection
    target_size = (int(config["y_scale"]), int(config["x_scale"]))
    padded, scale, pad_offset = blaze_base.resize_pad(rgb, target_size)
    normalized_detections = user_data.palm_detector.detect(padded)

    if len(normalized_detections) == 0:
        return

    # 2. Denormalize detections to image coordinates
    detections = blaze_base.denormalize_detections(
        normalized_detections, scale, pad_offset, config["x_scale"])

    # 3. Convert to ROIs
    xc, yc, roi_scale, theta = blaze_base.detection2roi(detections, config)

    # 4. Extract hand crops
    roi_imgs, roi_affines = blaze_base.extract_roi(
        rgb, xc, yc, theta, roi_scale, blaze_base.HAND_LANDMARK_RESOLUTION)

    if roi_imgs.shape[0] == 0:
        return

    # 5. Hand landmark inference
    flags, landmarks, handedness = user_data.hand_landmark.predict(roi_imgs)

    # 6. Denormalize landmarks back to image coordinates
    landmarks_img = blaze_base.denormalize_landmarks(
        landmarks, roi_affines, blaze_base.HAND_LANDMARK_RESOLUTION)

    # 7. Attach Hailo metadata to buffer
    roi = hailo.get_roi_from_buffer(buffer)

    for i in range(len(flags)):
        flag_val = float(flags[i].flatten()[0])
        if flag_val < -10 or flag_val > 10:
            flag_val = 1.0 / (1.0 + np.exp(-flag_val))

        if flag_val < HAND_FLAG_THRESHOLD:
            continue

        hand_lm = landmarks_img[i]  # (21, 3) in image pixel coords

        # Compute bbox from landmarks to cover the full hand (with padding)
        lm_x = hand_lm[:, 0]
        lm_y = hand_lm[:, 1]
        lm_xmin = float(np.min(lm_x))
        lm_ymin = float(np.min(lm_y))
        lm_xmax = float(np.max(lm_x))
        lm_ymax = float(np.max(lm_y))

        # Add 10% padding around landmarks
        pad_x = (lm_xmax - lm_xmin) * 0.1
        pad_y = (lm_ymax - lm_ymin) * 0.1
        lm_xmin = max(0, lm_xmin - pad_x)
        lm_ymin = max(0, lm_ymin - pad_y)
        lm_xmax = min(width, lm_xmax + pad_x)
        lm_ymax = min(height, lm_ymax + pad_y)

        # Normalize bbox to [0,1] relative to frame
        xmin = lm_xmin / width
        ymin = lm_ymin / height
        bbox_w = max((lm_xmax - lm_xmin) / width, 0.001)
        bbox_h = max((lm_ymax - lm_ymin) / height, 0.001)
        bbox = hailo.HailoBBox(xmin, ymin, bbox_w, bbox_h)
        palm_det = hailo.HailoDetection(bbox, "palm", float(flag_val))

        # Create hand landmarks normalized relative to the detection bbox
        # hailooverlay draws landmarks relative to the parent detection bbox
        hailo_points = []
        for j in range(21):
            # Map from image pixel coords to bbox-relative [0,1]
            px = (float(hand_lm[j, 0]) - lm_xmin) / (lm_xmax - lm_xmin)
            py = (float(hand_lm[j, 1]) - lm_ymin) / (lm_ymax - lm_ymin)
            hailo_points.append(hailo.HailoPoint(px, py, float(flag_val)))

        hand_landmarks = hailo.HailoLandmarks(
            "hand_landmarks", hailo_points, float(flag_val), HAND_CONNECTIONS)
        palm_det.add_object(hand_landmarks)

        # Classify gesture
        gesture_points = landmarks_to_gesture_points(hand_lm)
        gesture = classify_hand_gesture(gesture_points)
        fingers = count_fingers(gesture_points)

        if gesture:
            gesture_cls = hailo.HailoClassification(
                type="gesture", label=gesture, confidence=1.0)
            palm_det.add_object(gesture_cls)

            hand_str = ""
            if len(handedness) > i:
                hs = float(handedness[i].flatten()[0])
                hand_str = "L" if hs > 0.5 else "R"

            hailo_logger.info(
                "Detected: %s %s (fingers: %d, flag: %.2f)",
                hand_str, gesture, fingers, flag_val,
            )

        roi.add_object(palm_det)


class GStreamerGestureApp(GStreamerApp):
    """GStreamer pipeline for gesture detection using blaze Python modules.

    Simple pipeline: source → identity callback (Python inference) → overlay → display.
    The callback attaches Hailo metadata for hailooverlay and downstream consumption.
    """

    def __init__(self, app_callback, user_data, parser=None):
        if parser is None:
            parser = get_pipeline_parser()

        hailo_logger.info("Initializing GStreamer Gesture Detection App...")
        super().__init__(parser, user_data)
        setproctitle.setproctitle("gesture_detection_gst")

        self.app_callback = app_callback
        self.create_pipeline()
        hailo_logger.info("Pipeline created successfully.")

    def get_pipeline_string(self):
        from hailo_apps.python.core.gstreamer.gstreamer_helper_pipelines import (
            QUEUE,
            SOURCE_PIPELINE,
            USER_CALLBACK_PIPELINE,
            DISPLAY_PIPELINE,
        )

        source_pipeline = SOURCE_PIPELINE(
            video_source=self.video_source,
            video_width=self.video_width,
            video_height=self.video_height,
            frame_rate=self.frame_rate,
            sync=self.sync,
        )

        user_callback_pipeline = USER_CALLBACK_PIPELINE()

        display_pipeline = DISPLAY_PIPELINE(
            video_sink=self.video_sink, sync=self.sync, show_fps=self.show_fps
        )

        pipeline_string = (
            f"{source_pipeline} ! "
            f"{user_callback_pipeline} ! "
            f"hailooverlay name=hailo_overlay ! "
            f"{display_pipeline}"
        )
        hailo_logger.debug("Pipeline string: %s", pipeline_string)
        return pipeline_string


def main():
    hailo_logger.info("Starting GStreamer Gesture Detection App.")
    user_data = GestureAppCallback()
    app = GStreamerGestureApp(app_callback, user_data)
    app.run()


if __name__ == "__main__":
    main()
