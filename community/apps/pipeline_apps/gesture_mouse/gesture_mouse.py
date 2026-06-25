"""
Gesture-controlled mouse using Hailo (8 / 8L / 10H) hand tracking.

Maps the palm center to the screen cursor. Pinch (thumb+index) to click.
Fist while pinching to drag. Release the pinch to release the drag.

Gestures:
  - POINTING / ONE / TWO+ fingers: Move cursor (palm-center position)
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

# pynput needs a display/input backend (X11 or Wayland) and fails to import on
# a headless host. Defer the failure so the pipeline can still run with
# --no-click (cursor metadata only), and so importing this module for tests or
# inspection never hard-crashes. Button/MouseController are resolved lazily.
try:
    from pynput.mouse import Button, Controller as MouseController
    _PYNPUT_IMPORT_ERROR = None
except Exception as exc:  # ImportError, or backend/display errors on import
    Button = None
    MouseController = None
    _PYNPUT_IMPORT_ERROR = exc

from hailo_apps.python.core.common.buffer_utils import get_caps_from_pad
from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.gstreamer.gstreamer_app import app_callback_class

from community.apps.pipeline_apps.gesture_mouse.gesture_mouse_pipeline import (
    GStreamerGestureMouseApp,
)

hailo_logger = get_logger(__name__)

# Hand landmark indices (MediaPipe — 21-keypoint hand model)
WRIST = 0
INDEX_MCP = 5
MIDDLE_MCP = 9
RING_MCP = 13
PINKY_MCP = 17
THUMB_TIP = 4
INDEX_TIP = 8

# Anchor landmarks for the palm center — the average of these 5 points stays
# put when the thumb or fingers move, so the cursor doesn't jerk during the
# pinch click. The wrist + 4 MCP joints define the rigid palm.
PALM_ANCHOR_LANDMARKS = (WRIST, INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP)


class GestureMouseCallback(app_callback_class):
    """Tracks hand position and controls the mouse cursor."""

    def __init__(self):
        super().__init__()
        # Create the pynput mouse controller lazily/defensively: it needs a
        # display/input backend and can fail on headless or Wayland hosts.
        # When it can't be created, mouse actions are skipped (with a one-time
        # warning) instead of crashing the whole pipeline.
        if MouseController is not None:
            try:
                self.mouse = MouseController()
            except Exception as exc:  # backend/display errors at runtime
                self.mouse = None
                hailo_logger.warning(
                    "Could not initialize the mouse controller (%s). Mouse "
                    "actions are disabled. A display (X11/Wayland) is required.",
                    exc,
                )
        else:
            self.mouse = None
            hailo_logger.warning(
                "pynput is unavailable (%s). Mouse actions are disabled. "
                "Install it with 'pip install pynput' and run with a display "
                "(X11/Wayland) to enable cursor control.",
                _PYNPUT_IMPORT_ERROR,
            )
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


def _palm_center_position(detection, frame_w, frame_h):
    """Return the average pixel position of the palm anchor landmarks.

    Uses the wrist + 4 MCP joints — these define the rigid palm and stay put
    when the thumb or fingers move (e.g., during a pinch click).
    Returns (px, py) in frame pixels, or None if any landmark is unavailable.
    """
    xs = []
    ys = []
    for idx in PALM_ANCHOR_LANDMARKS:
        pos = _get_landmark_position(detection, idx, frame_w, frame_h)
        if pos is None:
            return None
        xs.append(pos[0])
        ys.append(pos[1])
    return sum(xs) / len(xs), sum(ys) / len(ys)


def _pinch_distance(detection, frame_w, frame_h):
    """Compute normalized distance between thumb tip and index tip."""
    thumb = _get_landmark_position(detection, THUMB_TIP, frame_w, frame_h)
    index = _get_landmark_position(detection, INDEX_TIP, frame_w, frame_h)
    if thumb is None or index is None:
        return float("inf")

    dx = (thumb[0] - index[0]) / frame_w
    dy = (thumb[1] - index[1]) / frame_h
    return math.sqrt(dx * dx + dy * dy)


def map_index_to_screen(norm_x, norm_y, speed, screen_w, screen_h):
    """Map normalized camera coords (index fingertip) to target screen pixel.

    - Mirrors X so camera-left becomes user-right (natural mirror behaviour).
    - 'speed' defines a centered zone inside the camera frame that, when the
      fingertip is fully traversed, covers the full screen:
        speed=1.0 -> full frame maps to full screen.
        speed=2.0 -> inner 50% of frame maps to full screen.
        speed<1.0 is degenerate (margin clamped to 0).
    - Output is clamped to [0, screen_w] x [0, screen_h].
    """
    norm_x = 1.0 - norm_x
    margin = max(0.0, (1.0 - 1.0 / speed) / 2.0) if speed > 0 else 0.0
    zone_size = 1.0 - 2.0 * margin
    if zone_size <= 0:
        # Degenerate speed; fall back to identity mapping
        target_x = norm_x
        target_y = norm_y
    else:
        target_x = (norm_x - margin) / zone_size
        target_y = (norm_y - margin) / zone_size
    target_x = max(0.0, min(1.0, target_x))
    target_y = max(0.0, min(1.0, target_y))
    return target_x * screen_w, target_y * screen_h


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
            if user_data.is_dragging and user_data.mouse is not None:
                user_data.mouse.release(Button.left)
                user_data.is_dragging = False
        return

    user_data.frames_without_hand = 0

    # No usable mouse backend (headless/Wayland/missing pynput): skip all
    # cursor and click actions. The pipeline still runs and logs gestures.
    if user_data.mouse is None:
        return

    # Anchor cursor on the palm center (rigid: wrist + 4 MCP joints) rather
    # than the index fingertip, so the pinch click doesn't pull the cursor.
    palm_pos = _palm_center_position(hand_det, width, height)
    if palm_pos is None:
        return

    # Map camera coordinates to screen coordinates via the pure helper.
    norm_x = palm_pos[0] / width
    norm_y = palm_pos[1] / height
    target_px, target_py = map_index_to_screen(
        norm_x, norm_y, user_data.speed, user_data.screen_w, user_data.screen_h,
    )

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
        if user_data.is_dragging:
            # Already dragging and still pinching: hold the button down.
            # (Do nothing — the press from a previous frame persists.)
            pass
        elif gesture == "FIST":
            # Start drag
            user_data.mouse.press(Button.left)
            user_data.is_dragging = True
            hailo_logger.debug("Drag started")
        elif (now - user_data.last_click_time) > user_data.click_cooldown:
            # Single click
            user_data.mouse.click(Button.left)
            user_data.last_click_time = now
            hailo_logger.debug("Click at (%d, %d)", int(user_data.smooth_x), int(user_data.smooth_y))
    else:
        if user_data.is_dragging:
            # Released the pinch: release drag
            user_data.mouse.release(Button.left)
            user_data.is_dragging = False
            hailo_logger.debug("Drag released")

    # Throttled status logging (skip frame 0)
    if user_data.frame_count > 0 and user_data.frame_count % 60 == 0:
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
