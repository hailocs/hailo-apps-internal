"""Tracker factory — create tracker instances by name.

Supported trackers:
    - ``byte`` (default): ByteTracker — lightweight, no extra deps
    - ``fast``: FastTracker — occlusion-aware
"""

from __future__ import annotations

import argparse

from .tracker import Tracker


TRACKER_CHOICES = ("byte", "fast")
DEFAULT_TRACKER = "byte"


def create_tracker(name: str, *, track_thresh: float = 0.4,
                   track_buffer: int = 90, match_thresh: float = 0.5,
                   frame_rate: int = 30) -> Tracker:
    """Instantiate a tracker by name.

    Args:
        name: One of "byte" or "fast".
        track_thresh: Detection confidence threshold.
        track_buffer: Frames to keep lost tracks.
        match_thresh: IoU matching threshold.
        frame_rate: Video frame rate.

    Returns:
        A tracker satisfying the :class:`Tracker` protocol.
    """
    common = dict(track_thresh=track_thresh, track_buffer=track_buffer,
                  match_thresh=match_thresh, frame_rate=frame_rate)

    if name == "byte":
        from .byte_tracker import ByteTrackerAdapter
        return ByteTrackerAdapter(**common)
    elif name == "fast":
        from .fast_tracker import FastTrackerAdapter
        return FastTrackerAdapter(**common)
    else:
        raise ValueError(f"Unknown tracker: {name!r}. Choose from {TRACKER_CHOICES}")


def add_tracker_args(parser: argparse.ArgumentParser) -> None:
    """Register --tracker CLI argument on a parser."""
    group = parser.add_argument_group("tracker")
    group.add_argument(
        "--tracker", choices=TRACKER_CHOICES, default=DEFAULT_TRACKER,
        help=f"Tracker algorithm (default: {DEFAULT_TRACKER})")
