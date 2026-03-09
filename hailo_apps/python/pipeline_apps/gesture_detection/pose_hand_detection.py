"""
Combined pose estimation + hand landmark detection GStreamer pipeline.

Uses YOLOv8-Pose on Hailo for full-body pose estimation (17 COCO keypoints).
Uses MediaPipe Blaze pipeline (palm detection + hand landmark + gesture) on Hailo
via hailonet elements and C++ postprocess filters. All inference runs on the NPU;
the Python callback only associates detected hands to the nearest person by wrist
proximity.

Architecture:
  source → hailonet(pose) → hailofilter(pose_postprocess) → hailotracker
         → hailonet(palm) → hailofilter(palm_postprocess)
         → hailocropper(palm_croppers) →
             inner: videoscale(224x224) → affine_warp → hailonet(hand) → hand_postprocess
         → hailoaggregator
         → hailofilter(gesture_classification)
         → Python callback (associate hands to persons)
         → hailooverlay → display

Usage:
    source setup_env.sh
    python -m hailo_apps.python.pipeline_apps.gesture_detection.pose_hand_detection
    python -m hailo_apps.python.pipeline_apps.gesture_detection.pose_hand_detection --input video.mp4
"""

# region imports
import os

os.environ["GST_PLUGIN_FEATURE_RANK"] = "vaapidecodebin:NONE"

import setproctitle
import numpy as np
import hailo

from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.gstreamer.gstreamer_app import GStreamerApp, app_callback_class
from hailo_apps.python.core.common.core import (
    get_pipeline_parser,
    get_resource_path,
    resolve_hef_path,
)
from hailo_apps.python.core.common.defines import (
    POSE_ESTIMATION_PIPELINE,
    POSE_ESTIMATION_POSTPROCESS_FUNCTION,
    POSE_ESTIMATION_POSTPROCESS_SO_FILENAME,
    RESOURCES_SO_DIR_NAME,
    SHARED_VDEVICE_GROUP_ID,
)

hailo_logger = get_logger(__name__)
# endregion imports

# Model paths
MODELS_DIR = os.path.join(os.path.dirname(__file__), "models")
DEFAULT_PALM_HEF = os.path.join(MODELS_DIR, "palm_detection_lite.hef")
DEFAULT_HAND_HEF = os.path.join(MODELS_DIR, "hand_landmark_lite.hef")

# C++ postprocess shared libraries
SO_DIR = "/usr/local/hailo/resources/so"
PALM_DETECTION_POST_SO = os.path.join(SO_DIR, "libpalm_detection_postprocess.so")
PALM_CROPPERS_SO = os.path.join(SO_DIR, "libpalm_croppers.so")
HAND_AFFINE_WARP_SO = os.path.join(SO_DIR, "libhand_affine_warp.so")
HAND_LANDMARK_POST_SO = os.path.join(SO_DIR, "libhand_landmark_postprocess.so")
GESTURE_CLASSIFICATION_SO = os.path.join(SO_DIR, "libgesture_classification.so")

# Pose keypoint indices (COCO format)
LEFT_WRIST = 9
RIGHT_WRIST = 10


class PoseHandCallback(app_callback_class):
    """Minimal callback data — all inference runs in hailonet elements."""
    def __init__(self):
        super().__init__()


def find_nearest_person(hand_det, person_detections, width, height):
    """Find the person detection whose pose wrist is closest to the hand detection center.

    Args:
        hand_det: HailoDetection for the hand (frame-absolute normalized coords).
        person_detections: List of (detection, pose_points) tuples.
        width, height: Frame dimensions.

    Returns:
        The nearest person detection, or None if no person is close enough.
    """
    hand_bbox = hand_det.get_bbox()
    hand_cx = (hand_bbox.xmin() + hand_bbox.width() / 2) * width
    hand_cy = (hand_bbox.ymin() + hand_bbox.height() / 2) * height

    best_det = None
    best_dist = float("inf")
    max_dist = max(width, height) * 0.3

    for detection, pose_points in person_detections:
        bbox = detection.get_bbox()
        for wrist_idx in [LEFT_WRIST, RIGHT_WRIST]:
            pt = pose_points[wrist_idx]
            wx = (pt.x() * bbox.width() + bbox.xmin()) * width
            wy = (pt.y() * bbox.height() + bbox.ymin()) * height
            dist = np.sqrt((hand_cx - wx) ** 2 + (hand_cy - wy) ** 2)
            if dist < best_dist:
                best_dist = dist
                best_det = detection

    if best_dist > max_dist:
        return None
    return best_det


def app_callback(element, buffer, user_data):
    """Associate hand detections with person detections by adding gesture to person.

    Hand detections stay at the ROI level for correct landmark rendering by
    hailooverlay. The association is done by adding the gesture classification
    to the nearest person detection.
    """
    if buffer is None:
        return

    roi = hailo.get_roi_from_buffer(buffer)
    detections = roi.get_objects_typed(hailo.HAILO_DETECTION)

    # Separate persons (with pose landmarks) and hands
    person_detections = []
    hand_detections = []
    for det in detections:
        label = det.get_label()
        if label == "person":
            landmarks_list = det.get_objects_typed(hailo.HAILO_LANDMARKS)
            if landmarks_list:
                points = landmarks_list[0].get_points()
                if len(points) >= 17:
                    person_detections.append((det, points))
        elif label == "hand":
            hand_detections.append(det)

    if not hand_detections or not person_detections:
        return

    # Get frame dimensions from pad caps
    pad = element.get_static_pad("src")
    from hailo_apps.python.core.common.buffer_utils import get_caps_from_pad
    _, width, height = get_caps_from_pad(pad)
    if width is None:
        return

    # Associate each hand's gesture to the nearest person
    for hand_det in hand_detections:
        nearest = find_nearest_person(hand_det, person_detections, width, height)
        if nearest is None:
            continue

        # Copy only gesture classification to the person (skip palm_angle etc.)
        for obj in hand_det.get_objects_typed(hailo.HAILO_CLASSIFICATION):
            if obj.get_classification_type() != "gesture":
                continue
            gesture_cls = hailo.HailoClassification(
                type=obj.get_classification_type(),
                label=obj.get_label(),
                confidence=obj.get_confidence())
            nearest.add_object(gesture_cls)
            hailo_logger.info("Hand on person: %s (flag: %.2f)",
                             obj.get_label(), hand_det.get_confidence())


class GStreamerPoseHandApp(GStreamerApp):
    """GStreamer pipeline: pose + hand detection, all inference via hailonet.

    Pipeline: source → pose inference → tracker → palm inference → cropper →
              hand landmark inference → gesture classify → callback → overlay → display
    """

    def __init__(self, app_callback, user_data, parser=None):
        if parser is None:
            parser = get_pipeline_parser()

        parser.add_argument(
            "--palm-hef", default=DEFAULT_PALM_HEF,
            help="Path to palm detection HEF model",
        )
        parser.add_argument(
            "--hand-hef", default=DEFAULT_HAND_HEF,
            help="Path to hand landmark HEF model",
        )

        hailo_logger.info("Initializing Pose + Hand Detection App...")
        super().__init__(parser, user_data)

        if self.batch_size == 1:
            self.batch_size = 2

        self.hef_path = resolve_hef_path(
            self.hef_path,
            app_name=POSE_ESTIMATION_PIPELINE,
            arch=self.arch,
        )
        hailo_logger.info("Pose model: %s", self.hef_path)

        self.palm_hef = self.options_menu.palm_hef
        self.hand_hef = self.options_menu.hand_hef

        self.app_callback = app_callback
        self.post_process_so = get_resource_path(
            POSE_ESTIMATION_PIPELINE,
            RESOURCES_SO_DIR_NAME,
            self.arch,
            POSE_ESTIMATION_POSTPROCESS_SO_FILENAME,
        )
        self.post_process_function = POSE_ESTIMATION_POSTPROCESS_FUNCTION

        setproctitle.setproctitle("pose_hand_detection")
        self.create_pipeline()
        hailo_logger.info("Pipeline created successfully.")

    def get_pipeline_string(self):
        from hailo_apps.python.core.gstreamer.gstreamer_helper_pipelines import (
            QUEUE,
            SOURCE_PIPELINE,
            INFERENCE_PIPELINE,
            INFERENCE_PIPELINE_WRAPPER,
            TRACKER_PIPELINE,
            USER_CALLBACK_PIPELINE,
            DISPLAY_PIPELINE,
        )

        # 1. Video source
        source_pipeline = SOURCE_PIPELINE(
            video_source=self.video_source,
            video_width=self.video_width,
            video_height=self.video_height,
            frame_rate=self.frame_rate,
            sync=self.sync,
        )

        # 2. Pose estimation (yolov8m_pose)
        pose_infer = INFERENCE_PIPELINE(
            hef_path=self.hef_path,
            post_process_so=self.post_process_so,
            post_function_name=self.post_process_function,
            batch_size=self.batch_size,
            name="pose_inference",
        )
        pose_wrapper = INFERENCE_PIPELINE_WRAPPER(pose_infer, name="pose_wrapper")
        tracker_pipeline = TRACKER_PIPELINE(class_id=0)

        # 3. Palm detection (wrapped to preserve original resolution)
        palm_infer = INFERENCE_PIPELINE(
            hef_path=self.palm_hef,
            post_process_so=PALM_DETECTION_POST_SO,
            batch_size=2,
            name="palm_detection",
        )
        palm_wrapper = INFERENCE_PIPELINE_WRAPPER(palm_infer, name="palm_wrapper")

        # 4. Inner pipeline for cropper: 224x224 → affine warp → hand landmark → postprocess
        inner_pipeline = (
            f"{QUEUE(name='hand_scale_q')} ! "
            f"videoscale name=hand_videoscale n-threads=2 qos=false ! "
            f"video/x-raw, width=224, height=224, pixel-aspect-ratio=1/1 ! "
            f"videoconvert name=hand_videoconvert n-threads=2 ! "
            f"hailofilter so-path={HAND_AFFINE_WARP_SO} "
            f"name=hand_affine_warp use-gst-buffer=true qos=false ! "
            f"{QUEUE(name='hand_hailonet_q')} ! "
            f"hailonet name=hand_landmark_hailonet "
            f"hef-path={self.hand_hef} "
            f"batch-size=2 "
            f"vdevice-group-id={SHARED_VDEVICE_GROUP_ID} "
            f"force-writable=true ! "
            f"{QUEUE(name='hand_postproc_q')} ! "
            f"hailofilter name=hand_landmark_postproc "
            f"so-path={HAND_LANDMARK_POST_SO} qos=false ! "
            f"{QUEUE(name='hand_output_q')} "
        )

        # 5. Cropper: palm_croppers creates rotated envelope crop
        palm_cropper_pipeline = (
            f"{QUEUE(name='palm_cropper_input_q')} ! "
            f"hailocropper name=palm_cropper "
            f"so-path={PALM_CROPPERS_SO} "
            f"function-name=palm_to_hand_crop "
            f"use-letterbox=false "
            f"no-scaling-bbox=true "
            f"internal-offset=true "
            f"hailoaggregator name=palm_agg "
            f"palm_cropper. ! "
            f"{QUEUE(name='palm_bypass_q', max_size_buffers=20)} ! palm_agg.sink_0 "
            f"palm_cropper. ! {inner_pipeline} ! palm_agg.sink_1 "
            f"palm_agg. ! {QUEUE(name='palm_cropper_output_q')} "
        )

        # 6. Gesture classification
        gesture_filter = (
            f"{QUEUE(name='gesture_filter_q')} ! "
            f"hailofilter so-path={GESTURE_CLASSIFICATION_SO} "
            f"name=gesture_classification qos=false "
        )

        # 7. User callback (associates hands to persons) + display
        user_callback = USER_CALLBACK_PIPELINE()
        display_pipeline = DISPLAY_PIPELINE(
            video_sink=self.video_sink,
            sync=self.sync,
            show_fps=self.show_fps,
            community_overlay=True,
        )

        pipeline_string = (
            f"{source_pipeline} ! "
            f"{pose_wrapper} ! "
            f"{tracker_pipeline} ! "
            f"{palm_wrapper} ! "
            f"{palm_cropper_pipeline} ! "
            f"{gesture_filter} ! "
            f"{user_callback} ! "
            f"{display_pipeline}"
        )

        hailo_logger.debug("Pipeline string: %s", pipeline_string)
        return pipeline_string


def main():
    hailo_logger.info("Starting Pose + Hand Detection App.")
    user_data = PoseHandCallback()
    app = GStreamerPoseHandApp(app_callback, user_data)
    app.run()


if __name__ == "__main__":
    main()
