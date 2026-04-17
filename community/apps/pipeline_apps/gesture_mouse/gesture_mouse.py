"""
Gesture-controlled mouse using Hailo-8 hand tracking.

Maps index fingertip position to screen cursor. Pinch (thumb+index) to click.
Fist to drag. Open hand to release.

Gestures:
  - POINTING / ONE / TWO+ fingers: Move cursor (index fingertip position)
  - Pinch (thumb tip close to index tip): Left click
  - FIST while pinching: Drag (hold mouse button)
  - OPEN_HAND: Release drag

Usage:
    python community/apps/pipeline_apps/gesture_mouse/gesture_mouse.py --input usb
    python community/apps/pipeline_apps/gesture_mouse/gesture_mouse.py --input usb --smoothing 0.5 --speed 2.0
"""

import math
import time

import hailo
from pynput.mouse import Button, Controller as MouseController

from hailo_apps.python.core.common.buffer_utils import get_caps_from_pad
from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.gstreamer.gstreamer_app import app_callback_class

from community.apps.pipeline_apps.gesture_mouse.gesture_mouse_pipeline import (
    GStreamerGestureMouseApp,
)

hailo_logger = get_logger(__name__)

# Hand landmark indices (MediaPipe)
INDEX_TIP = 8
THUMB_TIP = 4


class GestureMouseCallback(app_callback_class):
    """Tracks hand position and controls the mouse cursor."""

    def __init__(self):
        super().__init__()
        self.mouse = MouseController()
        # Defaults — overridden by CLI args in main()
        self.smoothing = 0.4
        self.pinch_threshold = 0.06
        self.speed = 1.5
        self.no_click = False

        # Screen dimensions (from pynput)
        try:
            import screeninfo
            monitor = screeninfo.get_monitors()[0]
            self.screen_w = monitor.width
            self.screen_h = monitor.height
        except (ImportError, IndexError):
            # Fallback: try xdotool
            import subprocess
            try:
                result = subprocess.run(
                    ["xdotool", "getdisplaygeometry"],
                    capture_output=True, text=True, check=True,
                )
                w, h = result.stdout.strip().split()
                self.screen_w = int(w)
                self.screen_h = int(h)
            except (FileNotFoundError, subprocess.CalledProcessError):
                self.screen_w = 1920
                self.screen_h = 1080
                hailo_logger.warning(
                    "Could not detect screen size. Using %dx%d. "
                    "Install 'screeninfo' or 'xdotool' for auto-detection.",
                    self.screen_w, self.screen_h,
                )

        hailo_logger.info("Screen size: %dx%d", self.screen_w, self.screen_h)

        # Smoothed cursor position
        self.smooth_x = self.screen_w / 2.0
        self.smooth_y = self.screen_h / 2.0

        # Click state
        self.is_dragging = False
        self.last_click_time = 0.0
        self.click_cooldown = 0.3  # seconds between clicks

        # Lost hand tracking
        self.frames_without_hand = 0
        self.max_frames_without_hand = 10


def _get_landmark_position(detection, landmark_idx, frame_w, frame_h):
    """Extract a landmark's frame-pixel position from a HailoDetection.

    Landmarks are stored relative to the detection bbox in [0,1] coords.
    Returns (pixel_x, pixel_y) in frame coordinates, or None.
    """
    landmarks_list = detection.get_objects_typed(hailo.HAILO_LANDMARKS)
    if not landmarks_list:
        return None

    points = landmarks_list[0].get_points()
    if landmark_idx >= len(points):
        return None

    point = points[landmark_idx]
    bbox = detection.get_bbox()

    # Landmark is bbox-relative [0,1] -> frame-relative -> pixel
    px = (bbox.xmin() + point.x() * bbox.width()) * frame_w
    py = (bbox.ymin() + point.y() * bbox.height()) * frame_h
    return px, py


def _pinch_distance(detection, frame_w, frame_h):
    """Compute normalized distance between thumb tip and index tip."""
    thumb = _get_landmark_position(detection, THUMB_TIP, frame_w, frame_h)
    index = _get_landmark_position(detection, INDEX_TIP, frame_w, frame_h)
    if thumb is None or index is None:
        return float("inf")

    dx = (thumb[0] - index[0]) / frame_w
    dy = (thumb[1] - index[1]) / frame_h
    return math.sqrt(dx * dx + dy * dy)


def app_callback(element, buffer, user_data):
    """Process each frame: extract hand position and control mouse."""
    if buffer is None:
        return

    pad = element.get_static_pad("src")
    _, width, height = get_caps_from_pad(pad)
    if width is None:
        return

    roi = hailo.get_roi_from_buffer(buffer)
    detections = roi.get_objects_typed(hailo.HAILO_DETECTION)

    # Find the first hand detection with landmarks
    hand_det = None
    for det in detections:
        if det.get_label() == "hand" and det.get_objects_typed(hailo.HAILO_LANDMARKS):
            hand_det = det
            break

    if hand_det is None:
        user_data.frames_without_hand += 1
        if user_data.frames_without_hand > user_data.max_frames_without_hand:
            # Release drag if hand is lost
            if user_data.is_dragging:
                user_data.mouse.release(Button.left)
                user_data.is_dragging = False
        return

    user_data.frames_without_hand = 0

    # Get index fingertip position for cursor
    index_pos = _get_landmark_position(hand_det, INDEX_TIP, width, height)
    if index_pos is None:
        return

    # Map camera coordinates to screen coordinates.
    norm_x = index_pos[0] / width
    norm_y = index_pos[1] / height

    # Mirror horizontally: camera left = your right, so flip for natural control
    norm_x = 1.0 - norm_x

    # Speed controls what fraction of the frame covers the full screen.
    # speed=1.0 → full frame, speed=1.5 → inner 67%, speed=2.0 → inner 50%.
    # This avoids separate dead zones from a stacked multiplier.
    margin = max(0.0, (1.0 - 1.0 / user_data.speed) / 2.0)
    zone_size = 1.0 - 2.0 * margin
    target_x = (norm_x - margin) / zone_size
    target_y = (norm_y - margin) / zone_size

    # Clamp to [0,1]
    target_x = max(0.0, min(1.0, target_x))
    target_y = max(0.0, min(1.0, target_y))

    # Scale to screen pixels
    target_px = target_x * user_data.screen_w
    target_py = target_y * user_data.screen_h

    # Apply exponential smoothing
    alpha = 1.0 - user_data.smoothing
    user_data.smooth_x = user_data.smooth_x * user_data.smoothing + target_px * alpha
    user_data.smooth_y = user_data.smooth_y * user_data.smoothing + target_py * alpha

    # Move cursor
    user_data.mouse.position = (int(user_data.smooth_x), int(user_data.smooth_y))

    if user_data.no_click:
        return

    # Detect pinch for click
    pinch_dist = _pinch_distance(hand_det, width, height)
    is_pinching = pinch_dist < user_data.pinch_threshold

    # Get gesture classification
    gesture = None
    classifications = hand_det.get_objects_typed(hailo.HAILO_CLASSIFICATION)
    for cls in classifications:
        if cls.get_classification_type() == "gesture":
            gesture = cls.get_label()
            break

    now = time.monotonic()

    if is_pinching:
        if gesture == "FIST" and not user_data.is_dragging:
            # Start drag
            user_data.mouse.press(Button.left)
            user_data.is_dragging = True
            hailo_logger.debug("Drag started")
        elif not user_data.is_dragging and (now - user_data.last_click_time) > user_data.click_cooldown:
            # Single click
            user_data.mouse.click(Button.left)
            user_data.last_click_time = now
            hailo_logger.debug("Click at (%d, %d)", int(user_data.smooth_x), int(user_data.smooth_y))
    else:
        if user_data.is_dragging:
            # Release drag
            user_data.mouse.release(Button.left)
            user_data.is_dragging = False
            hailo_logger.debug("Drag released")

    # Throttled status logging
    if user_data.frame_count % 60 == 0:
        hailo_logger.info(
            "Cursor: (%d, %d) | Gesture: %s | Pinch: %.3f",
            int(user_data.smooth_x), int(user_data.smooth_y),
            gesture or "none", pinch_dist,
        )


def main():
    user_data = GestureMouseCallback()
    app = GStreamerGestureMouseApp(app_callback, user_data)

    # Apply CLI args after pipeline is constructed
    user_data.smoothing = app.options_menu.smoothing
    user_data.pinch_threshold = app.options_menu.pinch_threshold
    user_data.speed = app.options_menu.speed
    user_data.no_click = app.options_menu.no_click

    hailo_logger.info(
        "Gesture Mouse started (smoothing=%.2f, pinch_threshold=%.3f, speed=%.1f, click=%s)",
        user_data.smoothing, user_data.pinch_threshold, user_data.speed,
        "disabled" if user_data.no_click else "enabled",
    )
    app.run()


if __name__ == "__main__":
    main()
