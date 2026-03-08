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
import platform
import statistics
import sys
import time

import cv2
import numpy as np
import psutil
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


def process_frame(frame, palm_detector, hand_landmark, config, headless=False, timings=None):
    """Process a single frame through the full pipeline.

    Args:
        frame: BGR image from camera.
        palm_detector: BlazePalmDetector instance.
        hand_landmark: BlazeHandLandmark instance.
        config: Palm model config dict.
        headless: If True, skip drawing and return None as display.
        timings: Optional dict to accumulate timing breakdown (keys: preprocess, palm_infer, postprocess, hand_infer).

    Returns:
        (display_frame, num_hands_detected) tuple.
    """
    display = None if headless else frame.copy()
    h, w = frame.shape[:2]

    t0 = time.time()

    # Convert BGR → RGB for model
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    # 1. Palm detection - preprocess
    target_size = (int(config["y_scale"]), int(config["x_scale"]))
    padded, scale, pad = blaze_base.resize_pad(rgb, target_size)

    t1 = time.time()

    # Palm detection - inference (includes HailoRT infer + postprocess decode)
    normalized_detections = palm_detector.detect(padded)

    t2 = time.time()

    if len(normalized_detections) == 0:
        if timings is not None:
            timings["preprocess"].append((t1 - t0) * 1000)
            timings["palm_infer"].append((t2 - t1) * 1000)
            timings["postprocess"].append(0)
            timings["hand_infer"].append(0)
        return display, 0

    # 2. Denormalize detections to image coordinates
    detections = blaze_base.denormalize_detections(
        normalized_detections, scale, pad, config["x_scale"])

    # 3. Convert detections to ROIs
    xc, yc, roi_scale, theta = blaze_base.detection2roi(detections, config)

    # 4. Extract hand crops
    roi_imgs, roi_affines = blaze_base.extract_roi(
        rgb, xc, yc, theta, roi_scale, blaze_base.HAND_LANDMARK_RESOLUTION)

    t3 = time.time()

    if roi_imgs.shape[0] == 0:
        if timings is not None:
            timings["preprocess"].append((t1 - t0) * 1000)
            timings["palm_infer"].append((t2 - t1) * 1000)
            timings["postprocess"].append((t3 - t2) * 1000)
            timings["hand_infer"].append(0)
        return display, 0

    # 5. Hand landmark inference
    flags, landmarks, handedness = hand_landmark.predict(roi_imgs)

    t4 = time.time()

    # 6. Denormalize landmarks back to image coordinates
    landmarks_img = blaze_base.denormalize_landmarks(
        landmarks, roi_affines, blaze_base.HAND_LANDMARK_RESOLUTION)

    if timings is not None:
        t5 = time.time()
        timings["preprocess"].append((t1 - t0) * 1000)
        timings["palm_infer"].append((t2 - t1) * 1000)
        timings["postprocess"].append((t3 - t2) * 1000 + (t5 - t4) * 1000)
        timings["hand_infer"].append((t4 - t3) * 1000)

    # 7. Classify gestures and draw
    num_valid_hands = 0
    for i in range(len(flags)):
        flag_val = float(flags[i].flatten()[0])

        # Apply sigmoid if raw logit
        if flag_val < -10 or flag_val > 10:
            flag_val = 1.0 / (1.0 + np.exp(-flag_val))

        if flag_val < HAND_FLAG_THRESHOLD:
            continue

        num_valid_hands += 1
        hand_lm = landmarks_img[i]  # (21, 3)

        if not headless:
            # Draw palm detection box
            if i < len(detections):
                draw_palm_box(display, detections[i])

            # Classify gesture
            gesture_points = landmarks_to_gesture_points(hand_lm)
            gesture = classify_hand_gesture(gesture_points)
            fingers = count_fingers(gesture_points)
            hand_side = float(handedness[i].flatten()[0]) if len(handedness) > i else None

            draw_hand(display, hand_lm, gesture, fingers, hand_side)

    return display, num_valid_hands


def get_system_info():
    """Collect system info for benchmark report."""
    info = {}
    info["platform"] = platform.platform()
    info["processor"] = platform.processor() or platform.machine()
    info["python"] = platform.python_version()
    info["cpu_count"] = psutil.cpu_count(logical=True)
    info["cpu_count_physical"] = psutil.cpu_count(logical=False)
    mem = psutil.virtual_memory()
    info["ram_total_gb"] = f"{mem.total / (1024**3):.1f}"
    try:
        with open("/proc/device-tree/model", "r") as f:
            info["board"] = f.read().strip().rstrip("\x00")
    except (FileNotFoundError, PermissionError):
        info["board"] = None
    return info


class CpuMonitor:
    """Tracks per-process and system CPU usage during benchmark."""

    def __init__(self):
        self.process = psutil.Process()
        self.samples = []
        self.system_samples = []
        self._last_sample_time = 0
        self.process.cpu_percent()
        psutil.cpu_percent(percpu=False)

    def sample(self):
        now = time.time()
        if now - self._last_sample_time < 0.5:
            return
        self._last_sample_time = now
        self.samples.append(self.process.cpu_percent())
        self.system_samples.append(psutil.cpu_percent(percpu=False))

    def summary(self):
        if not self.samples:
            return {}
        return {
            "process_cpu_avg": statistics.mean(self.samples),
            "process_cpu_max": max(self.samples),
            "system_cpu_avg": statistics.mean(self.system_samples),
            "system_cpu_max": max(self.system_samples),
        }


def run(args):
    """Main run loop.

    Args:
        args: Parsed CLI arguments.
    """
    headless = args.headless
    sys_info = get_system_info()
    cpu_monitor = CpuMonitor()

    print("=== System Info ===")
    if sys_info["board"]:
        print(f"Board:     {sys_info['board']}")
    print(f"Platform:  {sys_info['platform']}")
    print(f"Processor: {sys_info['processor']}")
    print(f"CPU cores: {sys_info['cpu_count_physical']} physical, {sys_info['cpu_count']} logical")
    print(f"RAM:       {sys_info['ram_total_gb']} GB")
    print(f"Python:    {sys_info['python']}")
    print()

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

    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0

    print(f"Source: {args.input or 'camera 0'} ({src_w}x{src_h} @ {src_fps:.0f}fps)")
    if total_frames > 0:
        print(f"Total frames: {total_frames}")
    if headless:
        print("Running in headless mode (no display)")
    print("Starting gesture detection — Hailo-8 (press 'q' to quit)...\n")

    fps_smoothed = 0.0
    alpha = 0.1
    prev_time = time.time()
    frame_times = []
    timings = {"preprocess": [], "palm_infer": [], "postprocess": [], "hand_infer": []}
    hands_detected_count = 0
    total_processed = 0
    t_wall_start = time.time()

    while True:
        ret, frame = cap.read()
        if not ret:
            if isinstance(source, str):
                break
            continue

        t_start = time.time()

        display, n_hands = process_frame(frame, palm_detector, hand_landmark, config, headless=headless, timings=timings)

        if n_hands > 0:
            hands_detected_count += 1

        t_end = time.time()
        frame_time_ms = (t_end - t_start) * 1000
        fps_instant = 1.0 / max(t_end - prev_time, 1e-6)
        fps_smoothed = alpha * fps_instant + (1 - alpha) * fps_smoothed if fps_smoothed > 0 else fps_instant
        prev_time = t_end
        total_processed += 1

        frame_times.append(frame_time_ms)
        cpu_monitor.sample()

        if not headless:
            cpu_stats = cpu_monitor.summary()
            cpu_pct = cpu_stats.get("process_cpu_avg", 0)
            cv2.putText(display, f"FPS: {fps_smoothed:.1f}", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
            cv2.putText(display, f"Frame: {frame_time_ms:.1f}ms", (10, 65),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            cv2.putText(display, f"CPU: {cpu_pct:.0f}%", (10, 95),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            cv2.putText(display, "HAILO-8", (10, src_h - 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 0), 2)

            cv2.imshow("Gesture Detection (H8)", display)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
        else:
            if total_processed % 100 == 0:
                print(f"  Processed {total_processed} frames... FPS: {fps_smoothed:.1f}")

    t_wall_end = time.time()
    wall_time = t_wall_end - t_wall_start

    cap.release()
    if not headless:
        cv2.destroyAllWindows()

    # Print benchmark report
    if frame_times:
        cpu_stats = cpu_monitor.summary()
        print()
        print("=" * 55)
        print("  BENCHMARK REPORT - Hailo-8 Accelerated")
        print("=" * 55)
        print()
        print("--- System ---")
        if sys_info["board"]:
            print(f"  Board:         {sys_info['board']}")
        print(f"  Platform:      {sys_info['platform']}")
        print(f"  Processor:     {sys_info['processor']}")
        print(f"  CPU cores:     {sys_info['cpu_count_physical']}P / {sys_info['cpu_count']}L")
        print(f"  RAM:           {sys_info['ram_total_gb']} GB")
        print()
        print("--- Input ---")
        print(f"  Source:        {args.input or 'camera 0'}")
        print(f"  Resolution:    {src_w}x{src_h}")
        print()
        print("--- Performance ---")
        print(f"  Frames:        {total_processed}")
        print(f"  Wall time:     {wall_time:.1f} s")
        print(f"  Avg FPS:       {total_processed / wall_time:.1f}")
        print(f"  Avg frame:     {statistics.mean(frame_times):.1f} ms")
        print(f"  Median frame:  {statistics.median(frame_times):.1f} ms")
        if len(frame_times) > 10:
            sorted_ft = sorted(frame_times)
            p5 = sorted_ft[int(len(sorted_ft) * 0.05)]
            p95 = sorted_ft[int(len(sorted_ft) * 0.95)]
            print(f"  P5 frame:      {p5:.1f} ms (best)")
            print(f"  P95 frame:     {p95:.1f} ms (worst)")
        print()
        print("--- Timing Breakdown ---")
        for key in ["preprocess", "palm_infer", "postprocess", "hand_infer"]:
            vals = timings[key]
            if vals:
                avg = statistics.mean(vals)
                med = statistics.median(vals)
                label = {
                    "preprocess": "Pre-process (Python)",
                    "palm_infer": "Palm detect (Hailo)",
                    "postprocess": "Post-process (Python)",
                    "hand_infer": "Hand landmark (Hailo)",
                }[key]
                print(f"  {label:26s}  avg {avg:5.1f} ms  med {med:5.1f} ms")
        total_infer = statistics.mean(timings["palm_infer"]) + statistics.mean(timings["hand_infer"])
        total_py = statistics.mean(timings["preprocess"]) + statistics.mean(timings["postprocess"])
        print(f"  {'Hailo inference total':26s}  avg {total_infer:5.1f} ms")
        print(f"  {'Python pre/post total':26s}  avg {total_py:5.1f} ms")
        print()
        print("--- CPU Usage ---")
        if cpu_stats:
            print(f"  Process avg:   {cpu_stats['process_cpu_avg']:.1f}%")
            print(f"  Process max:   {cpu_stats['process_cpu_max']:.1f}%")
            print(f"  System avg:    {cpu_stats['system_cpu_avg']:.1f}%")
            print(f"  System max:    {cpu_stats['system_cpu_max']:.1f}%")
        print()
        print("--- Detection ---")
        det_pct = hands_detected_count / total_processed * 100 if total_processed > 0 else 0
        print(f"  Frames w/hand: {hands_detected_count}/{total_processed} ({det_pct:.0f}%)")
        print()
    print("Done.")


def parse_args():
    parser = argparse.ArgumentParser(description="Gesture Detection (Hailo-8, MediaPipe Blaze)")
    parser.add_argument("--input", type=str, default=None,
                        help="Video source: camera index (0) or video file path")
    parser.add_argument("--palm-model", type=str, default=DEFAULT_PALM_MODEL,
                        help="Path to palm_detection_lite.hef")
    parser.add_argument("--hand-model", type=str, default=DEFAULT_HAND_MODEL,
                        help="Path to hand_landmark_lite.hef")
    parser.add_argument("--headless", action="store_true",
                        help="Run without display window (for benchmarking)")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run(args)
