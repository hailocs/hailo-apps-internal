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
from community.apps.pipeline_apps.rhythm_royale.motion_analyzer import (
    MotionAnalyzer, TrackScore,
)
from community.apps.pipeline_apps.rhythm_royale.player_ranker import (
    Bbox, PlayerRanker,
)
from community.apps.pipeline_apps.rhythm_royale import overlay


logger = get_logger(__name__)


KEYPOINT_NAMES = [
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle",
]


DEBUG_VIZ_CHOICES = ("off", "standard", "full")


# Dancer-tag colors used on the phase clock so the operator can tie a dot
# to a specific dancer. Picked from a short cycle.
_DANCER_PALETTE = [
    (255, 110, 110), (110, 220, 255), (255, 220, 80),
    (140, 255, 140), (255, 160, 220), (180, 180, 255),
]


def _dancer_color(track_id: int) -> Tuple[int, int, int]:
    return _DANCER_PALETTE[track_id % len(_DANCER_PALETTE)]


class RhythmRoyaleCallback(app_callback_class):
    def __init__(self, max_players: int = 4, debug_viz: str = "full"):
        super().__init__()
        self.use_frame = True
        self.audio_source: AudioSource | None = None
        self.beat_extractor: BeatExtractor | None = None
        self.motion: MotionAnalyzer = MotionAnalyzer(fps_hint=30.0)
        self.ranker: PlayerRanker = PlayerRanker(max_players=max_players)
        self.t0: float = time.monotonic()
        self.latest_scores: Dict[int, float] = {}
        self.debug_viz: str = debug_viz  # "off" | "standard" | "full"


def _extract_keypoints(detection, width: int, height: int
                       ) -> Tuple[Dict[str, Tuple[float, float]], Dict[str, float]]:
    """Return (kp_xy, kp_confidence). Both keyed by KEYPOINT_NAMES."""
    landmarks = detection.get_objects_typed(hailo.HAILO_LANDMARKS)
    if not landmarks:
        return {}, {}
    points = landmarks[0].get_points()
    bbox = detection.get_bbox()
    kp_xy: Dict[str, Tuple[float, float]] = {}
    kp_conf: Dict[str, float] = {}
    for i, name in enumerate(KEYPOINT_NAMES):
        if i >= len(points):
            break
        p = points[i]
        x = (p.x() * bbox.width() + bbox.xmin()) * width
        y = (p.y() * bbox.height() + bbox.ymin()) * height
        kp_xy[name] = (x, y)
        kp_conf[name] = float(p.confidence())
    return kp_xy, kp_conf


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

    # Pass 1 — collect all valid detections (still pose-tracked, valid kp).
    # We update every track's motion buffer (cheap appends) regardless of
    # ranking, so a dancer entering the top-K already has a warm window.
    candidates: Dict[int, Tuple[Dict[str, Tuple[float, float]],
                                 Dict[str, float],
                                 Bbox]] = {}
    for det in detections:
        if det.get_label() != "person":
            continue
        track_id = _get_track_id(det)
        if track_id == 0:
            continue
        kp, kp_conf = _extract_keypoints(det, width, height)
        if not kp:
            continue
        user_data.motion.update_track(track_id, kp, t_now, confidences=kp_conf)
        bbox = det.get_bbox()
        candidates[track_id] = (kp, kp_conf, Bbox(
            xmin=bbox.xmin(), ymin=bbox.ymin(),
            width=bbox.width(), height=bbox.height(),
        ))

    # Pass 2 — rank and score only the top-K.
    selected = user_data.ranker.select(
        [(tid, b) for tid, (_, _, b) in candidates.items()]
    )
    scored: Dict[int, Tuple[TrackScore, Dict[str, Tuple[float, float]],
                            Dict[str, float]]] = {}
    for tid in selected:
        kp, kp_conf, _ = candidates[tid]
        score = user_data.motion.compute_score(tid, beat, t_now)
        if score is None:
            continue
        scored[tid] = (score, kp, kp_conf)
        user_data.latest_scores[tid] = score.value

    user_data.motion.prune_stale(t_now)

    rockstar_id = None
    if scored:
        rockstar_id, (best_score, _, _) = max(
            scored.items(), key=lambda kv: kv[1][0].value,
        )
        if best_score.value < 0.15:
            rockstar_id = None

    show_glow = user_data.debug_viz in ("standard", "full")
    show_ladder = user_data.debug_viz in ("standard", "full")
    show_tape = user_data.debug_viz in ("standard", "full")
    show_clock = user_data.debug_viz == "full"

    # Draw skeletons for every detection (including non-scored ones so the
    # operator still sees who's in frame), score tags only for scored ones.
    for tid, (kp, kp_conf, _bbox) in candidates.items():
        if tid in scored:
            color = (0, 200, 255) if tid == rockstar_id else (200, 200, 200)
            glow = (overlay.per_kp_glow_colors(scored[tid][0].per_kp)
                    if show_glow else None)
        else:
            color = (110, 110, 110)  # dim — present but unranked
            glow = None
        overlay.draw_skeleton(frame, kp, color, kp_conf=kp_conf, kp_colors=glow)
    for tid, (score, kp, _kp_conf) in scored.items():
        overlay.draw_score_tag(frame, kp, tid, score.value,
                               is_rockstar=(tid == rockstar_id))
        if show_ladder:
            overlay.draw_harmonic_ladder(frame, kp, score)

    if beat is not None:
        overlay.draw_beat_pulse(frame, beat.f_beat_hz, beat.phase_rad,
                                t_now, beat.confidence)
    else:
        overlay.draw_beat_pulse(frame, None, 0.0, t_now, 0.0)

    if show_tape and user_data.beat_extractor is not None:
        envelope = user_data.beat_extractor.latest_envelope()
        overlay.draw_beat_tape(frame, envelope, beat, t_now)

    if show_clock:
        dancer_colors = {tid: _dancer_color(tid) for tid in scored}
        overlay.draw_phase_clock(
            frame, beat,
            [(tid, s) for tid, (s, _, _) in scored.items()],
            t_now=t_now, dancer_colors=dancer_colors,
        )

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
    group.add_argument(
        "--debug-viz", choices=DEBUG_VIZ_CHOICES, default="full",
        help="Overlay verbosity. 'off' keeps only score tags + beat badge; "
             "'standard' adds beat tape, harmonic ladder, per-kp glow; "
             "'full' also adds phase clock.",
    )
    group.add_argument(
        "--max-players", type=int, default=4,
        help="Hard cap on the number of dancers scored per frame (others "
             "still get their skeleton drawn).",
    )
    return parser


def main():
    parser = _build_parser()
    args, _ = parser.parse_known_args()

    user_data = RhythmRoyaleCallback(
        max_players=args.max_players,
        debug_viz=args.debug_viz,
    )

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
