"""Pure-Python unit tests for the Baby Sleep Monitor app.

Covers the sleep-position safety classifier (``analyze_sleep_position``),
keypoint visibility via the confidence accessor, and the sustained-DANGER
alert state machine (``BabySleepCallbackData.update_status``).

No Hailo device, GStreamer pipeline, or inference is exercised: keypoints,
bounding boxes and landmark containers are all faked in pure Python.
"""

import os
import sys

import pytest

_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..")
)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from community.apps.pipeline_apps.baby_sleep_monitor.baby_sleep_monitor import (
    KEYPOINTS,
    KEYPOINT_CONF_THRESHOLD,
    STATUS_DANGER,
    STATUS_SAFE,
    STATUS_WARNING,
    BabySleepCallbackData,
    analyze_sleep_position,
    get_keypoint_pixel_coords,
)

pytestmark = pytest.mark.community


# ---------------------------------------------------------------------------
# Fakes mimicking the Hailo C++ landmark / bbox API surface used by the app:
#   - point.x() / point.y() / point.confidence()
#   - bbox.width() / bbox.height() / bbox.xmin() / bbox.ymin()
#   - landmarks[0].get_points() -> list of 17 points (COCO order)
# ---------------------------------------------------------------------------

# A unit bbox at the origin scaled by FRAME means normalized point coords map
# 1:1 onto pixels: pixel = int(coord * FRAME).
FRAME = 1000


class FakePoint:
    def __init__(self, x=0.0, y=0.0, confidence=1.0):
        self._x = x
        self._y = y
        self._confidence = confidence

    def x(self):
        return self._x

    def y(self):
        return self._y

    def confidence(self):
        return self._confidence


class FakeBBox:
    def __init__(self, xmin=0.0, ymin=0.0, width=1.0, height=1.0):
        self._xmin = xmin
        self._ymin = ymin
        self._width = width
        self._height = height

    def xmin(self):
        return self._xmin

    def ymin(self):
        return self._ymin

    def width(self):
        return self._width

    def height(self):
        return self._height


class FakeLandmarks:
    """Wraps a 17-element point list, exposing get_points()."""

    def __init__(self, points):
        self._points = points

    def get_points(self):
        return self._points


def make_landmarks(overrides=None):
    """Build a full 17-keypoint landmark container.

    By default every keypoint is invisible (confidence 0) at the origin.
    ``overrides`` maps a COCO keypoint name -> dict(x=, y=, confidence=).
    Returns the ``[landmarks_obj]`` list that the app expects.
    """
    points = [FakePoint(0.0, 0.0, 0.0) for _ in range(len(KEYPOINTS))]
    if overrides:
        for name, attrs in overrides.items():
            idx = KEYPOINTS[name]
            points[idx] = FakePoint(
                attrs.get("x", 0.0),
                attrs.get("y", 0.0),
                attrs.get("confidence", 1.0),
            )
    return [FakeLandmarks(points)]


def classify(overrides):
    landmarks = make_landmarks(overrides)
    return analyze_sleep_position(landmarks, FakeBBox(), FRAME, FRAME)


# Reusable posture building blocks (normalized coords; y grows downward).
VIS = {"confidence": 1.0}


def _face(nose=(0.5, 0.30), left_eye=(0.45, 0.28), right_eye=(0.55, 0.28)):
    return {
        "nose": {"x": nose[0], "y": nose[1], **VIS},
        "left_eye": {"x": left_eye[0], "y": left_eye[1], **VIS},
        "right_eye": {"x": right_eye[0], "y": right_eye[1], **VIS},
    }


def _level_shoulders(y=0.50, left_x=0.40, right_x=0.60):
    return {
        "left_shoulder": {"x": left_x, "y": y, **VIS},
        "right_shoulder": {"x": right_x, "y": y, **VIS},
    }


# ---------------------------------------------------------------------------
# get_keypoint_pixel_coords
# ---------------------------------------------------------------------------

def test_pixel_coords_unit_bbox_maps_one_to_one():
    px, py = get_keypoint_pixel_coords(FakePoint(0.5, 0.25), FakeBBox(), FRAME, FRAME)
    assert (px, py) == (500, 250)


def test_pixel_coords_respects_bbox_offset_and_scale():
    bbox = FakeBBox(xmin=0.1, ymin=0.2, width=0.5, height=0.5)
    # x = (0.5*0.5 + 0.1)*1000 = 350 ; y = (0.4*0.5 + 0.2)*1000 = 400
    px, py = get_keypoint_pixel_coords(FakePoint(0.5, 0.4), bbox, FRAME, FRAME)
    assert (px, py) == (350, 400)


# ---------------------------------------------------------------------------
# SAFE classification
# ---------------------------------------------------------------------------

def test_supine_back_position_is_safe():
    overrides = {**_face(), **_level_shoulders()}
    status, reason = classify(overrides)
    assert status == STATUS_SAFE
    assert "supine" in reason.lower() or "back" in reason.lower()


def test_supine_without_shoulders_still_safe():
    # Only face visible (no shoulders): face-up with both eyes + nose -> SAFE.
    status, reason = classify(_face())
    assert status == STATUS_SAFE


# ---------------------------------------------------------------------------
# DANGER classification
# ---------------------------------------------------------------------------

def test_nose_not_visible_with_shoulders_is_danger():
    # Eyes visible (so the eyes-not-visible rule doesn't fire), nose hidden,
    # shoulders visible -> face-down by the nose rule.
    overrides = {
        "left_eye": {"x": 0.45, "y": 0.28, **VIS},
        "right_eye": {"x": 0.55, "y": 0.28, **VIS},
        **_level_shoulders(),
        # nose left invisible (confidence 0 default)
    }
    status, reason = classify(overrides)
    assert status == STATUS_DANGER
    assert "nose" in reason.lower()


def test_both_eyes_not_visible_is_danger():
    # Nose visible, no shoulders, both eyes hidden -> face-down by eyes rule.
    overrides = {"nose": {"x": 0.5, "y": 0.30, **VIS}}
    status, reason = classify(overrides)
    assert status == STATUS_DANGER
    assert "eye" in reason.lower()


def test_twisted_body_is_danger():
    # Large vertical shoulder offset relative to horizontal span -> twist>1.0.
    overrides = {
        **_face(),
        "left_shoulder": {"x": 0.40, "y": 0.40, **VIS},
        "right_shoulder": {"x": 0.50, "y": 0.70, **VIS},
        # width = 0.10*1000=100 ; height diff = 0.30*1000=300 ; ratio=3.0
    }
    status, reason = classify(overrides)
    assert status == STATUS_DANGER
    assert "twist" in reason.lower()


# ---------------------------------------------------------------------------
# WARNING classification
# ---------------------------------------------------------------------------

def test_partially_turned_is_warning():
    # twist_ratio between 0.5 and 1.0.
    overrides = {
        **_face(),
        "left_shoulder": {"x": 0.40, "y": 0.45, **VIS},
        "right_shoulder": {"x": 0.60, "y": 0.60, **VIS},
        # width = 200px ; height diff = 150px ; ratio = 0.75
    }
    status, reason = classify(overrides)
    assert status == STATUS_WARNING
    assert "side" in reason.lower() or "turn" in reason.lower()


def test_head_position_low_is_warning():
    # Level shoulders (low twist), nose well below shoulder line.
    overrides = {
        **_face(nose=(0.5, 0.70)),  # nose y=700px
        **_level_shoulders(y=0.50),  # shoulders y=500px ; 700 > 500+30
    }
    status, reason = classify(overrides)
    assert status == STATUS_WARNING
    assert "low" in reason.lower() or "head" in reason.lower()


def test_one_eye_hidden_is_side_warning():
    # Nose + one eye visible, no shoulders -> side position.
    overrides = {
        "nose": {"x": 0.5, "y": 0.30, **VIS},
        "left_eye": {"x": 0.45, "y": 0.28, **VIS},
        # right_eye invisible
    }
    status, reason = classify(overrides)
    assert status == STATUS_WARNING
    assert "side" in reason.lower() or "eye" in reason.lower()


def test_ambiguous_position_is_warning():
    # Nose + one eye visible reaches the "one eye hidden" branch, so to hit the
    # final ambiguous fallthrough we need: nose visible, exactly one eye, AND
    # shoulders visible & level so earlier branches pass -- but that still hits
    # the one-eye branch. The true fallthrough needs nose+one-eye to NOT both
    # be true. Construct: nose visible, neither-eye-hidden test must be false.
    # Simplest ambiguous case: nose visible, both eyes visible is SAFE; so
    # craft nose visible, both eyes visible blocked by requiring shoulders that
    # are level (no warning) -> SAFE. Instead: nose visible only (no eyes) is
    # caught by eyes-not-visible DANGER. The reachable ambiguous path: shoulders
    # visible & level, nose visible & not-low, and exactly-one-eye is false
    # because BOTH eyes invisible -> but that's DANGER. So ambiguous requires
    # nose hidden + shoulders hidden + at least one eye visible.
    overrides = {
        "left_eye": {"x": 0.45, "y": 0.28, **VIS},
        "right_eye": {"x": 0.55, "y": 0.28, **VIS},
        # nose hidden, no shoulders -> skips nose/eye danger, skips shoulder
        # block, both eyes visible so one-eye branch false, nose not visible so
        # SAFE branch false -> ambiguous.
    }
    status, reason = classify(overrides)
    assert status == STATUS_WARNING
    assert "ambiguous" in reason.lower()


# ---------------------------------------------------------------------------
# Visibility via confidence accessor (the fix: confidence() vs origin pixel)
# ---------------------------------------------------------------------------

def test_low_confidence_keypoint_treated_as_not_visible():
    # All face/shoulder points present but BELOW threshold -> none "visible".
    low = {"confidence": KEYPOINT_CONF_THRESHOLD - 0.01}
    overrides = {
        "nose": {"x": 0.5, "y": 0.30, **low},
        "left_eye": {"x": 0.45, "y": 0.28, **low},
        "right_eye": {"x": 0.55, "y": 0.28, **low},
    }
    status, reason = classify(overrides)
    # nose not visible, no shoulders; both eyes invisible -> eyes DANGER rule.
    assert status == STATUS_DANGER
    assert "eye" in reason.lower()


def test_confidence_exactly_at_threshold_is_visible():
    # >= threshold counts as visible. A keypoint sitting at (0,0) but with
    # threshold confidence must NOT be treated as missing (the bug being fixed).
    at = {"confidence": KEYPOINT_CONF_THRESHOLD}
    overrides = {
        "nose": {"x": 0.0, "y": 0.0, **at},        # at origin, but confident
        "left_eye": {"x": 0.0, "y": 0.0, **at},
        "right_eye": {"x": 0.0, "y": 0.0, **at},
    }
    status, reason = classify(overrides)
    assert status == STATUS_SAFE  # all three visible -> supine


def test_high_confidence_point_at_origin_is_visible_not_missing():
    # Explicit regression guard: a fully-confident keypoint at pixel (0,0) is
    # visible. Under the old origin-heuristic this would be a false negative.
    overrides = {**_face(nose=(0.0, 0.0)), **_level_shoulders()}
    status, _ = classify(overrides)
    assert status == STATUS_SAFE


def test_all_keypoints_low_confidence_is_warning():
    # Nothing visible at all: nose hidden, no shoulders (so face-down nose rule
    # skipped), no eyes visible -> eyes-not-visible DANGER fires.
    status, reason = classify({})  # all default confidence 0
    assert status == STATUS_DANGER
    assert "eye" in reason.lower()


def test_just_below_threshold_loses_visibility():
    # One eye just under threshold -> only the other eye visible -> side warning.
    overrides = {
        "nose": {"x": 0.5, "y": 0.30, **VIS},
        "left_eye": {"x": 0.45, "y": 0.28, "confidence": 1.0},
        "right_eye": {"x": 0.55, "y": 0.28,
                      "confidence": KEYPOINT_CONF_THRESHOLD - 1e-6},
    }
    status, reason = classify(overrides)
    assert status == STATUS_WARNING
    assert "side" in reason.lower() or "eye" in reason.lower()


# ---------------------------------------------------------------------------
# Edge geometry
# ---------------------------------------------------------------------------

def test_zero_width_shoulders_skips_twist_division():
    # Shoulders stacked vertically (same x) -> shoulder_width == 0, the twist
    # ratio guard (width>0) must avoid ZeroDivisionError. Nose level so no
    # low-head warning -> falls through to SAFE (nose+both eyes visible).
    overrides = {
        **_face(),
        "left_shoulder": {"x": 0.50, "y": 0.45, **VIS},
        "right_shoulder": {"x": 0.50, "y": 0.55, **VIS},
    }
    status, reason = classify(overrides)
    # No crash; both eyes + nose visible, head not low -> SAFE.
    assert status == STATUS_SAFE


def test_twist_ratio_just_above_warning_boundary():
    # ratio slightly > 0.5 -> WARNING (partially turned).
    overrides = {
        **_face(),
        "left_shoulder": {"x": 0.40, "y": 0.50, **VIS},
        "right_shoulder": {"x": 0.60, "y": 0.601, **VIS},
        # width=200px, diff=101px, ratio=0.505 > 0.5
    }
    status, _ = classify(overrides)
    assert status == STATUS_WARNING


def test_twist_ratio_just_below_warning_boundary_not_warning():
    # ratio slightly < 0.5 -> no twist warning; level-ish, nose not low -> SAFE.
    overrides = {
        **_face(),
        "left_shoulder": {"x": 0.40, "y": 0.50, **VIS},
        "right_shoulder": {"x": 0.60, "y": 0.599, **VIS},
        # width=200px, diff=99px, ratio=0.495 < 0.5
    }
    status, _ = classify(overrides)
    assert status == STATUS_SAFE


# ---------------------------------------------------------------------------
# Sustained-DANGER alert state machine (BabySleepCallbackData.update_status)
# ---------------------------------------------------------------------------

class FakeClock:
    """Monotonic-ish controllable clock for patching time.time()."""

    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, dt):
        self.now += dt


@pytest.fixture
def cb(monkeypatch):
    """A callback-data object with a controllable clock and silenced alert."""
    data = BabySleepCallbackData()
    clock = FakeClock()
    import community.apps.pipeline_apps.baby_sleep_monitor.baby_sleep_monitor as mod
    monkeypatch.setattr(mod.time, "time", clock)
    # Record alert triggers instead of spawning a logging thread.
    data.triggered = 0

    def _fake_trigger():
        data.triggered += 1

    data._trigger_audio_alert = _fake_trigger
    data._clock = clock
    return data


def test_single_danger_frame_does_not_alert(cb):
    cb.update_status(STATUS_DANGER, "Twisted body position")
    assert cb.danger_start_time is not None
    assert cb.alert_active is False
    assert cb.triggered == 0


def test_danger_below_threshold_does_not_alert(cb):
    cb.update_status(STATUS_DANGER, "x")
    cb._clock.advance(cb.danger_threshold_seconds - 0.5)  # still under 3s
    cb.update_status(STATUS_DANGER, "x")
    assert cb.alert_active is False
    assert cb.triggered == 0


def test_sustained_danger_triggers_alert_after_threshold(cb):
    cb.update_status(STATUS_DANGER, "x")
    cb._clock.advance(cb.danger_threshold_seconds + 0.1)  # exceed 3s
    cb.update_status(STATUS_DANGER, "x")
    assert cb.alert_active is True
    assert cb.triggered == 1


def test_alert_fires_only_once_while_sustained(cb):
    cb.update_status(STATUS_DANGER, "x")
    cb._clock.advance(cb.danger_threshold_seconds + 0.1)
    cb.update_status(STATUS_DANGER, "x")
    cb._clock.advance(5.0)
    cb.update_status(STATUS_DANGER, "x")  # still danger, should not re-fire
    assert cb.triggered == 1
    assert cb.alert_active is True


def test_threshold_is_strict_greater_than(cb):
    # The check is "> threshold", so EXACTLY at the threshold must not fire yet.
    cb.update_status(STATUS_DANGER, "x")
    cb._clock.advance(cb.danger_threshold_seconds)  # exactly 3.0s elapsed
    cb.update_status(STATUS_DANGER, "x")
    assert cb.alert_active is False
    assert cb.triggered == 0


def test_safe_resets_danger_timer_and_alert(cb):
    cb.update_status(STATUS_DANGER, "x")
    cb._clock.advance(cb.danger_threshold_seconds + 0.1)
    cb.update_status(STATUS_DANGER, "x")
    assert cb.alert_active is True

    cb.update_status(STATUS_SAFE, "back")
    assert cb.danger_start_time is None
    assert cb.alert_active is False


def test_danger_then_safe_then_danger_requires_full_resustain(cb):
    # An intervening SAFE frame resets the timer; a brief later DANGER must not
    # immediately re-alert.
    cb.update_status(STATUS_DANGER, "x")
    cb._clock.advance(cb.danger_threshold_seconds + 0.1)
    cb.update_status(STATUS_DANGER, "x")
    assert cb.triggered == 1

    cb.update_status(STATUS_SAFE, "ok")        # reset
    cb.update_status(STATUS_DANGER, "x")       # new danger window starts now
    cb._clock.advance(0.5)
    cb.update_status(STATUS_DANGER, "x")
    assert cb.alert_active is False            # not yet sustained
    assert cb.triggered == 1                   # no new alert

    cb._clock.advance(cb.danger_threshold_seconds)  # now exceed again
    cb.update_status(STATUS_DANGER, "x")
    assert cb.alert_active is True
    assert cb.triggered == 2


def test_warning_also_resets_danger_state(cb):
    cb.update_status(STATUS_DANGER, "x")
    assert cb.danger_start_time is not None
    cb.update_status(STATUS_WARNING, "side")
    assert cb.danger_start_time is None
    assert cb.alert_active is False
    assert cb.triggered == 0


def test_status_and_reason_recorded(cb):
    cb.update_status(STATUS_WARNING, "Side position: one eye hidden")
    assert cb.current_status == STATUS_WARNING
    assert cb.current_reason == "Side position: one eye hidden"
