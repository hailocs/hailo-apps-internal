"""Unit tests for line crossing counter state machine.

Tests TrackState and LineCrossingCallbackData pure-Python logic without
running the full GStreamer pipeline.
"""

import sys
from unittest.mock import MagicMock

import pytest

for mod_name in [
    "hailo",
    "gi",
    "gi.repository",
    "gi.repository.Gst",
    "hailo_apps.python.core.gstreamer.gstreamer_app",
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()
sys.modules["gi"].require_version = lambda *a, **kw: None


class _StubAppCallbackBase:
    """Mimics the real app_callback_class enough for LineCrossingCallbackData."""

    def __init__(self):
        self.frame_count = 0
        self.use_frame = False
        self.window_title = ""

    def get_count(self):
        return self.frame_count

    def increment(self):
        self.frame_count += 1

    def set_frame(self, frame):
        self._frame = frame


sys.modules["hailo_apps.python.core.gstreamer.gstreamer_app"].app_callback_class = (
    _StubAppCallbackBase
)

from community.apps.pipeline_apps.line_crossing_counter.line_crossing_counter import (
    SMOOTHING_WINDOW,
    LineCrossingCallbackData,
    TrackState,
)


class TestTrackState:
    def test_initial_state(self):
        ts = TrackState()
        assert ts.entry_side is None
        assert ts.smoothed_x() is None
        assert ts.x_history.maxlen == SMOOTHING_WINDOW

    def test_smoothed_x_single_value(self):
        ts = TrackState()
        ts.x_history.append(0.5)
        assert ts.smoothed_x() == pytest.approx(0.5)

    def test_smoothed_x_average(self):
        ts = TrackState()
        for x in [0.1, 0.2, 0.3, 0.4, 0.5]:
            ts.x_history.append(x)
        assert ts.smoothed_x() == pytest.approx(0.3)

    def test_smoothed_x_evicts_old_values(self):
        ts = TrackState()
        # Fill window with low values, then add high values.
        # Only the most recent SMOOTHING_WINDOW values count.
        for x in [0.1] * SMOOTHING_WINDOW:
            ts.x_history.append(x)
        for x in [0.9] * SMOOTHING_WINDOW:
            ts.x_history.append(x)
        assert ts.smoothed_x() == pytest.approx(0.9)


class TestZoneBoundaries:
    def test_default_zone(self):
        cb = LineCrossingCallbackData(line_x=0.5, zone_width=0.1)
        assert cb.zone_left == pytest.approx(0.45)
        assert cb.zone_right == pytest.approx(0.55)

    def test_zone_left_clamped_to_zero(self):
        cb = LineCrossingCallbackData(line_x=0.0, zone_width=0.2)
        assert cb.zone_left == 0.0
        assert cb.zone_right == pytest.approx(0.1)

    def test_zone_right_clamped_to_one(self):
        cb = LineCrossingCallbackData(line_x=1.0, zone_width=0.2)
        assert cb.zone_left == pytest.approx(0.9)
        assert cb.zone_right == 1.0

    def test_wide_zone(self):
        cb = LineCrossingCallbackData(line_x=0.5, zone_width=1.0)
        assert cb.zone_left == 0.0
        assert cb.zone_right == 1.0

    def test_zero_width_zone(self):
        # Degenerate: a zone of width 0 collapses to the line itself
        cb = LineCrossingCallbackData(line_x=0.5, zone_width=0.0)
        assert cb.zone_left == 0.5
        assert cb.zone_right == 0.5


# ============================================================
# State-machine simulation: mirrors the logic in app_callback
# without needing GStreamer/Hailo. The behavior under test is:
#   1. Person enters zone -> record entry_side
#   2. Person exits opposite side -> count crossing, reset
#   3. Person exits same side -> no count, reset
#   4. Track removed when no longer current
# ============================================================


def _simulate_step(cb, track_id, x_center):
    """Re-implementation of the per-detection state-machine branch in
    line_crossing_counter.py:160-204. Kept in sync so tests cover the
    real logic. Returns nothing — mutates cb in place.
    """
    if track_id not in cb.tracks:
        cb.tracks[track_id] = TrackState()
    ts = cb.tracks[track_id]
    ts.x_history.append(x_center)
    smoothed = ts.smoothed_x()
    in_zone = cb.zone_left <= smoothed <= cb.zone_right

    if in_zone:
        if ts.entry_side is None:
            ts.entry_side = "left" if smoothed < cb.line_x else "right"
    else:
        if ts.entry_side is not None:
            exited_left = smoothed < cb.zone_left
            exited_right = smoothed > cb.zone_right
            if ts.entry_side == "left" and exited_right:
                cb.count_left_to_right += 1
            elif ts.entry_side == "right" and exited_left:
                cb.count_right_to_left += 1
            ts.entry_side = None
            ts.x_history.clear()


def _hold(cb, track_id, x, n):
    """Hold a track at x_center=x for n frames so smoothing settles."""
    for _ in range(n):
        _simulate_step(cb, track_id=track_id, x_center=x)


class TestStateMachine:
    """Smoothing window is 5 frames, so each x_center 'position' is held for
    at least SMOOTHING_WINDOW frames to let the smoothed average settle.
    """

    def test_full_left_to_right_crossing(self):
        cb = LineCrossingCallbackData(line_x=0.5, zone_width=0.1)
        _hold(cb, 1, 0.30, SMOOTHING_WINDOW)   # well left, outside zone
        _hold(cb, 1, 0.47, SMOOTHING_WINDOW)   # inside zone, left of center
        _hold(cb, 1, 0.53, SMOOTHING_WINDOW)   # inside zone, right of center
        _hold(cb, 1, 0.70, SMOOTHING_WINDOW)   # well right, outside zone
        assert cb.count_left_to_right == 1
        assert cb.count_right_to_left == 0

    def test_full_right_to_left_crossing(self):
        cb = LineCrossingCallbackData(line_x=0.5, zone_width=0.1)
        _hold(cb, 2, 0.70, SMOOTHING_WINDOW)
        _hold(cb, 2, 0.53, SMOOTHING_WINDOW)
        _hold(cb, 2, 0.47, SMOOTHING_WINDOW)
        _hold(cb, 2, 0.30, SMOOTHING_WINDOW)
        assert cb.count_left_to_right == 0
        assert cb.count_right_to_left == 1

    def test_turn_back_no_count(self):
        cb = LineCrossingCallbackData(line_x=0.5, zone_width=0.1)
        # Enter zone from left, then exit back left -> NO count.
        _hold(cb, 3, 0.30, SMOOTHING_WINDOW)
        _hold(cb, 3, 0.47, SMOOTHING_WINDOW)
        _hold(cb, 3, 0.30, SMOOTHING_WINDOW)
        assert cb.count_left_to_right == 0
        assert cb.count_right_to_left == 0

    def test_person_only_inside_zone_no_count(self):
        cb = LineCrossingCallbackData(line_x=0.5, zone_width=0.1)
        # Stand still inside the zone — never exits.
        _hold(cb, 4, 0.50, 20)
        assert cb.count_left_to_right == 0
        assert cb.tracks[4].entry_side in ("left", "right")  # initial side recorded

    def test_multiple_tracks_independent(self):
        cb = LineCrossingCallbackData(line_x=0.5, zone_width=0.1)
        # Walk both tracks across in parallel.
        for x_left, x_right in zip(
            [0.30, 0.47, 0.53, 0.70],   # track 5 going L -> R
            [0.70, 0.53, 0.47, 0.30],   # track 6 going R -> L
        ):
            for _ in range(SMOOTHING_WINDOW):
                _simulate_step(cb, track_id=5, x_center=x_left)
                _simulate_step(cb, track_id=6, x_center=x_right)
        assert cb.count_left_to_right == 1
        assert cb.count_right_to_left == 1

    def test_re_entry_after_crossing(self):
        cb = LineCrossingCallbackData(line_x=0.5, zone_width=0.1)
        _hold(cb, 7, 0.30, SMOOTHING_WINDOW)
        _hold(cb, 7, 0.47, SMOOTHING_WINDOW)
        _hold(cb, 7, 0.53, SMOOTHING_WINDOW)
        _hold(cb, 7, 0.70, SMOOTHING_WINDOW)
        assert cb.count_left_to_right == 1
        assert cb.tracks[7].entry_side is None
        # Walks back: should count as R->L
        _hold(cb, 7, 0.53, SMOOTHING_WINDOW)
        _hold(cb, 7, 0.47, SMOOTHING_WINDOW)
        _hold(cb, 7, 0.30, SMOOTHING_WINDOW)
        assert cb.count_right_to_left == 1
        assert cb.tracks[7].entry_side is None


class TestEdgeWidths:
    def test_wide_zone_counts_full_traversal(self):
        # A very wide zone (full frame) means the person is never "outside" —
        # so no crossing should be counted.
        cb = LineCrossingCallbackData(line_x=0.5, zone_width=1.0)
        _hold(cb, 1, 0.05, SMOOTHING_WINDOW)
        _hold(cb, 1, 0.50, SMOOTHING_WINDOW)
        _hold(cb, 1, 0.95, SMOOTHING_WINDOW)
        assert cb.count_left_to_right == 0
        assert cb.count_right_to_left == 0

    def test_narrow_zone_still_counts(self):
        cb = LineCrossingCallbackData(line_x=0.5, zone_width=0.05)
        # Walk through narrow [0.475, 0.525] zone.
        _hold(cb, 1, 0.30, SMOOTHING_WINDOW)
        _hold(cb, 1, 0.49, SMOOTHING_WINDOW)
        _hold(cb, 1, 0.51, SMOOTHING_WINDOW)
        _hold(cb, 1, 0.70, SMOOTHING_WINDOW)
        assert cb.count_left_to_right == 1
