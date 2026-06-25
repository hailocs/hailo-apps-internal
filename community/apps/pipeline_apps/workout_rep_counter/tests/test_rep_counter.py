"""Unit tests for the Workout Rep Counter joint-angle math and the per-track
rep-counting state machine.

Pure Python only: no Hailo device, no GStreamer run, no model inference, no
network. The real ``app_callback`` from ``workout_rep_counter.py`` is exercised
directly by stubbing the ``hailo`` / ``gi`` / pipeline / buffer-util modules and
feeding it small fake detection objects. This means the tests cover the actual
shipped state-machine code, not a re-implementation.
"""

import sys
import types
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.community


# ---------------------------------------------------------------------------
# Module stubbing — make ``workout_rep_counter`` importable without a device.
#
# The app does, at module scope:
#   import gi; gi.require_version("Gst", "1.0"); from gi.repository import Gst
#   import hailo
#   from ...buffer_utils import get_caps_from_pad, get_numpy_from_buffer
#   from ...workout_rep_counter_pipeline import GStreamerWorkoutRepCounterApp
#   from ...gstreamer_app import app_callback_class
# cv2 is a genuine dependency and is left real.
# ---------------------------------------------------------------------------

# A real, lightweight ``hailo`` stub. The app reads these symbols as plain
# constants for ``get_objects_typed`` and ``get_roi_from_buffer``.
_hailo = types.ModuleType("hailo")
_hailo.HAILO_DETECTION = "HAILO_DETECTION"
_hailo.HAILO_UNIQUE_ID = "HAILO_UNIQUE_ID"
_hailo.HAILO_LANDMARKS = "HAILO_LANDMARKS"
# get_roi_from_buffer is monkeypatched per-test; default raises if used blindly.
_hailo.get_roi_from_buffer = lambda buffer: buffer
sys.modules.setdefault("hailo", _hailo)

for mod_name in (
    "gi",
    "gi.repository",
    "gi.repository.Gst",
    "hailo_apps.python.core.common.buffer_utils",
    "community.apps.pipeline_apps.workout_rep_counter.workout_rep_counter_pipeline",
    "hailo_apps.python.core.gstreamer.gstreamer_app",
):
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()
sys.modules["gi"].require_version = lambda *a, **kw: None


class _StubAppCallbackBase:
    """Mimics the real app_callback_class enough for user_app_callback_class."""

    def __init__(self):
        self.frame_count = 0
        self.use_frame = False
        self._frame = None

    def get_count(self):
        return self.frame_count

    def increment(self):
        self.frame_count += 1

    def set_frame(self, frame):
        self._frame = frame


sys.modules["hailo_apps.python.core.gstreamer.gstreamer_app"].app_callback_class = (
    _StubAppCallbackBase
)
# buffer_utils symbols must be plain callables (the app imports them by name).
# Square frame so normalized->pixel scaling is uniform on x and y; this keeps
# the test geometry's joint angles undistorted (a non-square frame would scale
# x and y differently and skew the computed angle).
sys.modules["hailo_apps.python.core.common.buffer_utils"].get_caps_from_pad = (
    lambda pad: ("RGB", 640, 640)
)
sys.modules["hailo_apps.python.core.common.buffer_utils"].get_numpy_from_buffer = (
    lambda *a, **kw: None
)


from community.apps.pipeline_apps.workout_rep_counter.workout_rep_counter import (  # noqa: E402
    EXERCISES,
    KEYPOINTS,
    RepState,
    app_callback,
    calculate_angle,
    get_keypoint_pixel_coords,
    user_app_callback_class,
)


# ===========================================================================
# Fakes for driving the real app_callback
# ===========================================================================

class FakeBBox:
    """Normalized bbox; identity transform (xmin=ymin=0, w=h=1) keeps the
    keypoint pixel mapping equal to point * frame_size for easy reasoning."""

    def __init__(self, xmin=0.0, ymin=0.0, width=1.0, height=1.0):
        self._xmin, self._ymin, self._w, self._h = xmin, ymin, width, height

    def xmin(self):
        return self._xmin

    def ymin(self):
        return self._ymin

    def width(self):
        return self._w

    def height(self):
        return self._h


class FakePoint:
    """A pose landmark point, normalized within the bbox."""

    def __init__(self, x, y):
        self._x, self._y = x, y

    def x(self):
        return self._x

    def y(self):
        return self._y


class FakeLandmarks:
    def __init__(self, points):
        self._points = points

    def get_points(self):
        return self._points


class FakeUniqueId:
    def __init__(self, tid):
        self._id = tid

    def get_id(self):
        return self._id


class FakeDetection:
    """Replicates the subset of the Hailo detection API the callback uses."""

    def __init__(self, label="person", track_id=1, points=None,
                 bbox=None, confidence=0.9, has_landmarks=True):
        self._label = label
        self._confidence = confidence
        self._bbox = bbox if bbox is not None else FakeBBox()
        self._track = [FakeUniqueId(track_id)] if track_id is not None else []
        if has_landmarks:
            self._landmarks = [FakeLandmarks(points if points is not None else [])]
        else:
            self._landmarks = []

    def get_label(self):
        return self._label

    def get_confidence(self):
        return self._confidence

    def get_bbox(self):
        return self._bbox

    def get_objects_typed(self, kind):
        if kind == _hailo.HAILO_UNIQUE_ID:
            return self._track
        if kind == _hailo.HAILO_LANDMARKS:
            return self._landmarks
        return []


class FakeRoi:
    def __init__(self, detections):
        self._detections = detections

    def get_objects_typed(self, kind):
        if kind == _hailo.HAILO_DETECTION:
            return self._detections
        return []


class FakePad:
    def get_static_pad(self, name):
        return object()


_ELEMENT = FakePad()


def _angle_points_for(angle_deg):
    """Return 17 COCO landmark points (normalized, identity bbox over a
    640x480 frame) such that the triplet used by squat/pushup/bicep_curl forms
    exactly ``angle_deg`` at the vertex.

    All three exercises use a left-side triplet:
      squat:      (left_hip,      left_knee,  left_ankle)
      pushup:     (left_shoulder, left_elbow, left_wrist)
      bicep_curl: (left_shoulder, left_elbow, left_wrist)

    We place a generic vertex and two arms of unit-ish length at the requested
    angle, and write the SAME geometry into every keypoint slot so whatever
    triplet an exercise selects yields ``angle_deg``.
    """
    import math
    # Vertex at frame center (in normalized coords, since identity bbox over a
    # 640x480 frame: pixel = normalized * size). Use normalized values that
    # land comfortably inside the frame.
    vx, vy = 0.5, 0.5
    arm = 0.2
    # First arm points straight up (toward decreasing y in pixel space).
    a1 = (vx, vy - arm)
    theta = math.radians(angle_deg)
    # Second arm rotated by angle_deg from the first (in the x-y plane).
    a2 = (vx + arm * math.sin(theta), vy - arm * math.cos(theta))

    pts = [FakePoint(vx, vy) for _ in range(len(KEYPOINTS))]
    # The triplet is (A, vertex B, C). Set A on arm1, B at vertex, C on arm2.
    triplets = set()
    for cfg in EXERCISES.values():
        triplets.add(cfg["joint_triplet"])
    for (ja, jb, jc) in triplets:
        pts[KEYPOINTS[ja]] = FakePoint(*a1)
        pts[KEYPOINTS[jb]] = FakePoint(vx, vy)
        pts[KEYPOINTS[jc]] = FakePoint(*a2)
    return pts


def _feed(user_data, angle_deg, track_id=1, label="person",
          has_landmarks=True, points=None, track_id_present=True):
    """Run one frame through the real app_callback with a single detection at
    the requested joint angle."""
    if points is None and has_landmarks:
        points = _angle_points_for(angle_deg)
    det = FakeDetection(
        label=label,
        track_id=track_id if track_id_present else None,
        points=points,
        has_landmarks=has_landmarks,
    )
    _run_frame(user_data, [det])


def _run_frame(user_data, detections):
    """Drive app_callback for one frame given a list of fake detections."""
    roi = FakeRoi(detections)
    buffer = object()
    _hailo.get_roi_from_buffer = lambda b, _roi=roi: _roi
    user_data.increment()
    app_callback(_ELEMENT, buffer, user_data)


def _make_user_data(exercise="squat"):
    ud = user_app_callback_class()
    ud.exercise = exercise
    return ud


def _assert_feed_angle(exercise, angle_deg):
    """Sanity check that the geometry generator actually produces the angle the
    callback computes for the given exercise's triplet."""
    ud = _make_user_data(exercise)
    _feed(ud, angle_deg)
    state = ud.track_states[1]
    return state.current_angle


# ===========================================================================
# calculate_angle
# ===========================================================================

class TestCalculateAngle:
    def test_straight_line_is_180(self):
        # p1 - p2 - p3 collinear, p2 in the middle -> 180 degrees.
        assert calculate_angle((0, 0), (1, 0), (2, 0)) == pytest.approx(180.0)

    def test_right_angle_is_90(self):
        assert calculate_angle((1, 0), (0, 0), (0, 1)) == pytest.approx(90.0)

    def test_acute_45(self):
        assert calculate_angle((1, 0), (0, 0), (1, 1)) == pytest.approx(45.0)

    def test_zero_angle_overlapping_arms(self):
        # Both arms point the same direction -> 0 degrees.
        assert calculate_angle((1, 0), (0, 0), (2, 0)) == pytest.approx(0.0)

    def test_coincident_p1_returns_zero(self):
        # mag1 == 0 -> degenerate -> 0.0 per the implementation.
        assert calculate_angle((0, 0), (0, 0), (1, 1)) == 0.0

    def test_coincident_p3_returns_zero(self):
        assert calculate_angle((1, 1), (0, 0), (0, 0)) == 0.0

    def test_all_coincident_returns_zero(self):
        assert calculate_angle((5, 5), (5, 5), (5, 5)) == 0.0

    def test_obtuse_135(self):
        assert calculate_angle((1, 0), (0, 0), (-1, 1)) == pytest.approx(135.0)

    def test_range_is_clamped_0_to_180(self):
        # Floating point can push cos slightly out of [-1, 1]; result must stay
        # in [0, 180] and never raise.
        a = calculate_angle((1.0, 0.0), (0.0, 0.0), (1.0000000001, 0.0))
        assert 0.0 <= a <= 180.0


# ===========================================================================
# RepState
# ===========================================================================

class TestRepState:
    def test_initial_state(self):
        s = RepState()
        assert s.phase == "up"
        assert s.rep_count == 0
        assert s.current_angle == 0.0


# ===========================================================================
# get_keypoint_pixel_coords
# ===========================================================================

class TestKeypointPixelCoords:
    def test_identity_bbox_maps_point_to_pixels(self):
        pts = [FakePoint(0.5, 0.25)] * len(KEYPOINTS)
        bbox = FakeBBox(0.0, 0.0, 1.0, 1.0)
        xy = get_keypoint_pixel_coords(pts, "nose", bbox, 640, 480)
        assert xy == pytest.approx((320.0, 120.0))

    def test_offset_bbox_applies_transform(self):
        # point inside a bbox at (0.2, 0.1) of size 0.5x0.5 over 100x100 frame
        pts = [FakePoint(0.5, 0.5)] * len(KEYPOINTS)
        bbox = FakeBBox(0.2, 0.1, 0.5, 0.5)
        xy = get_keypoint_pixel_coords(pts, "nose", bbox, 100, 100)
        # x = (0.5*0.5 + 0.2)*100 = 45 ; y = (0.5*0.5 + 0.1)*100 = 35
        assert xy == pytest.approx((45.0, 35.0))

    def test_unknown_keypoint_returns_none(self):
        pts = [FakePoint(0.0, 0.0)] * len(KEYPOINTS)
        assert get_keypoint_pixel_coords(pts, "tail", FakeBBox(), 10, 10) is None

    def test_index_out_of_range_returns_none(self):
        # Fewer points than the requested keypoint index -> None.
        pts = [FakePoint(0.0, 0.0)]  # only index 0 available
        assert get_keypoint_pixel_coords(pts, "left_ankle", FakeBBox(), 10, 10) is None


# ===========================================================================
# Geometry generator sanity (ensures the state-machine tests feed real angles)
# ===========================================================================

class TestGeometryGenerator:
    @pytest.mark.parametrize("exercise", list(EXERCISES.keys()))
    @pytest.mark.parametrize("angle", [40, 90, 160, 180])
    def test_generator_produces_requested_angle(self, exercise, angle):
        got = _assert_feed_angle(exercise, angle)
        assert got == pytest.approx(angle, abs=0.5)


# ===========================================================================
# Rep-counting state machine — per exercise
# ===========================================================================

class TestSquatStateMachine:
    """squat: down_angle=90, up_angle=160, down_is_smaller=True
    (down phase = small knee angle, up phase = large knee angle)."""

    def test_full_down_up_counts_one(self):
        ud = _make_user_data("squat")
        _feed(ud, 170)   # standing (up), above down_angle -> stays up
        _feed(ud, 85)    # squat down -> phase down, no count yet
        _feed(ud, 165)   # stand back up -> count 1
        assert ud.track_states[1].rep_count == 1
        assert ud.track_states[1].phase == "up"

    def test_at_rest_hold_counts_zero(self):
        ud = _make_user_data("squat")
        for _ in range(10):
            _feed(ud, 170)  # just standing
        assert ud.track_states[1].rep_count == 0
        assert ud.track_states[1].phase == "up"

    def test_three_full_cycles(self):
        ud = _make_user_data("squat")
        for _ in range(3):
            _feed(ud, 85)
            _feed(ud, 165)
        assert ud.track_states[1].rep_count == 3

    def test_down_hold_does_not_count(self):
        ud = _make_user_data("squat")
        _feed(ud, 80)
        for _ in range(5):
            _feed(ud, 70)  # held at bottom
        assert ud.track_states[1].rep_count == 0
        assert ud.track_states[1].phase == "down"


class TestPushupStateMachine:
    """pushup: down_angle=90, up_angle=160, down_is_smaller=True."""

    def test_full_down_up_counts_one(self):
        ud = _make_user_data("pushup")
        _feed(ud, 170)
        _feed(ud, 80)
        _feed(ud, 170)
        assert ud.track_states[1].rep_count == 1

    def test_partial_rep_no_count(self):
        ud = _make_user_data("pushup")
        # Go down but never come back up to up_angle.
        _feed(ud, 80)
        _feed(ud, 120)   # 120 < 160 -> still down, no count
        assert ud.track_states[1].rep_count == 0
        assert ud.track_states[1].phase == "down"


class TestBicepCurlStateMachine:
    """bicep_curl: down_angle=160, up_angle=40, down_is_smaller=False.
    This is the inverted-angle regression case:
      arm extended (large angle ~160) = 'down' phase,
      arm curled  (small angle ~40)  = 'up' phase, increments on the way up.
    """

    def test_extended_curl_extended_counts_one(self):
        ud = _make_user_data("bicep_curl")
        _feed(ud, 160)   # arm extended -> phase down
        _feed(ud, 40)    # curled -> phase up, count 1
        _feed(ud, 160)   # extended again -> phase down, no extra count
        assert ud.track_states[1].rep_count == 1
        assert ud.track_states[1].phase == "down"

    def test_held_extended_counts_zero(self):
        ud = _make_user_data("bicep_curl")
        for _ in range(8):
            _feed(ud, 160)  # arm just held extended at rest
        assert ud.track_states[1].rep_count == 0
        assert ud.track_states[1].phase == "down"

    def test_held_curled_counts_zero_extra(self):
        ud = _make_user_data("bicep_curl")
        _feed(ud, 160)
        _feed(ud, 40)            # one rep
        for _ in range(5):
            _feed(ud, 35)        # held curled at top
        assert ud.track_states[1].rep_count == 1

    def test_multiple_curls(self):
        ud = _make_user_data("bicep_curl")
        for _ in range(4):
            _feed(ud, 160)
            _feed(ud, 40)
        assert ud.track_states[1].rep_count == 4


# ===========================================================================
# Threshold edge cases
# ===========================================================================

class TestThresholdEdges:
    def test_squat_exactly_at_down_angle(self):
        # angle == down_angle (90) should trigger down (uses <=).
        ud = _make_user_data("squat")
        _feed(ud, 90)
        assert ud.track_states[1].phase == "down"

    def test_squat_exactly_at_up_angle_counts(self):
        ud = _make_user_data("squat")
        _feed(ud, 90)    # down
        _feed(ud, 160)   # exactly up_angle -> counts (uses >=)
        assert ud.track_states[1].rep_count == 1
        assert ud.track_states[1].phase == "up"

    def test_bicep_exactly_at_down_angle(self):
        # bicep down_angle=160; angle >= 160 triggers down.
        ud = _make_user_data("bicep_curl")
        _feed(ud, 160)
        assert ud.track_states[1].phase == "down"

    def test_bicep_exactly_at_up_angle_counts(self):
        ud = _make_user_data("bicep_curl")
        _feed(ud, 160)   # down
        _feed(ud, 40)    # exactly up_angle (<=) -> count
        assert ud.track_states[1].rep_count == 1

    def test_jitter_around_threshold_no_double_count_squat(self):
        # Sit in the down phase and jitter just under up_angle; must not count.
        ud = _make_user_data("squat")
        _feed(ud, 85)          # down
        for a in (158, 159, 158, 159, 157):  # all < 160 -> still down
            _feed(ud, a)
        assert ud.track_states[1].rep_count == 0
        # One clean rise across the threshold -> exactly one rep.
        _feed(ud, 165)
        assert ud.track_states[1].rep_count == 1
        # Jitter just above threshold while in up phase -> no extra reps.
        for a in (161, 162, 165, 170):
            _feed(ud, a)
        assert ud.track_states[1].rep_count == 1

    def test_jitter_around_threshold_no_double_count_bicep(self):
        ud = _make_user_data("bicep_curl")
        _feed(ud, 160)         # down
        for a in (42, 41, 45, 43):  # all > up_angle(40) -> still down
            _feed(ud, a)
        assert ud.track_states[1].rep_count == 0
        _feed(ud, 38)          # cross below 40 -> one rep, phase up
        assert ud.track_states[1].rep_count == 1
        for a in (35, 30, 38, 40):  # jitter at top, phase already up
            _feed(ud, a)
        assert ud.track_states[1].rep_count == 1


# ===========================================================================
# Missing / malformed inputs
# ===========================================================================

class TestMissingInputs:
    def test_non_person_label_ignored(self):
        ud = _make_user_data("squat")
        _feed(ud, 85, label="cat")
        _feed(ud, 165, label="cat")
        assert ud.track_states == {}  # never created any state

    def test_no_landmarks_creates_state_but_no_count(self):
        ud = _make_user_data("squat")
        _feed(ud, 85, has_landmarks=False)
        # State is created (track seen) but no angle processed -> stays up/0.
        assert 1 in ud.track_states
        assert ud.track_states[1].rep_count == 0
        assert ud.track_states[1].phase == "up"

    def test_untracked_detection_skipped(self):
        # Detection with no unique-id object: must not create state nor merge.
        ud = _make_user_data("squat")
        _feed(ud, 85, track_id_present=True, track_id=None)
        assert ud.track_states == {}

    def test_missing_keypoint_skips_angle(self):
        # Triplet keypoint index beyond available points -> p_* is None ->
        # angle not computed, no rep, no crash.
        ud = _make_user_data("squat")
        short_points = [FakePoint(0.5, 0.5)]  # only nose available
        _feed(ud, 0, has_landmarks=True, points=short_points)
        assert 1 in ud.track_states
        assert ud.track_states[1].rep_count == 0
        assert ud.track_states[1].current_angle == 0.0

    def test_none_buffer_is_safe(self):
        ud = _make_user_data("squat")
        ud.increment()
        # Should return without raising and create no state.
        app_callback(_ELEMENT, None, ud)
        assert ud.track_states == {}


# ===========================================================================
# track_states pruning & multi-track independence
# ===========================================================================

class TestTrackPruning:
    def test_absent_track_is_pruned(self):
        ud = _make_user_data("squat")
        _feed(ud, 85, track_id=7)
        assert 7 in ud.track_states
        # Next frame has a different track only -> id 7 must be pruned.
        _feed(ud, 85, track_id=9)
        assert 7 not in ud.track_states
        assert 9 in ud.track_states

    def test_empty_frame_prunes_all(self):
        ud = _make_user_data("squat")
        _feed(ud, 85, track_id=3)
        assert ud.track_states
        _run_frame(ud, [])  # no detections this frame
        assert ud.track_states == {}

    def test_two_tracks_count_independently(self):
        ud = _make_user_data("squat")
        # Frame 1: both go down.
        _run_frame(ud, [
            FakeDetection(track_id=1, points=_angle_points_for(85)),
            FakeDetection(track_id=2, points=_angle_points_for(170)),
        ])
        # Frame 2: track 1 stands -> rep; track 2 goes down.
        _run_frame(ud, [
            FakeDetection(track_id=1, points=_angle_points_for(165)),
            FakeDetection(track_id=2, points=_angle_points_for(85)),
        ])
        # Frame 3: track 2 stands -> rep; track 1 stays up.
        _run_frame(ud, [
            FakeDetection(track_id=1, points=_angle_points_for(170)),
            FakeDetection(track_id=2, points=_angle_points_for(165)),
        ])
        assert ud.track_states[1].rep_count == 1
        assert ud.track_states[2].rep_count == 1

    def test_track_reappears_after_prune_resets(self):
        ud = _make_user_data("squat")
        _feed(ud, 85, track_id=5)   # track 5 down
        _run_frame(ud, [])          # pruned
        assert 5 not in ud.track_states
        _feed(ud, 165, track_id=5)  # reappears in up position
        # Fresh state: phase started 'up', a single up reading => no rep.
        assert ud.track_states[5].rep_count == 0
        assert ud.track_states[5].phase == "up"


# ===========================================================================
# Exercise config sanity
# ===========================================================================

class TestExerciseConfig:
    def test_exercises_present(self):
        assert set(EXERCISES) == {"squat", "pushup", "bicep_curl"}

    @pytest.mark.parametrize("name", list(EXERCISES))
    def test_each_exercise_has_triplet_and_thresholds(self, name):
        cfg = EXERCISES[name]
        ja, jb, jc = cfg["joint_triplet"]
        assert ja in KEYPOINTS and jb in KEYPOINTS and jc in KEYPOINTS
        assert isinstance(cfg["down_angle"], (int, float))
        assert isinstance(cfg["up_angle"], (int, float))

    def test_bicep_curl_is_inverted(self):
        assert EXERCISES["bicep_curl"]["down_angle"] > EXERCISES["bicep_curl"]["up_angle"]

    def test_squat_and_pushup_not_inverted(self):
        for name in ("squat", "pushup"):
            assert EXERCISES[name]["down_angle"] < EXERCISES[name]["up_angle"]

    def test_unknown_exercise_falls_back_to_squat(self):
        # The callback uses EXERCISES.get(exercise, EXERCISES["squat"]).
        ud = _make_user_data("does_not_exist")
        _feed(ud, 85)    # squat down threshold
        _feed(ud, 165)
        assert ud.track_states[1].rep_count == 1
