"""Rhythm Royale — pose-based dance battle scored against the music beat.

Real-time input is microphone / line-in. The optional --audio-file flag is
for development and reproducible testing — it plays back an MP3 file and
analyzes the same playback stream.

Usage:
    # Real-time (microphone / line-in)
    ./run.sh --input usb --use-frame

    # Real-time with a specific input device (e.g. line-in or loopback)
    ./run.sh --input usb --use-frame --audio-device "Loopback"

    # Dev / testing with an MP3 file
    ./run.sh --input usb --use-frame --audio-file path/to/song.mp3
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Dict, Tuple

# Make `community.*` importable when launched directly.
_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

os.environ["GST_PLUGIN_FEATURE_RANK"] = "vaapidecodebin:NONE"

import cv2
import hailo
import numpy as np
from gi.repository import Gst

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

from community.apps.pipeline_apps.rhythm_royale.audio_source import AudioSource
from community.apps.pipeline_apps.rhythm_royale.beat_extractor import BeatExtractor
from community.apps.pipeline_apps.rhythm_royale.motion_analyzer import MotionAnalyzer
from community.apps.pipeline_apps.rhythm_royale import overlay


logger = get_logger(__name__)


KEYPOINT_NAMES = [
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle",
]


class RhythmRoyaleCallback(app_callback_class):
    def __init__(self):
        super().__init__()
        self.use_frame = True
        self.audio_source: AudioSource | None = None
        self.beat_extractor: BeatExtractor | None = None
        self.motion: MotionAnalyzer = MotionAnalyzer(fps_hint=30.0)
        self.t0: float = time.monotonic()
        self.latest_scores: Dict[int, float] = {}


def _extract_keypoints(detection, width: int, height: int) -> Dict[str, Tuple[float, float]]:
    landmarks = detection.get_objects_typed(hailo.HAILO_LANDMARKS)
    if not landmarks:
        return {}
    points = landmarks[0].get_points()
    bbox = detection.get_bbox()
    out: Dict[str, Tuple[float, float]] = {}
    for i, name in enumerate(KEYPOINT_NAMES):
        if i >= len(points):
            break
        p = points[i]
        x = (p.x() * bbox.width() + bbox.xmin()) * width
        y = (p.y() * bbox.height() + bbox.ymin()) * height
        out[name] = (x, y)
    return out


def _get_track_id(detection) -> int:
    tracks = detection.get_objects_typed(hailo.HAILO_UNIQUE_ID)
    return tracks[0].get_id() if len(tracks) == 1 else 0


def app_callback(element, buffer, user_data: RhythmRoyaleCallback):
    if buffer is None:
        return Gst.FlowReturn.OK

    pad = element.get_static_pad("src")
    fmt, width, height = get_caps_from_pad(pad)
    if not (user_data.use_frame and fmt and width and height):
        return Gst.FlowReturn.OK

    frame = get_numpy_from_buffer(buffer, fmt, width, height)
    if frame is None:
        return Gst.FlowReturn.OK

    t_now = time.monotonic() - user_data.t0

    roi = hailo.get_roi_from_buffer(buffer)
    detections = roi.get_objects_typed(hailo.HAILO_DETECTION)

    beat = user_data.beat_extractor.latest() if user_data.beat_extractor else None
    scores: Dict[int, Tuple[float, Dict[str, Tuple[float, float]]]] = {}

    for det in detections:
        if det.get_label() != "person":
            continue
        track_id = _get_track_id(det)
        if track_id == 0:
            continue
        kp = _extract_keypoints(det, width, height)
        if not kp:
            continue
        user_data.motion.update_track(track_id, kp, t_now)
        score = user_data.motion.compute_score(track_id, beat, t_now)
        value = score.value if score is not None else 0.0
        scores[track_id] = (value, kp)
        user_data.latest_scores[track_id] = value

    user_data.motion.prune_stale(t_now)

    rockstar_id = None
    if scores:
        best_id, (best_v, _) = max(scores.items(), key=lambda kv: kv[1][0])
        if best_v >= 0.15:
            rockstar_id = best_id

    for track_id, (value, kp) in scores.items():
        color = (0, 200, 255) if track_id == rockstar_id else (200, 200, 200)
        overlay.draw_skeleton(frame, kp, color)
        overlay.draw_score_tag(frame, kp, track_id, value,
                               is_rockstar=(track_id == rockstar_id))

    if beat is not None:
        overlay.draw_beat_pulse(frame, beat.f_beat_hz, beat.phase_rad,
                                t_now, beat.confidence)
    else:
        overlay.draw_beat_pulse(frame, None, 0.0, t_now, 0.0)

    frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    user_data.set_frame(frame)
    return Gst.FlowReturn.OK


class RhythmRoyaleApp(GStreamerPoseEstimationApp):
    def __init__(self, app_callback, user_data, parser):
        super().__init__(app_callback, user_data, parser)
        # CRITICAL: force use_frame ON regardless of CLI default
        self.options_menu.use_frame = True
        user_data.use_frame = True


def _build_parser() -> argparse.ArgumentParser:
    parser = get_pipeline_parser()
    group = parser.add_argument_group("rhythm_royale")
    group.add_argument(
        "--audio-file", type=str, default=None,
        help="MP3/WAV/FLAC file. Plays back through the system output and "
             "analyzes the same stream. Intended for development/testing — "
             "in production, use mic or line-in via --audio-device.",
    )
    group.add_argument(
        "--audio-device", type=str, default=None,
        help="sounddevice input device name (microphone / line-in / loopback). "
             "Default: system default input device.",
    )
    group.add_argument(
        "--audio-rate", type=int, default=44100,
        help="Capture sample rate (default 44100 Hz). Ignored for --audio-file.",
    )
    group.add_argument(
        "--no-playback", action="store_true",
        help="Disable playback when using --audio-file (just analyze).",
    )
    return parser


def main():
    parser = _build_parser()
    args, _ = parser.parse_known_args()

    user_data = RhythmRoyaleCallback()

    if args.audio_file:
        logger.info("Audio: file %s (playback=%s)",
                    args.audio_file, not args.no_playback)
        audio = AudioSource.from_file(args.audio_file,
                                      playback=not args.no_playback)
    else:
        logger.info("Audio: mic/line-in device=%s rate=%d",
                    args.audio_device or "default", args.audio_rate)
        audio = AudioSource.from_mic(device=args.audio_device,
                                     sample_rate=args.audio_rate)

    audio.start()
    beat = BeatExtractor(audio, update_hz=10.0)
    beat.start()
    user_data.audio_source = audio
    user_data.beat_extractor = beat

    app = RhythmRoyaleApp(app_callback, user_data, parser=parser)
    try:
        app.run()
    finally:
        if user_data.beat_extractor is not None:
            user_data.beat_extractor.stop()
        if user_data.audio_source is not None:
            user_data.audio_source.stop()


if __name__ == "__main__":
    main()
