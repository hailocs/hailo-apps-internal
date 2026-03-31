"""
Easter Eggs Game — Catch eggs with your hands using pose estimation.

A custom background is displayed with Easter eggs placed at random positions.
The user catches eggs by moving their wrists close to the egg. Each catch
scores a point and a new egg spawns at a random location.
"""

import math
import random
import time

import cv2
import numpy as np

import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst

import hailo

from hailo_apps.python.core.common.buffer_utils import (
    get_caps_from_pad,
    get_numpy_from_buffer,
)
from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.common.parser import get_pipeline_parser
from hailo_apps.python.core.gstreamer.gstreamer_app import app_callback_class
from hailo_apps.python.pipeline_apps.pose_estimation.pose_estimation_pipeline import (
    GStreamerPoseEstimationApp,
)

logger = get_logger(__name__)

# Pose keypoint indices for wrists
LEFT_WRIST = 9
RIGHT_WRIST = 10

# Game constants
CATCH_RADIUS = 60          # Pixel radius for catching an egg
EGG_WIDTH = 50             # Egg drawing width
EGG_HEIGHT = 65            # Egg drawing height
GAME_DURATION = 60         # Seconds
SPAWN_MARGIN = 80          # Margin from edges for egg placement
HAND_MARKER_RADIUS = 18    # Drawn hand circle radius


def _draw_egg(frame, cx, cy, scale=1.0):
    """Draw a colourful Easter egg centred at (cx, cy) on *frame*."""
    w = int(EGG_WIDTH * scale)
    h = int(EGG_HEIGHT * scale)

    # Egg body (ellipse)
    cv2.ellipse(frame, (cx, cy), (w // 2, h // 2), 0, 0, 360, (80, 200, 255), -1)
    cv2.ellipse(frame, (cx, cy), (w // 2, h // 2), 0, 0, 360, (40, 100, 180), 2)

    # Decorative stripes
    stripe_gap = h // 5
    for i, colour in enumerate([(255, 100, 100), (100, 255, 100), (100, 100, 255)]):
        y_off = -stripe_gap + i * stripe_gap
        cv2.ellipse(
            frame,
            (cx, cy + y_off),
            (w // 2 - 4, 5),
            0, 0, 360,
            colour, -1,
        )

    # Highlight
    cv2.ellipse(
        frame,
        (cx - w // 6, cy - h // 5),
        (w // 8, h // 8),
        -30, 0, 360,
        (255, 255, 255), -1,
    )


def _spawn_egg(width, height):
    """Return a random (x, y) position within the frame margins."""
    x = random.randint(SPAWN_MARGIN, max(SPAWN_MARGIN + 1, width - SPAWN_MARGIN))
    y = random.randint(SPAWN_MARGIN, max(SPAWN_MARGIN + 1, height - SPAWN_MARGIN))
    return x, y


class EasterEggCallback(app_callback_class):
    """Per-frame game state."""

    def __init__(self, background_path):
        super().__init__()
        self.use_frame = True  # will be enforced again in app __init__

        # Game state
        self.score = 0
        self.egg_x = 0
        self.egg_y = 0
        self.egg_placed = False
        self.start_time = None
        self.game_over = False

        # Background
        self._bg_path = background_path
        self._background = None  # loaded lazily once we know frame size
        self._bg_loaded = False


    def get_background(self, width, height):
        """Load and resize the background image once."""
        if not self._bg_loaded:
            self._bg_loaded = True
            if self._bg_path:
                img = cv2.imread(self._bg_path)
                if img is not None:
                    img = cv2.resize(img, (width, height))
                    # Convert BGR→RGB to match GStreamer frame colour space
                    self._background = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                    logger.info("Loaded background: %s (%dx%d)", self._bg_path, width, height)
                else:
                    logger.warning("Could not load background image: %s", self._bg_path)
        return self._background


def app_callback(element, buffer, user_data):
    """Per-frame callback — game logic runs here."""
    pad = element.get_static_pad("src")
    fmt, width, height = get_caps_from_pad(pad)

    frame = None
    if user_data.use_frame and fmt and width and height:
        frame = get_numpy_from_buffer(buffer, fmt, width, height)

    if frame is None:
        return Gst.FlowReturn.OK

    # ----- Build output frame (custom background, NOT camera feed) -----
    bg = user_data.get_background(width, height)
    if bg is not None:
        output = bg.copy()
    else:
        output = np.zeros((height, width, 3), dtype=np.uint8)

    # ----- Timer -----
    now = time.time()
    if user_data.start_time is None:
        user_data.start_time = now
    elapsed = now - user_data.start_time
    remaining = max(0, GAME_DURATION - elapsed)

    if remaining <= 0:
        user_data.game_over = True

    # ----- Spawn egg if needed -----
    if not user_data.egg_placed and not user_data.game_over:
        user_data.egg_x, user_data.egg_y = _spawn_egg(width, height)
        user_data.egg_placed = True

    # ----- Extract hand positions from pose detections -----
    hand_positions = []
    roi = hailo.get_roi_from_buffer(buffer)
    detections = roi.get_objects_typed(hailo.HAILO_DETECTION)

    for detection in detections:
        if detection.get_label() != "person":
            continue

        bbox = detection.get_bbox()
        landmarks = detection.get_objects_typed(hailo.HAILO_LANDMARKS)
        if not landmarks:
            continue

        points = landmarks[0].get_points()

        for kp_idx in (LEFT_WRIST, RIGHT_WRIST):
            pt = points[kp_idx]
            px = int((pt.x() * bbox.width() + bbox.xmin()) * width)
            py = int((pt.y() * bbox.height() + bbox.ymin()) * height)
            hand_positions.append((px, py))

    # ----- Check catch -----
    if user_data.egg_placed and not user_data.game_over:
        for hx, hy in hand_positions:
            dist = math.hypot(hx - user_data.egg_x, hy - user_data.egg_y)
            if dist < CATCH_RADIUS:
                user_data.score += 1
                user_data.egg_placed = False  # will respawn next frame
                logger.info("Egg caught! Score: %d", user_data.score)
                break

    # ----- Draw egg -----
    if user_data.egg_placed and not user_data.game_over:
        _draw_egg(output, user_data.egg_x, user_data.egg_y)

    # ----- Draw hand markers -----
    for hx, hy in hand_positions:
        cv2.circle(output, (hx, hy), HAND_MARKER_RADIUS, (0, 255, 100), -1)
        cv2.circle(output, (hx, hy), HAND_MARKER_RADIUS, (255, 255, 255), 2)

    # ----- HUD: score + timer -----
    hud_colour = (255, 255, 255)
    cv2.putText(
        output,
        f"Score: {user_data.score}",
        (20, 50),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.4,
        hud_colour,
        3,
    )
    cv2.putText(
        output,
        f"Time: {int(remaining)}s",
        (20, 100),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.2,
        hud_colour,
        2,
    )

    # ----- Game over screen -----
    if user_data.game_over:
        overlay = output.copy()
        cv2.rectangle(overlay, (0, 0), (width, height), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.6, output, 0.4, 0, output)
        cv2.putText(
            output,
            "GAME OVER",
            (width // 2 - 200, height // 2 - 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            2.5,
            (80, 200, 255),
            4,
        )
        cv2.putText(
            output,
            f"Final Score: {user_data.score}",
            (width // 2 - 180, height // 2 + 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.5,
            (255, 255, 255),
            3,
        )

    # ----- Publish frame (RGB → BGR for display) -----
    output = cv2.cvtColor(output, cv2.COLOR_RGB2BGR)
    user_data.set_frame(output)

    return Gst.FlowReturn.OK


class EasterEggsGameApp(GStreamerPoseEstimationApp):
    """Easter-egg-catching game built on top of the pose estimation pipeline."""

    def __init__(self, app_callback_func, user_data, parser=None):
        if parser is None:
            parser = get_pipeline_parser()
        parser.add_argument(
            "--background",
            type=str,
            default=None,
            help="Path to background image (PNG/JPG).",
        )
        super().__init__(app_callback_func, user_data, parser)

        # Force use_frame (overwritten by GStreamerApp.__init__)
        self.options_menu.use_frame = True
        user_data.use_frame = True

        logger.info("Easter Eggs Game initialised — catch eggs with your hands!")


def main():
    import sys

    # Pre-parse --background before pipeline parser consumes args
    bg_path = None
    for i, arg in enumerate(sys.argv):
        if arg == "--background" and i + 1 < len(sys.argv):
            bg_path = sys.argv[i + 1]

    user_data = EasterEggCallback(background_path=bg_path)
    app = EasterEggsGameApp(app_callback, user_data)
    app.run()


if __name__ == "__main__":
    main()
