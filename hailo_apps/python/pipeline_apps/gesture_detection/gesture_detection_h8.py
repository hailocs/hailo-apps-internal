"""
Gesture detection app for Hailo-8 using MediaPipe Blaze models.

Architecture:
  Camera (OpenCV) → resize_pad(192x192) → palm_detection_lite.hef (HailoRT)
    → anchor decode + NMS → detection2roi → affine warp (224x224)
    → hand_landmark_lite.hef (HailoRT) → denormalize landmarks
    → gesture_recognition.py → OpenCV display

Uses HailoRT Python API (InferVStreams) directly instead of GStreamer.
Based on AlbertaBeef/blaze_app_python (https://github.com/AlbertaBeef/blaze_app_python).

Usage:
    python -m hailo_apps.python.pipeline_apps.gesture_detection.gesture_detection_h8
    python -m hailo_apps.python.pipeline_apps.gesture_detection.gesture_detection_h8 --input video.mp4
"""

import argparse
import os
import sys
import time

import cv2
import numpy as np
from hailo_platform import VDevice

from . import blaze_base
from .blaze_palm_detector import BlazePalmDetector
from .blaze_hand_landmark import BlazeHandLandmark
from .gesture_recognition import classify_hand_gesture, count_fingers


# Hand skeleton connections for drawing (MediaPipe topology)
HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),       # thumb
    (0, 5), (5, 6), (6, 7), (7, 8),       # index
    (0, 9), (9, 10), (10, 11), (11, 12),   # middle
    (0, 13), (13, 14), (14, 15), (15, 16), # ring
    (0, 17), (17, 18), (18, 19), (19, 20), # pinky
    (5, 9), (9, 13), (13, 17),             # palm
]

# Colors
COLOR_PALM_BOX = (0, 255, 0)
COLOR_LANDMARK = (255, 0, 0)
COLOR_SKELETON = (0, 200, 200)
COLOR_GESTURE = (255, 255, 255)
HAND_FLAG_THRESHOLD = 0.5

# Default model paths
DEFAULT_MODELS_DIR = os.path.join(os.path.dirname(__file__), "models")
DEFAULT_PALM_MODEL = os.path.join(DEFAULT_MODELS_DIR, "palm_detection_lite.hef")
DEFAULT_HAND_MODEL = os.path.join(DEFAULT_MODELS_DIR, "hand_landmark_lite.hef")


class GesturePoint:
    """Adapter to wrap numpy landmark coordinates with .x(), .y(), .confidence() interface.

    This bridges the gap between the numpy-based blaze pipeline output and
    gesture_recognition.py which expects HailoPoint-like objects.
    """

    def __init__(self, x, y, confidence=1.0):
        self._x = float(x)
        self._y = float(y)
        self._confidence = float(confidence)

    def x(self):
        return self._x

    def y(self):
        return self._y

    def confidence(self):
        return self._confidence


def landmarks_to_gesture_points(landmarks_2d):
    """Convert (21, 2+) numpy landmarks to list of GesturePoint.

    Args:
        landmarks_2d: np.ndarray (21, 2) or (21, 3) with x, y[, z] in image pixels.

    Returns:
        List of 21 GesturePoint objects.
    """
    points = []
    for i in range(21):
        x = landmarks_2d[i, 0]
        y = landmarks_2d[i, 1]
        points.append(GesturePoint(x, y))
    return points


def draw_hand(frame, landmarks, gesture_label=None, finger_count=None, handedness=None):
    """Draw hand landmarks, skeleton, and gesture label on frame.

    Args:
        frame: BGR image to draw on.
        landmarks: np.ndarray (21, 3) with x, y in image pixel coords.
        gesture_label: Optional gesture string to display.
        finger_count: Optional finger count to display.
        handedness: Optional handedness score (>0.5 = left).
    """
    pts = landmarks[:, :2].astype(int)

    # Draw skeleton
    for i, j in HAND_CONNECTIONS:
        cv2.line(frame, tuple(pts[i]), tuple(pts[j]), COLOR_SKELETON, 2)

    # Draw landmark points
    for i, pt in enumerate(pts):
        cv2.circle(frame, tuple(pt), 4, COLOR_LANDMARK, -1)

    # Draw gesture label
    if gesture_label:
        hand_str = ""
        if handedness is not None:
            hand_str = "L" if handedness > 0.5 else "R"
        label = f"{hand_str} {gesture_label}"
        if finger_count is not None and finger_count >= 0:
            label += f" ({finger_count})"

        # Position above wrist
        wrist = pts[0]
        text_pos = (wrist[0] - 30, wrist[1] - 20)
        cv2.putText(frame, label, text_pos, cv2.FONT_HERSHEY_SIMPLEX,
                    0.8, COLOR_GESTURE, 2, cv2.LINE_AA)


def draw_palm_box(frame, detection):
    """Draw palm detection bounding box.

    Args:
        frame: BGR image.
        detection: np.ndarray (num_coords+1,) with [ymin, xmin, ymax, xmax, ...].
    """
    ymin, xmin, ymax, xmax = detection[:4].astype(int)
    cv2.rectangle(frame, (xmin, ymin), (xmax, ymax), COLOR_PALM_BOX, 2)


def process_frame(frame, palm_detector, hand_landmark, config):
    """Process a single frame through the full pipeline.

    Args:
        frame: BGR image from camera.
        palm_detector: BlazePalmDetector instance.
        hand_landmark: BlazeHandLandmark instance.
        config: Palm model config dict.

    Returns:
        Annotated frame with landmarks and gesture labels.
    """
    display = frame.copy()
    h, w = frame.shape[:2]

    # Convert BGR → RGB for model
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    # 1. Palm detection
    target_size = (int(config["y_scale"]), int(config["x_scale"]))
    padded, scale, pad = blaze_base.resize_pad(rgb, target_size)
    normalized_detections = palm_detector.detect(padded)

    if len(normalized_detections) == 0:
        return display

    # 2. Denormalize detections to image coordinates
    detections = blaze_base.denormalize_detections(
        normalized_detections, scale, pad, config["x_scale"])

    # 3. Convert detections to ROIs
    xc, yc, roi_scale, theta = blaze_base.detection2roi(detections, config)

    # 4. Extract hand crops
    roi_imgs, roi_affines = blaze_base.extract_roi(
        rgb, xc, yc, theta, roi_scale, blaze_base.HAND_LANDMARK_RESOLUTION)

    if roi_imgs.shape[0] == 0:
        return display

    # 5. Hand landmark inference
    flags, landmarks, handedness = hand_landmark.predict(roi_imgs)

    # 6. Denormalize landmarks back to image coordinates
    landmarks_img = blaze_base.denormalize_landmarks(
        landmarks, roi_affines, blaze_base.HAND_LANDMARK_RESOLUTION)

    # 7. Classify gestures and draw
    for i in range(len(flags)):
        flag_val = float(flags[i].flatten()[0])

        # Apply sigmoid if raw logit
        if flag_val < -10 or flag_val > 10:
            flag_val = 1.0 / (1.0 + np.exp(-flag_val))

        if flag_val < HAND_FLAG_THRESHOLD:
            continue

        hand_lm = landmarks_img[i]  # (21, 3)

        # Draw palm detection box
        if i < len(detections):
            draw_palm_box(display, detections[i])

        # Classify gesture
        gesture_points = landmarks_to_gesture_points(hand_lm)
        gesture = classify_hand_gesture(gesture_points)
        fingers = count_fingers(gesture_points)
        hand_side = float(handedness[i].flatten()[0]) if len(handedness) > i else None

        draw_hand(display, hand_lm, gesture, fingers, hand_side)

    return display


def run(args):
    """Main run loop.

    Args:
        args: Parsed CLI arguments.
    """
    print(f"Loading palm detection model: {args.palm_model}")
    print(f"Loading hand landmark model: {args.hand_model}")

    # Create shared VDevice for both models
    vdevice = VDevice()

    palm_detector = BlazePalmDetector(args.palm_model, vdevice=vdevice)
    hand_landmark = BlazeHandLandmark(args.hand_model, vdevice=vdevice)
    config = blaze_base.PALM_MODEL_CONFIG

    # Open video source
    if args.input is None or args.input == "0":
        source = 0
    else:
        try:
            source = int(args.input)
        except ValueError:
            source = args.input

    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        print(f"Error: Cannot open video source: {source}")
        sys.exit(1)

    print("Starting gesture detection (press 'q' to quit)...")

    fps_time = time.time()
    frame_count = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            if isinstance(source, str):
                # Video file ended
                break
            continue

        display = process_frame(frame, palm_detector, hand_landmark, config)

        # FPS counter
        frame_count += 1
        elapsed = time.time() - fps_time
        if elapsed >= 1.0:
            fps = frame_count / elapsed
            frame_count = 0
            fps_time = time.time()
            cv2.putText(display, f"FPS: {fps:.1f}", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)

        cv2.imshow("Gesture Detection (H8)", display)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()
    print("Done.")


def parse_args():
    parser = argparse.ArgumentParser(description="Gesture Detection (Hailo-8, MediaPipe Blaze)")
    parser.add_argument("--input", type=str, default=None,
                        help="Video source: camera index (0) or video file path")
    parser.add_argument("--palm-model", type=str, default=DEFAULT_PALM_MODEL,
                        help="Path to palm_detection_lite.hef")
    parser.add_argument("--hand-model", type=str, default=DEFAULT_HAND_MODEL,
                        help="Path to hand_landmark_lite.hef")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run(args)
