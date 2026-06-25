"""Pure-Python unit tests for the lane_departure_warning standalone app.

Covers:
  * UFLDProcessing softmax (`_soft_max`) — sum-to-1, argmax, numerical behaviour.
  * UFLDProcessing anchor decode (`_slice_and_reshape`, `_pred2coords`,
    `get_coordinates`) with synthetic model-output arrays + bottom-crop assumption.
  * DepartureDetector lateral-offset classification (centered / left / right /
    no-lanes) and the warning-threshold boundary.
  * Edge cases: empty/zero/all-equal model output, lanes missing on one side,
    too-short lanes, degenerate (narrow) lane width, exact-threshold value.

No device / inference / network access. Native modules (cv2 / hailo / hailo_platform)
are stubbed in sys.modules so the suite runs headless in its own process.
"""

import sys
from unittest.mock import MagicMock

import numpy as np
import pytest

# The app module imports cv2 and (via the core package) HailoRT bindings at
# import time. None of those are exercised by the logic under test, so stub them
# before importing the app. This file is run in its own pytest process (see the
# community testpaths note in pyproject.toml), so these stubs do not leak.
for _mod in [
    "cv2",
    "hailo",
    "hailo_platform",
    "hailo_platform.pyhailort",
    "hailo_platform.pyhailort.pyhailort",
]:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

from community.apps.standalone_apps.lane_departure_warning.lane_departure_warning_utils import (  # noqa: E402
    DepartureDetector,
    UFLDProcessing,
    compute_scaled_radius,
)

pytestmark = pytest.mark.community


# Small synthetic UFLD geometry used across decode tests. Values are tiny so the
# feature vector stays small but exercises all four output slices.
NUM_CELL_ROW = 4
NUM_CELL_COL = 4
NUM_ROW = 3
NUM_COL = 3
NUM_LANES = 4
FRAME_W = 1280
FRAME_H = 720


def make_ufld():
    return UFLDProcessing(
        num_cell_row=NUM_CELL_ROW,
        num_cell_col=NUM_CELL_COL,
        num_row=NUM_ROW,
        num_col=NUM_COL,
        num_lanes=NUM_LANES,
        crop_ratio=0.6,
        original_frame_width=FRAME_W,
        original_frame_height=FRAME_H,
        total_frames=1,
    )


def feature_len():
    dim1 = NUM_CELL_ROW * NUM_ROW * NUM_LANES
    dim2 = NUM_CELL_COL * NUM_COL * NUM_LANES
    dim3 = 2 * NUM_ROW * NUM_LANES
    dim4 = 2 * NUM_COL * NUM_LANES
    return dim1, dim2, dim3, dim4, dim1 + dim2 + dim3 + dim4


# ---------------------------------------------------------------------------
# _soft_max
# ---------------------------------------------------------------------------
class TestSoftMax:
    def test_sums_to_one(self):
        p = make_ufld()
        out = p._soft_max(np.array([1.0, 2.0, 3.0]))
        assert out.shape == (3,)
        assert np.isclose(out.sum(), 1.0)

    def test_all_probabilities_positive(self):
        p = make_ufld()
        out = p._soft_max(np.array([-5.0, 0.0, 5.0]))
        assert np.all(out > 0.0)
        assert np.all(out < 1.0)

    def test_argmax_preserved(self):
        """Softmax is monotonic — the largest logit gets the largest probability."""
        p = make_ufld()
        z = np.array([0.1, 3.0, 1.5, -2.0])
        out = p._soft_max(z)
        assert np.argmax(out) == np.argmax(z)

    def test_equal_logits_give_uniform(self):
        p = make_ufld()
        out = p._soft_max(np.array([2.0, 2.0, 2.0, 2.0]))
        assert np.allclose(out, 0.25)

    def test_single_element(self):
        p = make_ufld()
        out = p._soft_max(np.array([7.0]))
        assert np.isclose(out[0], 1.0)

    def test_known_values(self):
        """Compare against a hand-checked reference for [1, 2, 3]."""
        p = make_ufld()
        out = p._soft_max(np.array([1.0, 2.0, 3.0]))
        expected = np.array([0.09003057, 0.24472847, 0.66524096])
        assert np.allclose(out, expected, atol=1e-6)

    def test_large_logits_overflow_to_nan(self):
        """Documented behaviour: `_soft_max` has NO max-subtraction, so very
        large logits overflow exp() and produce nan. This is a known limitation
        of the app's implementation; this test pins the current behaviour so a
        future numerical-stability fix is a deliberate, visible change."""
        p = make_ufld()
        with np.errstate(over="ignore", invalid="ignore"):
            out = p._soft_max(np.array([1000.0, 1000.0, 1000.0]))
        assert np.all(np.isnan(out))

    def test_moderately_large_logits_still_finite(self):
        """Logits in a realistic post-network range stay finite and sum to 1."""
        p = make_ufld()
        out = p._soft_max(np.array([10.0, 20.0, 30.0]))
        assert np.all(np.isfinite(out))
        assert np.isclose(out.sum(), 1.0)
        assert np.argmax(out) == 2


# ---------------------------------------------------------------------------
# _slice_and_reshape
# ---------------------------------------------------------------------------
class TestSliceAndReshape:
    def test_output_shapes(self):
        p = make_ufld()
        _, _, _, _, total = feature_len()
        out = np.zeros((1, total), dtype=np.float32)
        loc_row, loc_col, exist_row, exist_col = p._slice_and_reshape(out)
        assert loc_row.shape == (1, NUM_CELL_ROW, NUM_ROW, NUM_LANES)
        assert loc_col.shape == (1, NUM_CELL_COL, NUM_COL, NUM_LANES)
        assert exist_row.shape == (1, 2, NUM_ROW, NUM_LANES)
        assert exist_col.shape == (1, 2, NUM_COL, NUM_LANES)

    def test_slices_are_contiguous_partition(self):
        """The four slices must come from disjoint, ordered regions of the
        flat feature vector — verify by tagging each region with a distinct
        constant and checking it lands in the right tensor."""
        p = make_ufld()
        dim1, dim2, dim3, dim4, total = feature_len()
        out = np.zeros((1, total), dtype=np.float32)
        out[:, :dim1] = 1.0
        out[:, dim1:dim1 + dim2] = 2.0
        out[:, dim1 + dim2:dim1 + dim2 + dim3] = 3.0
        out[:, dim1 + dim2 + dim3:] = 4.0
        loc_row, loc_col, exist_row, exist_col = p._slice_and_reshape(out)
        assert np.all(loc_row == 1.0)
        assert np.all(loc_col == 2.0)
        assert np.all(exist_row == 3.0)
        assert np.all(exist_col == 4.0)


# ---------------------------------------------------------------------------
# _pred2coords / get_coordinates — anchor decode
# ---------------------------------------------------------------------------
def build_output_with_valid_row_lanes():
    """Build a flat model-output array where the two row-based center lanes
    (indices 1 and 2) are marked 'valid' for every row anchor, and column lanes
    are absent. Returns the (1, total) float array."""
    p = make_ufld()
    dim1, dim2, dim3, dim4, total = feature_len()
    out = np.zeros((1, total), dtype=np.float32)

    # exist_row reshapes to (1, 2, num_row, num_lanes). argmax over axis 1
    # decides validity (index 1 == valid). Drive index 1 high for all rows/lanes.
    exist_row = np.zeros((1, 2, NUM_ROW, NUM_LANES), dtype=np.float32)
    exist_row[0, 1, :, :] = 10.0
    flat_exist_row = exist_row.reshape(-1)
    out[0, dim1 + dim2:dim1 + dim2 + dim3] = flat_exist_row
    return p, out


class TestPred2Coords:
    def test_two_center_row_lanes_decoded(self):
        p, out = build_output_with_valid_row_lanes()
        coords = p.get_coordinates(out)
        # Row lane indices [1, 2] both valid -> exactly two lanes returned.
        assert len(coords) == 2
        # Each valid row anchor produces a point -> num_row points per lane.
        for lane in coords:
            assert len(lane) == NUM_ROW

    def test_decoded_points_are_int_pixel_tuples(self):
        p, out = build_output_with_valid_row_lanes()
        coords = p.get_coordinates(out)
        for lane in coords:
            for pt in lane:
                assert isinstance(pt, tuple) and len(pt) == 2
                x, y = pt
                assert isinstance(x, int) and isinstance(y, int)

    def test_row_y_uses_bottom_crop_anchor_range(self):
        """The row anchors span linspace(160, 710, 56)/720 — i.e. the BOTTOM
        portion of the frame. Decoded y-coordinates must therefore all fall in
        the lower band of the frame (>= 160/720 * H), never near the top."""
        p, out = build_output_with_valid_row_lanes()
        coords = p.get_coordinates(out)
        min_expected_y = int((160.0 / 720.0) * FRAME_H)
        max_expected_y = int((710.0 / 720.0) * FRAME_H) + 1
        ys = [y for lane in coords for (_, y) in lane]
        assert ys, "expected decoded points"
        assert min(ys) >= min_expected_y
        assert max(ys) <= max_expected_y

    def test_decoded_x_within_frame_width(self):
        p, out = build_output_with_valid_row_lanes()
        coords = p.get_coordinates(out)
        for lane in coords:
            for x, _ in lane:
                assert 0 <= x <= FRAME_W

    def test_zero_output_yields_no_lanes(self):
        """All-zero output: argmax of existence ties -> index 0 (invalid) ->
        no lane passes the validity-sum gate."""
        p = make_ufld()
        _, _, _, _, total = feature_len()
        out = np.zeros((1, total), dtype=np.float32)
        assert p.get_coordinates(out) == []

    def test_all_equal_output_yields_no_lanes(self):
        """Constant non-zero output also ties existence argmax to index 0."""
        p = make_ufld()
        _, _, _, _, total = feature_len()
        out = np.full((1, total), 3.3, dtype=np.float32)
        assert p.get_coordinates(out) == []

    def test_insufficient_valid_rows_drops_lane(self):
        """Row lane is kept only if valid_row_sum > num_cls_row/2. With just one
        of three rows valid (1 is not > 1.5) the lane is dropped."""
        p = make_ufld()
        dim1, dim2, dim3, dim4, total = feature_len()
        out = np.zeros((1, total), dtype=np.float32)
        exist_row = np.zeros((1, 2, NUM_ROW, NUM_LANES), dtype=np.float32)
        # Mark only row 0 valid for lane index 1 -> sum == 1, not > 1.5.
        exist_row[0, 1, 0, 1] = 10.0
        out[0, dim1 + dim2:dim1 + dim2 + dim3] = exist_row.reshape(-1)
        assert p.get_coordinates(out) == []

    def test_get_original_frame_size(self):
        p = make_ufld()
        assert p.get_original_frame_size() == (FRAME_W, FRAME_H)


# ---------------------------------------------------------------------------
# DepartureDetector — classification
# ---------------------------------------------------------------------------
def lane_at(x, ys=(300, 320, 360)):
    """Helper: a lane (>=3 points) at constant x across the given y rows."""
    return [(x, y) for y in ys]


class TestDepartureClassification:
    def test_centered(self):
        d = DepartureDetector(frame_width=1000, frame_height=400,
                              departure_threshold=0.15, smoothing_window=1)
        # left avg 100, right avg 900 -> center 500 == vehicle 500 -> offset 0
        res = d.analyze_lanes([lane_at(100), lane_at(900)])
        assert res["status"] == DepartureDetector.CENTERED
        assert res["offset"] == pytest.approx(0.0)
        assert res["lane_center_x"] == pytest.approx(500.0)
        assert res["vehicle_x"] == pytest.approx(500.0)

    def test_right_departure(self):
        d = DepartureDetector(1000, 400, departure_threshold=0.15,
                              smoothing_window=1)
        # left 100, right 500 -> center 300, width 400, vehicle 500
        # offset = (500-300)/200 = +1.0  (vehicle right of lane center)
        res = d.analyze_lanes([lane_at(100), lane_at(500)])
        assert res["status"] == DepartureDetector.RIGHT_DEPARTURE
        assert res["offset"] == pytest.approx(1.0)

    def test_left_departure(self):
        d = DepartureDetector(1000, 400, departure_threshold=0.15,
                              smoothing_window=1)
        # left 500, right 900 -> center 700, width 400, vehicle 500
        # offset = (500-700)/200 = -1.0
        res = d.analyze_lanes([lane_at(500), lane_at(900)])
        assert res["status"] == DepartureDetector.LEFT_DEPARTURE
        assert res["offset"] == pytest.approx(-1.0)

    def test_lane_ordering_independent_of_input_order(self):
        """Lanes are sorted by x internally, so swapping input order must not
        change the classification."""
        a = DepartureDetector(1000, 400, 0.15, 1).analyze_lanes(
            [lane_at(100), lane_at(500)])
        b = DepartureDetector(1000, 400, 0.15, 1).analyze_lanes(
            [lane_at(500), lane_at(100)])
        assert a["status"] == b["status"] == DepartureDetector.RIGHT_DEPARTURE
        assert a["offset"] == pytest.approx(b["offset"])


class TestDepartureThresholdBoundary:
    def test_exact_threshold_is_centered(self):
        """Comparison is strict (`<`/`>`), so offset exactly == threshold stays
        CENTERED. center 470, width 400 -> offset (500-470)/200 = 0.15."""
        d = DepartureDetector(1000, 400, departure_threshold=0.15,
                              smoothing_window=1)
        res = d.analyze_lanes([lane_at(270), lane_at(670)])
        assert res["offset"] == pytest.approx(0.15)
        assert res["status"] == DepartureDetector.CENTERED

    def test_just_over_threshold_is_departure(self):
        d = DepartureDetector(1000, 400, departure_threshold=0.15,
                              smoothing_window=1)
        # center 469, width 400 -> offset (500-469)/200 = 0.155 > 0.15
        res = d.analyze_lanes([lane_at(269), lane_at(669)])
        assert res["offset"] > 0.15
        assert res["status"] == DepartureDetector.RIGHT_DEPARTURE

    def test_just_under_threshold_is_centered(self):
        d = DepartureDetector(1000, 400, departure_threshold=0.15,
                              smoothing_window=1)
        # center 471, width 400 -> offset (500-471)/200 = 0.145 < 0.15
        res = d.analyze_lanes([lane_at(271), lane_at(671)])
        assert res["offset"] < 0.15
        assert res["status"] == DepartureDetector.CENTERED

    def test_negative_exact_threshold_is_centered(self):
        """Symmetric boundary on the left side: offset == -threshold -> CENTERED."""
        d = DepartureDetector(1000, 400, departure_threshold=0.15,
                              smoothing_window=1)
        # center 530, width 400 -> offset (500-530)/200 = -0.15
        res = d.analyze_lanes([lane_at(330), lane_at(730)])
        assert res["offset"] == pytest.approx(-0.15)
        assert res["status"] == DepartureDetector.CENTERED


# ---------------------------------------------------------------------------
# DepartureDetector — edge cases
# ---------------------------------------------------------------------------
class TestDepartureEdgeCases:
    def test_empty_lanes(self):
        d = DepartureDetector(1000, 400)
        res = d.analyze_lanes([])
        assert res["status"] == DepartureDetector.NO_LANES
        assert res["offset"] == 0.0
        assert res["left_lane_x"] is None
        assert res["right_lane_x"] is None

    def test_single_lane_only(self):
        d = DepartureDetector(1000, 400)
        res = d.analyze_lanes([lane_at(300)])
        assert res["status"] == DepartureDetector.NO_LANES

    def test_lanes_too_short_are_filtered(self):
        """Lanes with fewer than 3 points are ignored -> not enough lanes."""
        d = DepartureDetector(1000, 400)
        res = d.analyze_lanes([[(100, 300), (110, 320)],
                               [(900, 300), (905, 320)]])
        assert res["status"] == DepartureDetector.NO_LANES

    def test_one_side_missing(self):
        """Only a left lane present (right side missing) -> NO_LANES."""
        d = DepartureDetector(1000, 400)
        res = d.analyze_lanes([lane_at(120)])
        assert res["status"] == DepartureDetector.NO_LANES

    def test_degenerate_narrow_lane_width(self):
        """Lane width < 10 px is treated as noise -> NO_LANES, but the measured
        lane x's are still reported for debugging."""
        d = DepartureDetector(1000, 400)
        res = d.analyze_lanes([lane_at(500), lane_at(505)])
        assert res["status"] == DepartureDetector.NO_LANES
        assert res["left_lane_x"] is not None
        assert res["right_lane_x"] is not None

    def test_bottom_crop_assumption_uses_lower_70pct(self):
        """avg_x_bottom only averages points with y >= 0.7*H. Points above that
        band must be ignored, so a lane whose top points are far off-center does
        not skew the result."""
        # H=400 -> bottom threshold y=280. Put a wild outlier at y=10 (ignored),
        # real lane at x=100 for y>=280.
        d = DepartureDetector(1000, 400, 0.15, 1)
        left = [(9000, 10), (100, 300), (100, 320), (100, 360)]
        right = [(900, 300), (900, 320), (900, 360)]
        res = d.analyze_lanes([left, right])
        # If the y=10 outlier counted, left avg would be huge; instead it's 100.
        assert res["left_lane_x"] == pytest.approx(100.0)
        assert res["status"] == DepartureDetector.CENTERED

    def test_fallback_to_last_points_when_none_in_bottom_band(self):
        """If no point lies in the bottom 70%, avg_x_bottom falls back to the
        last 5 points, so a lane fully in the upper frame is still usable."""
        d = DepartureDetector(1000, 400, 0.15, 1)
        # All y < 280 -> fallback to last-5 points.
        left = [(100, 50), (100, 60), (100, 70)]
        right = [(900, 50), (900, 60), (900, 70)]
        res = d.analyze_lanes([left, right])
        assert res["status"] == DepartureDetector.CENTERED
        assert res["lane_center_x"] == pytest.approx(500.0)


# ---------------------------------------------------------------------------
# DepartureDetector — smoothing, events, summary
# ---------------------------------------------------------------------------
class TestSmoothingAndEvents:
    def test_smoothing_window_averages_offsets(self):
        """With window 2, a centered frame followed by a departing frame yields a
        smoothed offset = mean of the two, which can stay below threshold."""
        d = DepartureDetector(1000, 400, departure_threshold=0.4,
                              smoothing_window=2)
        # frame 1: offset 0.0 (centered)
        d.analyze_lanes([lane_at(100), lane_at(900)])
        # frame 2: raw offset +1.0; smoothed = mean(0.0, 1.0) = 0.5 > 0.4
        res = d.analyze_lanes([lane_at(100), lane_at(500)])
        assert res["offset"] == pytest.approx(0.5)
        assert res["status"] == DepartureDetector.RIGHT_DEPARTURE

    def test_smoothing_suppresses_single_noisy_frame(self):
        d = DepartureDetector(1000, 400, departure_threshold=0.6,
                              smoothing_window=2)
        d.analyze_lanes([lane_at(100), lane_at(900)])      # 0.0
        res = d.analyze_lanes([lane_at(100), lane_at(500)])  # raw 1.0, smoothed 0.5
        assert res["offset"] == pytest.approx(0.5)
        assert res["status"] == DepartureDetector.CENTERED  # 0.5 < 0.6

    def test_history_capped_at_window(self):
        d = DepartureDetector(1000, 400, smoothing_window=3)
        for _ in range(10):
            d.analyze_lanes([lane_at(100), lane_at(900)])
        assert len(d.offset_history) == 3

    def test_frame_index_increments_every_call(self):
        d = DepartureDetector(1000, 400)
        d.analyze_lanes([])
        d.analyze_lanes([lane_at(100), lane_at(900)])
        res = d.analyze_lanes([lane_at(100), lane_at(900)])
        assert res["frame_index"] == 3

    def test_event_logged_once_per_direction_run(self):
        """A departure event is recorded only when the direction changes, not
        for every frame of a sustained departure."""
        d = DepartureDetector(1000, 400, departure_threshold=0.15,
                              smoothing_window=1)
        for _ in range(3):
            d.analyze_lanes([lane_at(100), lane_at(500)])  # right, sustained
        events = d.get_departure_events()
        assert len(events) == 1
        assert events[0]["direction"] == DepartureDetector.RIGHT_DEPARTURE

    def test_direction_change_logs_new_event(self):
        d = DepartureDetector(1000, 400, departure_threshold=0.15,
                              smoothing_window=1)
        d.analyze_lanes([lane_at(100), lane_at(500)])  # right
        d.analyze_lanes([lane_at(500), lane_at(900)])  # left
        events = d.get_departure_events()
        assert len(events) == 2
        assert events[0]["direction"] == DepartureDetector.RIGHT_DEPARTURE
        assert events[1]["direction"] == DepartureDetector.LEFT_DEPARTURE

    def test_centered_logs_no_event(self):
        d = DepartureDetector(1000, 400, 0.15, 1)
        d.analyze_lanes([lane_at(100), lane_at(900)])
        assert d.get_departure_events() == []

    def test_summary_counts(self):
        d = DepartureDetector(1000, 400, departure_threshold=0.15,
                              smoothing_window=1)
        d.analyze_lanes([lane_at(100), lane_at(500)])  # right
        d.analyze_lanes([lane_at(500), lane_at(900)])  # left
        d.analyze_lanes([lane_at(100), lane_at(900)])  # centered
        summary = d.get_summary()
        assert summary["total_frames"] == 3
        assert summary["total_departures"] == 2
        assert summary["left_departures"] == 1
        assert summary["right_departures"] == 1
        assert len(summary["events"]) == 2

    def test_summary_empty_run(self):
        d = DepartureDetector(1000, 400)
        summary = d.get_summary()
        assert summary["total_frames"] == 0
        assert summary["total_departures"] == 0
        assert summary["events"] == []

    def test_get_departure_events_returns_copy(self):
        """Mutating the returned list must not corrupt internal state."""
        d = DepartureDetector(1000, 400, 0.15, 1)
        d.analyze_lanes([lane_at(100), lane_at(500)])
        events = d.get_departure_events()
        events.clear()
        assert len(d.get_departure_events()) == 1


# ---------------------------------------------------------------------------
# compute_scaled_radius
# ---------------------------------------------------------------------------
class TestComputeScaledRadius:
    def test_standard_resolution_returns_base(self):
        assert compute_scaled_radius(1280, 720) == 5

    def test_larger_resolution_scales_up(self):
        assert compute_scaled_radius(2560, 1440) == 10

    def test_smaller_resolution_scales_down(self):
        r = compute_scaled_radius(640, 360)
        assert r == 2  # 5 * 0.5 == 2.5 -> int 2

    def test_never_below_one(self):
        assert compute_scaled_radius(1, 1) >= 1

    def test_returns_int(self):
        assert isinstance(compute_scaled_radius(800, 600), int)
