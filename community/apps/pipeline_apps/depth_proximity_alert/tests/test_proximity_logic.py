"""Pure-Python unit tests for the Depth Proximity Alert callback logic.

These tests exercise ``ProximityAlertCallback`` (ROI extraction, the
5th-percentile + N-frame deque smoothing, the alert/threshold decision, and
the 95th-percentile average-depth helper) plus the CLI range validation
contract from ``main()``. No Hailo device, no GStreamer pipeline, and no
inference are involved — only NumPy arrays fed directly into the callback
methods.

``gi`` and ``hailo`` are importable in the test environment, so the app module
imports cleanly; we additionally stub them defensively (mirroring the sibling
``depth_anything_python`` test) so the suite stays device/GStreamer-free on
machines where those native modules are absent.
"""

import sys
from collections import deque
from unittest.mock import MagicMock

import numpy as np
import pytest

pytestmark = pytest.mark.community

# ----------------------------------------------------------------------------
# Defensive stubs: install fakes for the heavy native / GStreamer modules ONLY
# if they are not already importable, so the app import is pure-Python and
# device-free everywhere. Where they exist (this env) the real modules win.
# ----------------------------------------------------------------------------
for _mod_name in ("hailo",):
    if _mod_name not in sys.modules:
        try:  # pragma: no cover - environment dependent
            __import__(_mod_name)
        except Exception:  # pragma: no cover
            sys.modules[_mod_name] = MagicMock()

try:  # pragma: no cover - environment dependent
    import gi  # noqa: F401
except Exception:  # pragma: no cover
    gi_stub = MagicMock()
    sys.modules["gi"] = gi_stub
    sys.modules["gi.repository"] = MagicMock()

from community.apps.pipeline_apps.depth_proximity_alert.depth_proximity_alert import (  # noqa: E402
    ALERT_COOLDOWN_SECONDS,
    ProximityAlertCallback,
)


# ============================================================================
# get_region_depth — ROI extraction
# ============================================================================
class TestGetRegionDepth:
    def test_default_region_is_center_50_percent(self):
        """With no alert_region, the ROI is the center 50% ([h/4:3h/4, w/4:3w/4])."""
        cb = ProximityAlertCallback()
        arr = np.arange(100).reshape(10, 10)
        region = cb.get_region_depth(arr)
        # 10//4 = 2, 3*10//4 = 7  ->  rows 2..6, cols 2..6 == 5x5 == 25 values.
        assert region.size == 25
        expected = arr[2:7, 2:7].flatten()
        assert sorted(region.tolist()) == sorted(expected.tolist())

    def test_custom_region_extracts_expected_slice(self):
        """A custom normalized region maps to int(rx*w):int((rx+rw)*w) etc."""
        # top-left quarter of an 8x8 frame -> rows 0..3, cols 0..3 (4x4 = 16)
        cb = ProximityAlertCallback(alert_region=(0.0, 0.0, 0.5, 0.5))
        arr = np.arange(64).reshape(8, 8)
        region = cb.get_region_depth(arr)
        assert region.size == 16
        expected = arr[0:4, 0:4].flatten()
        assert sorted(region.tolist()) == sorted(expected.tolist())

    def test_region_covering_whole_frame_returns_all_values(self):
        cb = ProximityAlertCallback(alert_region=(0.0, 0.0, 1.0, 1.0))
        arr = np.arange(16).reshape(4, 4)
        region = cb.get_region_depth(arr)
        assert sorted(region.tolist()) == sorted(arr.flatten().tolist())

    def test_1d_input_is_flattened_and_returned_whole(self):
        """ndim < 2 short-circuits: the whole flattened array comes back."""
        cb = ProximityAlertCallback()
        arr = np.array([3.0, 1.0, 2.0])
        region = cb.get_region_depth(arr)
        assert region.tolist() == [3.0, 1.0, 2.0]

    def test_scalar_like_0d_input_flattens_to_single_value(self):
        cb = ProximityAlertCallback()
        region = cb.get_region_depth(np.float32(5.0))
        assert region.tolist() == [5.0]

    def test_degenerate_region_is_clamped_to_at_least_one_pixel(self):
        """A zero-width region (w=0) is clamped so x2 >= x1+1; never empty."""
        cb = ProximityAlertCallback(alert_region=(0.5, 0.5, 0.0, 0.0))
        arr = np.arange(100).reshape(10, 10)
        region = cb.get_region_depth(arr)
        assert region.size >= 1

    def test_out_of_frame_region_is_clamped_not_crashing(self):
        """Region extending past the frame edge is clamped to valid bounds."""
        cb = ProximityAlertCallback(alert_region=(0.9, 0.9, 0.9, 0.9))
        arr = np.arange(100).reshape(10, 10)
        region = cb.get_region_depth(arr)
        assert region.size >= 1
        # All extracted values come from the bottom-right corner of the array.
        assert region.max() <= arr.max()

    def test_accepts_python_list_input(self):
        """get_region_depth wraps input in np.array, so a nested list works."""
        cb = ProximityAlertCallback(alert_region=(0.0, 0.0, 1.0, 1.0))
        region = cb.get_region_depth([[1, 2], [3, 4]])
        assert sorted(region.tolist()) == [1, 2, 3, 4]

    def test_3d_depth_uses_first_two_dims_for_roi(self):
        """shape[:2] drives the ROI even when a trailing channel dim is present."""
        cb = ProximityAlertCallback(alert_region=(0.0, 0.0, 1.0, 1.0))
        arr = np.arange(2 * 2 * 1).reshape(2, 2, 1)
        region = cb.get_region_depth(arr)
        # Region slice keeps the trailing dim; flatten collapses everything.
        assert region.size == 4


# ============================================================================
# check_proximity — percentile + smoothing + threshold decision
# ============================================================================
class TestCheckProximity:
    def test_empty_input_returns_no_alert_zeros(self):
        cb = ProximityAlertCallback(proximity_threshold=0.5)
        assert cb.check_proximity(np.array([])) == (False, 0.0, 0.0)
        # Nothing should have been pushed into the history.
        assert len(cb.min_depth_history) == 0

    def test_uses_5th_percentile_as_current_min(self):
        """current_min_depth == 5th percentile of the input values."""
        cb = ProximityAlertCallback(proximity_threshold=1.0)
        values = np.arange(100, dtype=np.float64)  # 0..99
        is_alert, smoothed, current = cb.check_proximity(values)
        assert current == pytest.approx(np.percentile(values, 5))  # 4.95
        # First frame: smoothed == current (single sample in the deque).
        assert smoothed == pytest.approx(current)

    def test_alert_true_when_smoothed_at_or_below_threshold(self):
        """is_alert is smoothed <= threshold (boundary is inclusive)."""
        cb = ProximityAlertCallback(proximity_threshold=0.2)
        # Constant 0.2 -> p5 == 0.2 == threshold -> alert (<=).
        is_alert, smoothed, current = cb.check_proximity(np.full(50, 0.2))
        assert smoothed == pytest.approx(0.2)
        assert is_alert is True

    def test_no_alert_when_smoothed_above_threshold(self):
        cb = ProximityAlertCallback(proximity_threshold=0.2)
        is_alert, smoothed, _ = cb.check_proximity(np.full(50, 0.5))
        assert smoothed == pytest.approx(0.5)
        assert is_alert is False

    def test_threshold_exact_boundary_is_inclusive(self):
        """smoothed == threshold must alert (the comparison is <=, not <)."""
        cb = ProximityAlertCallback(proximity_threshold=0.3)
        is_alert, smoothed, _ = cb.check_proximity(np.full(10, 0.3))
        assert smoothed == pytest.approx(0.3)
        assert is_alert is True

    def test_just_above_boundary_does_not_alert(self):
        cb = ProximityAlertCallback(proximity_threshold=0.3)
        is_alert, smoothed, _ = cb.check_proximity(np.full(10, 0.3000001))
        assert is_alert is False

    def test_constant_depth_p5_equals_value(self):
        cb = ProximityAlertCallback(proximity_threshold=1.0)
        _, smoothed, current = cb.check_proximity(np.full(20, 0.42))
        assert current == pytest.approx(0.42)
        assert smoothed == pytest.approx(0.42)

    def test_all_zero_depth_alerts_for_any_positive_threshold(self):
        cb = ProximityAlertCallback(proximity_threshold=0.1)
        is_alert, smoothed, current = cb.check_proximity(np.zeros(30))
        assert current == 0.0
        assert smoothed == 0.0
        assert is_alert is True

    def test_zero_threshold_only_alerts_when_smoothed_is_zero(self):
        cb = ProximityAlertCallback(proximity_threshold=0.0)
        # zeros -> smoothed 0.0 <= 0.0 -> alert
        assert cb.check_proximity(np.zeros(10))[0] is True
        cb2 = ProximityAlertCallback(proximity_threshold=0.0)
        # any positive depth -> smoothed > 0.0 -> no alert
        assert cb2.check_proximity(np.full(10, 0.01))[0] is False

    def test_single_value_input(self):
        cb = ProximityAlertCallback(proximity_threshold=1.0)
        is_alert, smoothed, current = cb.check_proximity(np.array([0.7]))
        assert current == pytest.approx(0.7)
        assert smoothed == pytest.approx(0.7)


# ============================================================================
# Smoothing deque behavior (maxlen, windowed mean, oldest drop)
# ============================================================================
class TestSmoothingDeque:
    def test_history_is_bounded_deque_with_maxlen_10(self):
        cb = ProximityAlertCallback()
        assert isinstance(cb.min_depth_history, deque)
        assert cb.min_depth_history.maxlen == 10
        assert cb.history_max_len == 10

    def test_smoothed_is_running_mean_over_window(self):
        """Each call appends the per-frame p5; smoothed == mean of the window."""
        cb = ProximityAlertCallback(proximity_threshold=1.0)
        # Feed three constant frames at 0.0, 0.3, 0.6 -> p5 == the constant.
        _, s1, _ = cb.check_proximity(np.full(10, 0.0))
        assert s1 == pytest.approx(0.0)
        _, s2, _ = cb.check_proximity(np.full(10, 0.3))
        assert s2 == pytest.approx(np.mean([0.0, 0.3]))  # 0.15
        _, s3, _ = cb.check_proximity(np.full(10, 0.6))
        assert s3 == pytest.approx(np.mean([0.0, 0.3, 0.6]))  # 0.3

    def test_oldest_value_drops_after_maxlen(self):
        """After maxlen frames, the window only averages the last 10 samples."""
        cb = ProximityAlertCallback(proximity_threshold=1.0)
        # Push 10 frames of value 1.0 to saturate the deque.
        for _ in range(10):
            cb.check_proximity(np.full(5, 1.0))
        assert len(cb.min_depth_history) == 10
        # The 11th frame (0.0) must evict the oldest 1.0; window = nine 1.0s + one 0.0.
        _, smoothed, _ = cb.check_proximity(np.full(5, 0.0))
        assert len(cb.min_depth_history) == 10
        assert smoothed == pytest.approx(np.mean([1.0] * 9 + [0.0]))  # 0.9

    def test_window_never_exceeds_maxlen(self):
        cb = ProximityAlertCallback()
        for i in range(25):
            cb.check_proximity(np.full(3, float(i)))
        assert len(cb.min_depth_history) == 10

    def test_smoothing_can_suppress_a_single_close_spike(self):
        """A lone close frame averaged with distant history may stay below alert."""
        cb = ProximityAlertCallback(proximity_threshold=0.2)
        # Nine frames far away (1.0), then one very close (0.0).
        for _ in range(9):
            cb.check_proximity(np.full(5, 1.0))
        is_alert, smoothed, current = cb.check_proximity(np.full(5, 0.0))
        # current (this frame) is 0.0, but the smoothed mean is 0.9 -> NOT an alert.
        assert current == pytest.approx(0.0)
        assert smoothed == pytest.approx(0.9)
        assert is_alert is False


# ============================================================================
# calculate_average_depth — 95th-percentile outlier drop
# ============================================================================
class TestCalculateAverageDepth:
    def test_drops_top_5_percent_outliers(self):
        cb = ProximityAlertCallback()
        # 0..99: keep values <= p95 (94.05) -> 0..94, mean == 47.0
        avg = cb.calculate_average_depth(np.arange(100))
        kept = np.arange(100)[np.arange(100) <= np.percentile(np.arange(100), 95)]
        assert avg == pytest.approx(float(np.mean(kept)))
        assert avg == pytest.approx(47.0)

    def test_constant_depth_returns_that_constant(self):
        cb = ProximityAlertCallback()
        assert cb.calculate_average_depth(np.full(50, 3.5)) == pytest.approx(3.5)

    def test_all_zero_depth_returns_zero(self):
        cb = ProximityAlertCallback()
        assert cb.calculate_average_depth(np.zeros(50)) == 0.0

    def test_empty_input_returns_zero(self):
        cb = ProximityAlertCallback()
        assert cb.calculate_average_depth(np.array([])) == 0.0

    def test_accepts_2d_input_and_flattens(self):
        cb = ProximityAlertCallback()
        avg = cb.calculate_average_depth(np.full((4, 4), 2.0))
        assert avg == pytest.approx(2.0)

    def test_single_value(self):
        cb = ProximityAlertCallback()
        assert cb.calculate_average_depth(np.array([9.0])) == pytest.approx(9.0)


# ============================================================================
# Alert cooldown constant + state-machine timing
# ============================================================================
class TestAlertCooldown:
    def test_cooldown_constant_is_one_second(self):
        assert ALERT_COOLDOWN_SECONDS == 1.0

    def test_cooldown_logic_first_fire_then_suppress_then_refire(self):
        """Mirror the app_callback alert state machine to assert cooldown timing.

        The real callback fires when ``not alert_active`` OR a full
        ALERT_COOLDOWN_SECONDS has elapsed since the last fire. We drive that
        exact decision here with a synthetic monotonic clock.
        """

        def should_fire(alert_active, now, last_alert_time):
            return (not alert_active) or (
                (now - last_alert_time) >= ALERT_COOLDOWN_SECONDS
            )

        alert_active = False
        last_alert_time = 0.0

        # t=0.0: first detection -> fire.
        assert should_fire(alert_active, 0.0, last_alert_time) is True
        alert_active, last_alert_time = True, 0.0

        # t=0.5: within cooldown -> suppressed.
        assert should_fire(alert_active, 0.5, last_alert_time) is False

        # t=1.0: exactly the cooldown boundary (>=) -> re-fires.
        assert should_fire(alert_active, 1.0, last_alert_time) is True
        last_alert_time = 1.0

        # t=1.9: within the new cooldown -> suppressed again.
        assert should_fire(alert_active, 1.9, last_alert_time) is False

    def test_cleared_state_allows_immediate_refire(self):
        """When the alert clears (alert_active reset to False), the next
        detection fires immediately regardless of elapsed time."""

        def should_fire(alert_active, now, last_alert_time):
            return (not alert_active) or (
                (now - last_alert_time) >= ALERT_COOLDOWN_SECONDS
            )

        # alert cleared at some point -> alert_active False, last fire long ago=5.0
        assert should_fire(False, 5.1, 5.0) is True

    def test_initial_callback_state(self):
        cb = ProximityAlertCallback()
        assert cb.alert_active is False
        assert cb.last_alert_time == 0.0


# ============================================================================
# CLI validation contract for --proximity-threshold and --alert-region.
#
# The validation lives inline in depth_proximity_alert.main(); these helpers
# replicate that exact predicate set so we can assert the accept/reject
# boundaries without building a GStreamer pipeline. Keep in sync with main().
# ============================================================================
def _threshold_valid(t):
    return 0.0 <= t <= 1.0


def _alert_region_valid(region):
    if region is None:
        return True
    rx, ry, rw, rh = region
    if not all(0.0 <= v <= 1.0 for v in region):
        return False
    if rx + rw > 1.0 or ry + rh > 1.0:
        return False
    return True


class TestProximityThresholdValidation:
    @pytest.mark.parametrize("t", [0.0, 0.3, 0.5, 1.0])
    def test_in_range_thresholds_accepted(self, t):
        assert _threshold_valid(t) is True

    @pytest.mark.parametrize("t", [-0.1, -1.0, 1.0001, 1.5, 2.0, 100.0])
    def test_out_of_range_thresholds_rejected(self, t):
        assert _threshold_valid(t) is False

    def test_boundaries_inclusive(self):
        assert _threshold_valid(0.0) is True
        assert _threshold_valid(1.0) is True


class TestAlertRegionValidation:
    def test_none_is_valid_default(self):
        assert _alert_region_valid(None) is True

    @pytest.mark.parametrize(
        "region",
        [
            (0.0, 0.0, 1.0, 1.0),  # whole frame
            (0.25, 0.25, 0.5, 0.5),  # centered
            (0.0, 0.0, 0.0, 0.0),  # degenerate but in-range and in-frame
            (0.5, 0.5, 0.5, 0.5),  # exactly fills bottom-right, x+w==1.0
        ],
    )
    def test_in_range_in_frame_regions_accepted(self, region):
        assert _alert_region_valid(region) is True

    @pytest.mark.parametrize(
        "region",
        [
            (-0.1, 0.0, 0.5, 0.5),  # negative x
            (0.0, -0.1, 0.5, 0.5),  # negative y
            (0.0, 0.0, 1.5, 0.5),  # w > 1
            (0.0, 0.0, 0.5, 2.0),  # h > 1
        ],
    )
    def test_out_of_range_components_rejected(self, region):
        assert _alert_region_valid(region) is False

    @pytest.mark.parametrize(
        "region",
        [
            (0.6, 0.0, 0.6, 0.5),  # x+w = 1.2 > 1.0
            (0.0, 0.7, 0.5, 0.6),  # y+h = 1.3 > 1.0
            (0.9, 0.9, 0.2, 0.2),  # both overflow
        ],
    )
    def test_region_overflowing_frame_rejected(self, region):
        """In-range components that still extend past the frame are rejected."""
        # Each component is within [0,1] ...
        assert all(0.0 <= v <= 1.0 for v in region)
        # ... but the x+w / y+h sum check rejects it.
        assert _alert_region_valid(region) is False


# ============================================================================
# Integration of the pieces: ROI -> proximity decision over a synthetic depth
# array, end to end through the callback (still pure-Python, no device).
# ============================================================================
class TestEndToEndRoiToAlert:
    def test_close_object_in_center_triggers_alert(self):
        """A near (low-depth) blob in the center ROI drives the smoothed value
        below threshold and raises the alert."""
        cb = ProximityAlertCallback(proximity_threshold=0.2)
        frame = np.ones((20, 20), dtype=np.float32)  # far background = 1.0
        frame[5:15, 5:15] = 0.05  # close object fills the center ROI
        region = cb.get_region_depth(frame)
        is_alert, smoothed, _ = cb.check_proximity(region)
        assert smoothed == pytest.approx(0.05, abs=1e-6)
        assert is_alert is True

    def test_far_scene_does_not_alert(self):
        cb = ProximityAlertCallback(proximity_threshold=0.2)
        frame = np.full((20, 20), 0.9, dtype=np.float32)
        region = cb.get_region_depth(frame)
        is_alert, smoothed, _ = cb.check_proximity(region)
        assert smoothed == pytest.approx(0.9)
        assert is_alert is False

    def test_close_object_outside_custom_roi_is_ignored(self):
        """An object close in a corner is ignored when the ROI is elsewhere."""
        # ROI = top-left quarter only.
        cb = ProximityAlertCallback(
            proximity_threshold=0.2, alert_region=(0.0, 0.0, 0.5, 0.5)
        )
        frame = np.ones((20, 20), dtype=np.float32)
        frame[15:20, 15:20] = 0.0  # close object in the bottom-right, outside ROI
        region = cb.get_region_depth(frame)
        is_alert, smoothed, _ = cb.check_proximity(region)
        assert smoothed == pytest.approx(1.0)
        assert is_alert is False
