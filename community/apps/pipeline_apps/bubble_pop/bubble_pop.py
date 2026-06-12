"""Bubble Pop — pop floating bubble hearts with your hands and magic!

A pose-estimation mirror game: heart-shaped bubbles drift up from the
bottom of the screen and pop when you touch them with your wrists. Every
pop bursts into particles, plays a pop sound, and bumps the score. Both
wrists of every detected person can pop — perfect for two players.

Arm gestures cast magic (all spells blow up hearts too):
    hands together   -> SHOCKWAVE   (expanding ring pops everything it hits)
    both arms up     -> GLITTER RAIN (sparkle rain pops hearts for 3 s)
    fast hand flick  -> MAGIC BOLT  (shooting star pops hearts on its path)

The skeleton overlay is intentionally NOT drawn: instead each wrist gets a
glittery sparkle trail. The display is mirrored by default so it behaves
like a real mirror.

Usage:
    ./run.sh --input usb
    ./run.sh --input usb --max-bubbles 8 --spawn-interval 0.5   # calmer
    ./run.sh --input usb --no-sound --no-mirror
"""
from __future__ import annotations

import os
import sys
import time

# Make `community.*` importable when launched directly.
_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

os.environ["GST_PLUGIN_FEATURE_RANK"] = "vaapidecodebin:NONE"

import cv2
import hailo
from gi.repository import Gst

from hailo_apps.python.core.common.buffer_utils import (
    get_caps_from_pad,
    get_numpy_from_buffer,
)
from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.common.parser import get_pipeline_parser
from hailo_apps.python.core.gstreamer.gstreamer_app import app_callback_class
from hailo_apps.python.core.gstreamer.gstreamer_helper_pipelines import (
    DISPLAY_PIPELINE,
    INFERENCE_PIPELINE,
    INFERENCE_PIPELINE_WRAPPER,
    TRACKER_PIPELINE,
    USER_CALLBACK_PIPELINE,
)
from hailo_apps.python.pipeline_apps.pose_estimation.pose_estimation_pipeline import (
    GStreamerPoseEstimationApp,
)

from community.apps.pipeline_apps.bubble_pop.bubble_engine import BubbleGame
from community.apps.pipeline_apps.bubble_pop.gestures import (
    GestureCaster,
    PersonPose,
)
from community.apps.pipeline_apps.bubble_pop.sound import PopSound

logger = get_logger(__name__)

# COCO pose keypoint indices
NOSE = 0
LEFT_SHOULDER = 5
RIGHT_SHOULDER = 6
LEFT_WRIST = 9
RIGHT_WRIST = 10
WRIST_CONF_THRESHOLD = 0.4


class BubblePopCallback(app_callback_class):
    def __init__(self, game: BubbleGame, sound: PopSound, mirror: bool = True):
        super().__init__()
        self.use_frame = True
        self.game = game
        self.sound = sound
        self.mirror = mirror
        self.caster: GestureCaster | None = None  # built once frame size known
        self.last_t: float | None = None


def _get_track_id(detection) -> int:
    tracks = detection.get_objects_typed(hailo.HAILO_UNIQUE_ID)
    return tracks[0].get_id() if len(tracks) == 1 else 0


def _person_pose(detection, width: int, height: int) -> PersonPose | None:
    """Extract the magic-relevant keypoints of one detection."""
    landmarks = detection.get_objects_typed(hailo.HAILO_LANDMARKS)
    if not landmarks:
        return None
    points = landmarks[0].get_points()
    bbox = detection.get_bbox()

    def kp(idx):
        if idx >= len(points):
            return None
        p = points[idx]
        if p.confidence() < WRIST_CONF_THRESHOLD:
            return None
        return ((p.x() * bbox.width() + bbox.xmin()) * width,
                (p.y() * bbox.height() + bbox.ymin()) * height)

    ls, rs = kp(LEFT_SHOULDER), kp(RIGHT_SHOULDER)
    shoulder_width = abs(ls[0] - rs[0]) if (ls and rs) else None
    pose = PersonPose(
        left_wrist=kp(LEFT_WRIST),
        right_wrist=kp(RIGHT_WRIST),
        nose=kp(NOSE),
        shoulder_width=shoulder_width,
    )
    return pose if pose.wrists else None


def app_callback(element, buffer, user_data: BubblePopCallback):
    if buffer is None:
        return Gst.FlowReturn.OK

    pad = element.get_static_pad("src")
    fmt, width, height = get_caps_from_pad(pad)
    if not (user_data.use_frame and fmt and width and height):
        return Gst.FlowReturn.OK

    frame = get_numpy_from_buffer(buffer, fmt, width, height)

    # Collect keypoints from ALL detected people (multi-player!)
    roi = hailo.get_roi_from_buffer(buffer)
    people = {}
    for detection in roi.get_objects_typed(hailo.HAILO_DETECTION):
        if detection.get_label() != "person":
            continue
        pose = _person_pose(detection, width, height)
        if pose:
            people[_get_track_id(detection)] = pose

    if user_data.mirror:
        frame = cv2.flip(frame, 1)
        people = {tid: p.mirrored(width) for tid, p in people.items()}

    wrists = [w for p in people.values() for w in p.wrists]

    t = time.monotonic()
    dt = 1.0 / 30.0 if user_data.last_t is None else min(t - user_data.last_t, 0.1)
    user_data.last_t = t

    # Magic gestures → cast spells
    if user_data.caster is None:
        user_data.caster = GestureCaster(frame_height=height)
    events = user_data.caster.update(t, people)
    for event in events:
        user_data.game.cast(event, t)
    if events:
        user_data.sound.play_cast()

    popped = user_data.game.update(dt, t, wrists, width, height)
    if popped:
        user_data.sound.play()

    user_data.game.draw(frame, wrists)

    frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    user_data.set_frame(frame)
    return Gst.FlowReturn.OK


class BubblePopApp(GStreamerPoseEstimationApp):
    """Pose pipeline whose GStreamer display is a fakesink — the game is
    rendered exclusively in the user-frame window, so no skeleton overlay
    ever appears."""

    def __init__(self, app_callback, user_data, parser=None):
        super().__init__(app_callback, user_data, parser)
        # CRITICAL: force use_frame ON regardless of CLI default
        self.options_menu.use_frame = True
        user_data.use_frame = True

    def get_pipeline_string(self):
        infer_pipeline = INFERENCE_PIPELINE(
            hef_path=self.hef_path,
            post_process_so=self.post_process_so,
            post_function_name=self.post_process_function,
            batch_size=self.batch_size,
        )
        pipeline_string = (
            f"{self.get_source_pipeline()} ! "
            f"{INFERENCE_PIPELINE_WRAPPER(infer_pipeline)} ! "
            f"{TRACKER_PIPELINE(class_id=0)} ! "
            f"{USER_CALLBACK_PIPELINE()} ! "
            f"{DISPLAY_PIPELINE(video_sink='fakesink', sync=self.sync, show_fps=self.show_fps)}"
        )
        logger.debug("Pipeline string: %s", pipeline_string)
        return pipeline_string


def _build_parser():
    parser = get_pipeline_parser()
    group = parser.add_argument_group("bubble_pop")
    group.add_argument(
        "--max-bubbles", type=int, default=40,
        help="Maximum number of hearts on screen at once (default: 40)",
    )
    group.add_argument(
        "--spawn-interval", type=float, default=0.08,
        help="Average seconds between new hearts (default: 0.08)",
    )
    group.add_argument(
        "--no-mirror", action="store_true",
        help="Disable the mirror (horizontal flip) effect",
    )
    group.add_argument(
        "--no-sound", action="store_true",
        help="Disable the pop sound",
    )
    return parser


def main():
    parser = _build_parser()
    args, _ = parser.parse_known_args()

    game = BubbleGame(
        max_bubbles=args.max_bubbles,
        spawn_interval=args.spawn_interval,
    )
    sound = PopSound(enabled=not args.no_sound)
    user_data = BubblePopCallback(game, sound, mirror=not args.no_mirror)

    app = BubblePopApp(app_callback, user_data, parser)
    app.run()


if __name__ == "__main__":
    main()
