"""Unit tests for the crowd counting line-crossing logic.

This app places a virtual HORIZONTAL line at ``line_y`` (normalized 0..1) and
counts tracked people crossing it:
  * top -> bottom (prev_y < line_y <= y_center)  => count_left_to_right ("L->R")
  * bottom -> top (prev_y > line_y >= y_center)  => count_right_to_left ("R->L")

Each track is counted at most once until its id is "aged out" after being
absent for ``forget_after_frames`` consecutive frames (the re-count guard fix).

These tests exercise the *real* ``app_callback`` from
``crowd_counting.py`` directly, driving it with fake hailo detection/track
objects. No GStreamer, no Hailo device, no inference, no OpenCV are involved:
``hailo``/``gi`` and the gstreamer_app base class are stubbed before import,
and ``use_frame`` is left False so the drawing branch (cv2) never runs.
"""

import sys
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.community


# ---------------------------------------------------------------------------
# Stub out device/GStreamer/inference modules BEFORE importing the app module.
# crowd_counting.py does `import hailo`, `import gi`, `import cv2`,
# `from gi.repository import Gst`, and imports the gstreamer_app base class.
# We replace them all with mocks so the module imports as pure Python.
# ---------------------------------------------------------------------------
for mod_name in [
    "hailo",
    "gi",
    "gi.repository",
    "gi.repository.Gst",
    "cv2",
    "hailo_apps.python.core.gstreamer.gstreamer_app",
    "hailo_apps.python.core.common.buffer_utils",
    # crowd_counting imports its sibling pipeline module, which pulls in the
    # GStreamerApp machinery. Stub it so import stays pure-Python.
    "community.apps.pipeline_apps.crowd_counting.crowd_counting_pipeline",
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()
sys.modules["gi"].require_version = lambda *a, **kw: None


class _StubAppCallbackBase:
    """Mimics the real app_callback_class enough for CrowdCountingCallbackData.

    The app's CrowdCountingCallbackData subclasses app_callback_class and relies
    on get_count()/use_frame/set_frame from the base.
    """

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

# HAILO_DETECTION / HAILO_UNIQUE_ID are used as opaque type tags by the
# callback; any distinct sentinel values work since our fake roi keys on them.
_HAILO_DETECTION = "HAILO_DETECTION"
_HAILO_UNIQUE_ID = "HAILO_UNIQUE_ID"
sys.modules["hailo"].HAILO_DETECTION = _HAILO_DETECTION
sys.modules["hailo"].HAILO_UNIQUE_ID = _HAILO_UNIQUE_ID

from community.apps.pipeline_apps.crowd_counting import (  # noqa: E402
    crowd_counting as cc,
)
from community.apps.pipeline_apps.crowd_counting.crowd_counting import (  # noqa: E402
    CrowdCountingCallbackData,
    app_callback,
)

# The app does `from ...buffer_utils import get_caps_from_pad`, binding the
# name into the crowd_counting module at import time. Patch it there (not on
# the source buffer_utils module) so the callback sees our stub. use_frame is
# left False, so get_numpy_from_buffer is never reached.
cc.get_caps_from_pad = lambda pad: (None, None, None)


# ---------------------------------------------------------------------------
# Fakes for the hailo detection / track objects the callback consumes.
# ---------------------------------------------------------------------------
class _FakeBBox:
    """Normalized bbox. Callback only reads ymin() and height()."""

    def __init__(self, ymin, height):
        self._ymin = ymin
        self._height = height

    def ymin(self):
        return self._ymin

    def height(self):
        return self._height


class _FakeUniqueId:
    def __init__(self, track_id):
        self._id = track_id

    def get_id(self):
        return self._id


class _FakeDetection:
    """Fake hailo detection.

    y_center is what the callback computes as ymin + height/2. We accept a
    desired y_center directly and synthesize a thin bbox around it so the
    callback's arithmetic reproduces it exactly.

    track_id semantics mirror the app:
      * track_id is None  -> no HAILO_UNIQUE_ID object attached
      * track_id == 0     -> app treats as untracked and skips
    """

    def __init__(self, y_center, track_id, label="person"):
        self._label = label
        # Thin box centered on y_center: ymin = y_center, height = 0.
        self._bbox = _FakeBBox(ymin=y_center, height=0.0)
        if track_id is None:
            self._tracks = []
        else:
            self._tracks = [_FakeUniqueId(track_id)]

    def get_label(self):
        return self._label

    def get_bbox(self):
        return self._bbox

    def get_objects_typed(self, type_tag):
        assert type_tag == _HAILO_UNIQUE_ID
        return self._tracks


class _FakeRoi:
    def __init__(self, detections):
        self._detections = detections

    def get_objects_typed(self, type_tag):
        assert type_tag == _HAILO_DETECTION
        return self._detections


class _FakeElement:
    """Stands in for the GStreamer element passed to the callback."""

    def get_static_pad(self, name):
        return MagicMock()


def _make_frame(detections):
    """Wire a fake buffer so hailo.get_roi_from_buffer returns our roi.

    The callback calls hailo.get_roi_from_buffer(buffer) (attribute lookup at
    call time), so we point it at a _FakeRoi carrying the given detections.
    get_caps_from_pad is patched once at import (see top) to return Nones, so
    the frame-drawing branch is skipped (also gated on use_frame=False).
    """
    sys.modules["hailo"].get_roi_from_buffer = lambda buf: _FakeRoi(detections)
    return object()  # opaque, non-None buffer


def _run_frame(user_data, detections):
    """Invoke the real app_callback for one frame with the given detections.

    Increments the frame counter the way the real pipeline driver would, so
    the periodic-logging branch (frame_idx % 30) is exercised across frames.
    """
    element = _FakeElement()
    buffer = _make_frame(detections)
    app_callback(element, buffer, user_data)
    user_data.increment()


def _det(y_center, track_id=1, label="person"):
    return _FakeDetection(y_center=y_center, track_id=track_id, label=label)


# ===========================================================================
# Construction / config
# ===========================================================================
class TestConstruction:
    def test_defaults(self):
        cb = CrowdCountingCallbackData()
        assert cb.line_y == 0.5
        assert cb.count_left_to_right == 0
        assert cb.count_right_to_left == 0
        assert cb.counted_ids == set()
        assert cb.prev_positions == {}
        assert cb.frames_since_seen == {}
        assert cb.forget_after_frames == 90

    def test_custom_line_y(self):
        cb = CrowdCountingCallbackData(line_y=0.3)
        assert cb.line_y == 0.3


# ===========================================================================
# Basic crossing detection (the core convention)
# ===========================================================================
class TestCrossingDetection:
    def test_top_to_bottom_counts_l_to_r_once(self):
        cb = CrowdCountingCallbackData(line_y=0.5)
        _run_frame(cb, [_det(0.30, track_id=1)])  # above line
        _run_frame(cb, [_det(0.70, track_id=1)])  # below line -> crossed down
        assert cb.count_left_to_right == 1
        assert cb.count_right_to_left == 0
        assert 1 in cb.counted_ids

    def test_bottom_to_top_counts_r_to_l_once(self):
        cb = CrowdCountingCallbackData(line_y=0.5)
        _run_frame(cb, [_det(0.70, track_id=1)])  # below line
        _run_frame(cb, [_det(0.30, track_id=1)])  # above line -> crossed up
        assert cb.count_right_to_left == 1
        assert cb.count_left_to_right == 0
        assert 1 in cb.counted_ids

    def test_no_crossing_when_staying_above(self):
        cb = CrowdCountingCallbackData(line_y=0.5)
        _run_frame(cb, [_det(0.10, track_id=1)])
        _run_frame(cb, [_det(0.20, track_id=1)])
        _run_frame(cb, [_det(0.40, track_id=1)])
        assert cb.count_left_to_right == 0
        assert cb.count_right_to_left == 0
        assert cb.counted_ids == set()

    def test_no_crossing_when_staying_below(self):
        cb = CrowdCountingCallbackData(line_y=0.5)
        _run_frame(cb, [_det(0.90, track_id=1)])
        _run_frame(cb, [_det(0.80, track_id=1)])
        _run_frame(cb, [_det(0.60, track_id=1)])
        assert cb.count_left_to_right == 0
        assert cb.count_right_to_left == 0

    def test_first_frame_alone_never_counts(self):
        # No prev_positions yet -> nothing to compare against.
        cb = CrowdCountingCallbackData(line_y=0.5)
        _run_frame(cb, [_det(0.70, track_id=1)])
        assert cb.count_left_to_right == 0
        assert cb.count_right_to_left == 0

    def test_crossing_counted_only_once_while_present(self):
        # After being counted, staying on the far side must not re-count.
        cb = CrowdCountingCallbackData(line_y=0.5)
        _run_frame(cb, [_det(0.30, track_id=1)])
        _run_frame(cb, [_det(0.70, track_id=1)])  # count
        _run_frame(cb, [_det(0.80, track_id=1)])
        _run_frame(cb, [_det(0.90, track_id=1)])
        assert cb.count_left_to_right == 1

    def test_back_and_forth_only_first_crossing_counts(self):
        # Counted on first crossing; the return crossing is suppressed because
        # the id is in counted_ids (and never aged out while still present).
        cb = CrowdCountingCallbackData(line_y=0.5)
        _run_frame(cb, [_det(0.30, track_id=1)])
        _run_frame(cb, [_det(0.70, track_id=1)])  # L->R counted
        _run_frame(cb, [_det(0.30, track_id=1)])  # would be R->L but suppressed
        assert cb.count_left_to_right == 1
        assert cb.count_right_to_left == 0


# ===========================================================================
# Boundary / exact-on-line behavior
# ===========================================================================
class TestLineBoundary:
    def test_landing_exactly_on_line_from_above_counts_down(self):
        # prev_y < line_y <= y_center, with y_center == line_y.
        cb = CrowdCountingCallbackData(line_y=0.5)
        _run_frame(cb, [_det(0.30, track_id=1)])
        _run_frame(cb, [_det(0.50, track_id=1)])  # exactly on line from above
        assert cb.count_left_to_right == 1
        assert cb.count_right_to_left == 0

    def test_landing_exactly_on_line_from_below_counts_up(self):
        # prev_y > line_y >= y_center, with y_center == line_y.
        cb = CrowdCountingCallbackData(line_y=0.5)
        _run_frame(cb, [_det(0.70, track_id=1)])
        _run_frame(cb, [_det(0.50, track_id=1)])  # exactly on line from below
        assert cb.count_right_to_left == 1
        assert cb.count_left_to_right == 0

    def test_starting_exactly_on_line_then_moving_down_no_count(self):
        # prev_y == line_y is NOT strictly less than line_y, so moving down
        # does not satisfy prev_y < line_y <= y_center.
        cb = CrowdCountingCallbackData(line_y=0.5)
        _run_frame(cb, [_det(0.50, track_id=1)])  # exactly on line
        _run_frame(cb, [_det(0.70, track_id=1)])  # moves below
        assert cb.count_left_to_right == 0
        assert cb.count_right_to_left == 0

    def test_starting_exactly_on_line_then_moving_up_no_count(self):
        cb = CrowdCountingCallbackData(line_y=0.5)
        _run_frame(cb, [_det(0.50, track_id=1)])  # exactly on line
        _run_frame(cb, [_det(0.30, track_id=1)])  # moves above
        assert cb.count_left_to_right == 0
        assert cb.count_right_to_left == 0

    def test_staying_exactly_on_line_no_count(self):
        cb = CrowdCountingCallbackData(line_y=0.5)
        _run_frame(cb, [_det(0.50, track_id=1)])
        _run_frame(cb, [_det(0.50, track_id=1)])
        assert cb.count_left_to_right == 0
        assert cb.count_right_to_left == 0


# ===========================================================================
# line_y configuration
# ===========================================================================
class TestLineYConfig:
    def test_custom_line_y_high_position(self):
        # Line near the top (0.2). A person above 0.2 moving below it counts.
        cb = CrowdCountingCallbackData(line_y=0.2)
        _run_frame(cb, [_det(0.10, track_id=1)])
        _run_frame(cb, [_det(0.30, track_id=1)])
        assert cb.count_left_to_right == 1

    def test_motion_above_custom_line_does_not_count(self):
        # With line at 0.2, movement entirely below the line never crosses.
        cb = CrowdCountingCallbackData(line_y=0.2)
        _run_frame(cb, [_det(0.40, track_id=1)])
        _run_frame(cb, [_det(0.80, track_id=1)])
        assert cb.count_left_to_right == 0
        assert cb.count_right_to_left == 0

    def test_line_at_extreme_low(self):
        cb = CrowdCountingCallbackData(line_y=0.9)
        _run_frame(cb, [_det(0.80, track_id=1)])
        _run_frame(cb, [_det(0.95, track_id=1)])  # crosses 0.9 downward
        assert cb.count_left_to_right == 1


# ===========================================================================
# Re-count guard / forget window (the documented fix)
# ===========================================================================
class TestRecountGuard:
    def test_brief_occlusion_does_not_recount(self):
        # Cross once, disappear for a few frames (< forget window), reappear
        # with SAME id and cross again -> must NOT recount.
        cb = CrowdCountingCallbackData(line_y=0.5)
        _run_frame(cb, [_det(0.30, track_id=7)])
        _run_frame(cb, [_det(0.70, track_id=7)])  # counted L->R
        assert cb.count_left_to_right == 1

        # Occluded for 10 frames (well under forget_after_frames=90).
        for _ in range(10):
            _run_frame(cb, [])
        assert 7 in cb.counted_ids  # still remembered

        # Reappears above and crosses down again with same id.
        _run_frame(cb, [_det(0.30, track_id=7)])
        _run_frame(cb, [_det(0.70, track_id=7)])
        assert cb.count_left_to_right == 1  # NOT incremented again

    def test_aged_out_after_forget_window_can_recount(self):
        cb = CrowdCountingCallbackData(line_y=0.5)
        _run_frame(cb, [_det(0.30, track_id=7)])
        _run_frame(cb, [_det(0.70, track_id=7)])  # counted L->R
        assert cb.count_left_to_right == 1

        # Absent for the full forget window -> id is released.
        for _ in range(cb.forget_after_frames):
            _run_frame(cb, [])
        assert 7 not in cb.counted_ids
        assert 7 not in cb.frames_since_seen

        # Same id reappears and crosses -> counts again.
        _run_frame(cb, [_det(0.30, track_id=7)])
        _run_frame(cb, [_det(0.70, track_id=7)])
        assert cb.count_left_to_right == 2

    def test_forget_counter_resets_when_seen_again(self):
        # Disappear for < window, reappear (resetting the counter), disappear
        # again for < window. Total absence > window but never CONSECUTIVE, so
        # the id is never aged out.
        cb = CrowdCountingCallbackData(line_y=0.5)
        _run_frame(cb, [_det(0.30, track_id=7)])
        _run_frame(cb, [_det(0.70, track_id=7)])  # counted
        assert cb.count_left_to_right == 1

        half = cb.forget_after_frames - 5
        for _ in range(half):
            _run_frame(cb, [])
        assert 7 in cb.counted_ids
        # Seen again (below the line, no new crossing) -> resets counter.
        _run_frame(cb, [_det(0.70, track_id=7)])
        assert cb.frames_since_seen[7] == 0
        for _ in range(half):
            _run_frame(cb, [])
        assert 7 in cb.counted_ids  # never aged out

    def test_forget_boundary_exact(self):
        # Aged out exactly when missing reaches forget_after_frames.
        cb = CrowdCountingCallbackData(line_y=0.5)
        cb.forget_after_frames = 3
        _run_frame(cb, [_det(0.30, track_id=7)])
        _run_frame(cb, [_det(0.70, track_id=7)])  # counted; seen this frame
        assert cb.count_left_to_right == 1

        _run_frame(cb, [])  # missing == 1
        assert 7 in cb.counted_ids
        _run_frame(cb, [])  # missing == 2
        assert 7 in cb.counted_ids
        _run_frame(cb, [])  # missing == 3 == forget_after_frames -> aged out
        assert 7 not in cb.counted_ids


# ===========================================================================
# track_id handling: None and 0 are not tracked
# ===========================================================================
class TestTrackIdHandling:
    def test_track_id_zero_is_ignored(self):
        # track_id == 0 means "untracked" and is skipped entirely.
        cb = CrowdCountingCallbackData(line_y=0.5)
        _run_frame(cb, [_det(0.30, track_id=0)])
        _run_frame(cb, [_det(0.70, track_id=0)])
        assert cb.count_left_to_right == 0
        assert cb.count_right_to_left == 0
        assert cb.prev_positions == {}

    def test_no_unique_id_object_is_untracked(self):
        # No HAILO_UNIQUE_ID attached -> track_id stays 0 -> skipped.
        cb = CrowdCountingCallbackData(line_y=0.5)
        _run_frame(cb, [_det(0.30, track_id=None)])
        _run_frame(cb, [_det(0.70, track_id=None)])
        assert cb.count_left_to_right == 0
        assert cb.prev_positions == {}

    def test_multiple_unique_ids_is_untracked(self):
        # The app only treats len(track) == 1 as tracked; anything else -> 0.
        cb = CrowdCountingCallbackData(line_y=0.5)
        det1 = _FakeDetection(y_center=0.30, track_id=1)
        det1._tracks = [_FakeUniqueId(1), _FakeUniqueId(2)]  # two ids
        det2 = _FakeDetection(y_center=0.70, track_id=1)
        det2._tracks = [_FakeUniqueId(1), _FakeUniqueId(2)]
        _run_frame(cb, [det1])
        _run_frame(cb, [det2])
        assert cb.count_left_to_right == 0
        assert cb.prev_positions == {}


# ===========================================================================
# Non-person and empty-frame handling
# ===========================================================================
class TestLabelAndEmptyFrames:
    def test_non_person_detections_ignored(self):
        cb = CrowdCountingCallbackData(line_y=0.5)
        _run_frame(cb, [_det(0.30, track_id=1, label="car")])
        _run_frame(cb, [_det(0.70, track_id=1, label="car")])
        assert cb.count_left_to_right == 0
        assert cb.prev_positions == {}

    def test_empty_frame_no_detections(self):
        cb = CrowdCountingCallbackData(line_y=0.5)
        _run_frame(cb, [])
        _run_frame(cb, [])
        assert cb.count_left_to_right == 0
        assert cb.count_right_to_left == 0
        assert cb.prev_positions == {}

    def test_none_buffer_is_safe(self):
        # The callback returns early on a None buffer without touching state.
        cb = CrowdCountingCallbackData(line_y=0.5)
        element = _FakeElement()
        app_callback(element, None, cb)
        assert cb.count_left_to_right == 0
        assert cb.count_right_to_left == 0
        assert cb.prev_positions == {}

    def test_person_disappears_then_a_new_track_appears(self):
        # Person A crosses, leaves; later a DIFFERENT id appears and crosses.
        # Both should count (distinct ids).
        cb = CrowdCountingCallbackData(line_y=0.5)
        _run_frame(cb, [_det(0.30, track_id=1)])
        _run_frame(cb, [_det(0.70, track_id=1)])  # A counted
        _run_frame(cb, [_det(0.30, track_id=2)])
        _run_frame(cb, [_det(0.70, track_id=2)])  # B counted
        assert cb.count_left_to_right == 2


# ===========================================================================
# Multiple simultaneous tracks
# ===========================================================================
class TestMultipleTracks:
    def test_two_tracks_cross_opposite_directions(self):
        cb = CrowdCountingCallbackData(line_y=0.5)
        # Frame 1: track 1 above, track 2 below.
        _run_frame(cb, [_det(0.30, track_id=1), _det(0.70, track_id=2)])
        # Frame 2: track 1 below (down), track 2 above (up).
        _run_frame(cb, [_det(0.70, track_id=1), _det(0.30, track_id=2)])
        assert cb.count_left_to_right == 1
        assert cb.count_right_to_left == 1
        assert {1, 2} <= cb.counted_ids

    def test_many_tracks_same_direction(self):
        cb = CrowdCountingCallbackData(line_y=0.5)
        ids = [10, 11, 12, 13, 14]
        _run_frame(cb, [_det(0.30, track_id=i) for i in ids])
        _run_frame(cb, [_det(0.70, track_id=i) for i in ids])
        assert cb.count_left_to_right == len(ids)
        assert cb.count_right_to_left == 0
        assert set(ids) <= cb.counted_ids

    def test_tracks_are_independent(self):
        # One track crosses, another just loiters above the line.
        cb = CrowdCountingCallbackData(line_y=0.5)
        _run_frame(cb, [_det(0.30, track_id=1), _det(0.10, track_id=2)])
        _run_frame(cb, [_det(0.70, track_id=1), _det(0.15, track_id=2)])
        assert cb.count_left_to_right == 1  # only track 1
        assert 1 in cb.counted_ids
        assert 2 not in cb.counted_ids

    def test_independent_aging_per_track(self):
        # Two tracks counted; one keeps being seen, the other ages out.
        cb = CrowdCountingCallbackData(line_y=0.5)
        cb.forget_after_frames = 4
        _run_frame(cb, [_det(0.30, track_id=1), _det(0.30, track_id=2)])
        _run_frame(cb, [_det(0.70, track_id=1), _det(0.70, track_id=2)])
        assert cb.count_left_to_right == 2

        # Track 1 stays visible (below line), track 2 vanishes.
        for _ in range(cb.forget_after_frames):
            _run_frame(cb, [_det(0.80, track_id=1)])
        assert 1 in cb.counted_ids       # kept alive
        assert 2 not in cb.counted_ids   # aged out
