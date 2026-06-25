"""Pure-Python unit tests for the traffic_light_detector post-processing module.

These tests exercise the HSV color classifier, the COCO-class detection filter,
the score-threshold / top-K box logic, and the letterbox-padding box math.
No Hailo device, inference, or network access is required.
"""

import sys
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest

pytestmark = pytest.mark.community

# HailoRT is not available on the test machine. The post-process module only
# imports it transitively via hailo_logger; stub the submodules so the import
# of the app module under test succeeds.
for _mod_name in [
    "hailo_platform",
    "hailo_platform.pyhailort",
    "hailo_platform.pyhailort.pyhailort",
]:
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = MagicMock()

from community.apps.standalone_apps.traffic_light_detector.traffic_light_post_process import (
    COLOR_RANGES,
    STATE_COLORS,
    TRAFFIC_LIGHT_CLASS_ID,
    classify_traffic_light_state,
    denormalize_and_rm_pad,
    extract_detections,
    inference_result_handler,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def solid_bgr_crop(bgr, h=20, w=20):
    """Build an h x w crop filled with a single BGR color."""
    crop = np.empty((h, w, 3), dtype=np.uint8)
    crop[:, :] = bgr
    return crop


def hue_of(bgr):
    """Return the OpenCV HSV hue (0-179) for a single BGR pixel."""
    px = np.array([[list(bgr)]], dtype=np.uint8)
    return int(cv2.cvtColor(px, cv2.COLOR_BGR2HSV)[0, 0, 0])


# --------------------------------------------------------------------------- #
# Color classification — the core logic
# --------------------------------------------------------------------------- #
class TestClassifyTrafficLightState:
    def test_pure_red(self):
        # BGR (0,0,255) -> HSV hue 0 -> red.
        assert classify_traffic_light_state(solid_bgr_crop((0, 0, 255))) == "red"

    def test_pure_red_upper_wrap(self):
        # Red also wraps around at the top of the hue circle (H~170).
        # Pick a BGR that lands in the upper red range [160-180].
        crop = solid_bgr_crop((40, 0, 255))  # slightly magenta-red
        assert hue_of((40, 0, 255)) >= 160
        assert classify_traffic_light_state(crop) == "red"

    def test_pure_green(self):
        # BGR (0,255,0) -> HSV hue 60 -> green.
        assert classify_traffic_light_state(solid_bgr_crop((0, 255, 0))) == "green"

    def test_pure_yellow(self):
        # BGR (0,255,255) -> HSV hue 30 -> yellow.
        assert classify_traffic_light_state(solid_bgr_crop((0, 255, 255))) == "yellow"

    @pytest.mark.parametrize("bgr", [(0, 90, 255), (0, 110, 255), (0, 130, 255)])
    def test_amber_orange_is_yellow_not_unknown(self, bgr):
        """Regression: the H=10-15 orange/amber gap.

        Before the fix, yellow's lower bound did not reach down to H=10, so
        amber/orange lights (hue ~11-15) matched no range and returned
        "unknown". The fix extended yellow's lower bound to H=10. These hues
        must now classify as "yellow" and never "unknown".
        """
        h = hue_of(bgr)
        assert 10 <= h <= 15, f"test fixture drifted: hue={h}"
        state = classify_traffic_light_state(solid_bgr_crop(bgr))
        assert state != "unknown"
        assert state == "yellow"

    def test_hue_just_below_yellow_floor_is_red(self):
        # Hue 7 is below the yellow floor (10) but inside red upper (<=10).
        bgr = (0, 60, 255)
        assert hue_of(bgr) < 10
        assert classify_traffic_light_state(solid_bgr_crop(bgr)) == "red"

    def test_gray_crop_is_unknown(self):
        # Neutral gray has near-zero saturation -> matches no color range.
        assert classify_traffic_light_state(solid_bgr_crop((128, 128, 128))) == "unknown"

    def test_black_crop_is_unknown(self):
        assert classify_traffic_light_state(solid_bgr_crop((0, 0, 0))) == "unknown"

    def test_dim_color_below_value_floor_is_unknown(self):
        # Correct hue but value/saturation below the 100 floor -> no match.
        # A very dark red (V well under 100).
        dark_red = solid_bgr_crop((0, 0, 40))
        assert classify_traffic_light_state(dark_red) == "unknown"

    def test_below_min_pixel_fraction_is_unknown(self):
        # Only ~1% of pixels are red (< 3% threshold) -> unknown.
        crop = solid_bgr_crop((128, 128, 128), h=100, w=100)  # gray background
        crop[0, 0:80] = (0, 0, 255)  # 80 red px out of 10000 = 0.8%
        assert classify_traffic_light_state(crop) == "unknown"

    def test_above_min_pixel_fraction_classifies(self):
        # ~10% red pixels (>3%) -> red.
        crop = solid_bgr_crop((128, 128, 128), h=100, w=100)
        crop[0:10, :] = (0, 0, 255)  # 1000 red px = 10%
        assert classify_traffic_light_state(crop) == "red"

    def test_dominant_color_wins(self):
        # Mostly green, a sliver of red -> green should dominate.
        crop = solid_bgr_crop((0, 255, 0), h=40, w=40)
        crop[0:2, :] = (0, 0, 255)
        assert classify_traffic_light_state(crop) == "green"

    # --- Edge cases: degenerate crop dimensions --- #
    def test_empty_crop_is_unknown(self):
        assert classify_traffic_light_state(np.empty((0, 0, 3), dtype=np.uint8)) == "unknown"

    def test_zero_height_crop_is_unknown(self):
        assert classify_traffic_light_state(np.empty((0, 10, 3), dtype=np.uint8)) == "unknown"

    def test_zero_width_crop_is_unknown(self):
        assert classify_traffic_light_state(np.empty((10, 0, 3), dtype=np.uint8)) == "unknown"

    def test_too_small_crop_is_unknown(self):
        # Below the 4x4 minimum guard.
        assert classify_traffic_light_state(solid_bgr_crop((0, 0, 255), h=3, w=3)) == "unknown"

    def test_minimum_valid_crop_classifies(self):
        # Exactly 4x4 is the smallest accepted size.
        assert classify_traffic_light_state(solid_bgr_crop((0, 0, 255), h=4, w=4)) == "red"


# --------------------------------------------------------------------------- #
# Color-range / state-color tables
# --------------------------------------------------------------------------- #
class TestColorTables:
    def test_color_ranges_cover_amber_gap(self):
        # Yellow lower bound must reach down to H=10 (the closed gap).
        yellow_lows = [r["lower"][0] for r in COLOR_RANGES["yellow"]]
        assert min(yellow_lows) == 10

    def test_red_has_two_wraparound_ranges(self):
        assert len(COLOR_RANGES["red"]) == 2

    def test_state_colors_have_all_states(self):
        assert set(STATE_COLORS) == {"red", "yellow", "green", "unknown"}

    def test_traffic_light_class_id_is_coco_9(self):
        assert TRAFFIC_LIGHT_CLASS_ID == 9


# --------------------------------------------------------------------------- #
# denormalize_and_rm_pad — box math
# --------------------------------------------------------------------------- #
class TestDenormalizeAndRmPad:
    def test_square_image_no_padding(self):
        # Square image: size == height == width, no padding applied.
        # Normalized box [x1,y1,x2,y2] -> returns [ymin,xmin,ymax,xmax].
        box = [0.1, 0.2, 0.5, 0.6]
        out = denormalize_and_rm_pad(box, size=100, padding_length=0,
                                     input_height=100, input_width=100)
        # scaled: x1=10,y1=20,x2=50,y2=60 -> [y1,x1,y2,x2] = [20,10,60,50]
        assert out == [20, 10, 60, 50]

    def test_landscape_removes_y_padding(self):
        # Wider than tall: input_width != size, so y-coords get padding removed.
        box = [0.1, 0.2, 0.5, 0.6]
        out = denormalize_and_rm_pad(box, size=200, padding_length=25,
                                     input_height=150, input_width=200)
        # scaled: x1=20,y1=40,x2=100,y2=120
        # i=1 (y1): width(200)==size -> NOT removed; i=3 (y2) same.
        # i=0 (x1): height(150)!=size -> 20-25=-5; i=2 (x2): 100-25=75
        # returns [y1, x1, y2, x2] = [40, -5, 120, 75]
        assert out == [40, -5, 120, 75]

    def test_returns_four_coords(self):
        out = denormalize_and_rm_pad([0.0, 0.0, 1.0, 1.0], 50, 0, 50, 50)
        assert len(out) == 4


# --------------------------------------------------------------------------- #
# extract_detections — filtering / threshold / top-K
# --------------------------------------------------------------------------- #
def make_detections(per_class):
    """Build a YOLOv8-style list-of-arrays-per-class.

    `per_class` maps class_id -> list of [x1,y1,x2,y2,score]. Classes not
    present get an empty array. The list is padded to cover the max class id.
    """
    max_id = max(per_class) if per_class else 0
    out = []
    for cid in range(max_id + 1):
        rows = per_class.get(cid, [])
        out.append(np.array(rows, dtype=np.float32).reshape(-1, 5)
                   if rows else np.empty((0, 5), dtype=np.float32))
    return out


CONFIG = {"visualization_params": {"score_thres": 0.3, "max_boxes_to_draw": 100,
                                    "traffic_light_class_id": 9}}


class TestExtractDetections:
    def setup_method(self):
        self.image = np.zeros((100, 100, 3), dtype=np.uint8)  # square -> no padding

    def test_keeps_only_traffic_light_class(self):
        dets = make_detections({
            0: [[0.1, 0.1, 0.2, 0.2, 0.9]],   # person (ignored)
            9: [[0.1, 0.1, 0.2, 0.2, 0.8]],   # traffic light (kept)
        })
        res = extract_detections(self.image, dets, CONFIG)
        assert res["num_detections"] == 1
        assert res["detection_classes"] == [9]

    def test_no_detections(self):
        dets = make_detections({0: [[0.1, 0.1, 0.2, 0.2, 0.9]]})  # only non-TL class
        res = extract_detections(self.image, dets, CONFIG)
        assert res["num_detections"] == 0
        assert res["detection_boxes"] == []
        assert res["detection_scores"] == []
        assert res["detection_classes"] == []

    def test_completely_empty_input(self):
        res = extract_detections(self.image, [], CONFIG)
        assert res["num_detections"] == 0

    def test_below_threshold_dropped(self):
        dets = make_detections({9: [[0.1, 0.1, 0.2, 0.2, 0.2]]})  # 0.2 < 0.3
        res = extract_detections(self.image, dets, CONFIG)
        assert res["num_detections"] == 0

    def test_at_threshold_kept(self):
        # score == threshold passes (>=).
        dets = make_detections({9: [[0.1, 0.1, 0.2, 0.2, 0.3]]})
        res = extract_detections(self.image, dets, CONFIG)
        assert res["num_detections"] == 1

    def test_sorted_by_score_descending(self):
        dets = make_detections({9: [
            [0.1, 0.1, 0.2, 0.2, 0.4],
            [0.3, 0.3, 0.4, 0.4, 0.95],
            [0.5, 0.5, 0.6, 0.6, 0.7],
        ]})
        res = extract_detections(self.image, dets, CONFIG)
        assert res["detection_scores"] == pytest.approx([0.95, 0.7, 0.4], abs=1e-5)

    def test_max_boxes_truncates(self):
        rows = [[0.1, 0.1, 0.2, 0.2, 0.5 + i * 0.001] for i in range(10)]
        dets = make_detections({9: rows})
        cfg = {"visualization_params": {"score_thres": 0.3, "max_boxes_to_draw": 3,
                                        "traffic_light_class_id": 9}}
        res = extract_detections(self.image, dets, cfg)
        assert res["num_detections"] == 3

    def test_custom_class_id_from_config(self):
        cfg = {"visualization_params": {"score_thres": 0.3, "max_boxes_to_draw": 100,
                                        "traffic_light_class_id": 2}}
        dets = make_detections({2: [[0.1, 0.1, 0.2, 0.2, 0.8]],
                                9: [[0.1, 0.1, 0.2, 0.2, 0.8]]})
        res = extract_detections(self.image, dets, cfg)
        assert res["num_detections"] == 1
        assert res["detection_classes"] == [2]

    def test_defaults_when_config_missing_params(self):
        # Empty config -> falls back to score_thres=0.3, class id=9.
        dets = make_detections({9: [[0.1, 0.1, 0.2, 0.2, 0.5]]})
        res = extract_detections(self.image, dets, {})
        assert res["num_detections"] == 1

    def test_result_keys_present(self):
        res = extract_detections(self.image, [], CONFIG)
        assert set(res) == {"detection_boxes", "detection_classes",
                            "detection_scores", "num_detections"}


# --------------------------------------------------------------------------- #
# inference_result_handler — end-to-end on a synthetic frame
# --------------------------------------------------------------------------- #
class TestInferenceResultHandler:
    def _frame_with_red_light(self):
        # 100x100 square frame, a red patch in the box region [10:30, 10:30].
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        frame[10:30, 10:30] = (0, 0, 255)  # BGR red
        return frame

    def test_returns_same_frame_object(self):
        frame = self._frame_with_red_light()
        # Box covering the red patch: normalized [x1,y1,x2,y2] on 100px image.
        dets = make_detections({9: [[0.10, 0.10, 0.30, 0.30, 0.9]]})
        out = inference_result_handler(frame, dets, labels=[], config_data=CONFIG)
        assert out is frame  # drawn in place
        assert out.shape == (100, 100, 3)

    def test_no_detections_leaves_frame_unannotated(self):
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        dets = make_detections({0: [[0.1, 0.1, 0.2, 0.2, 0.9]]})  # non-TL only
        out = inference_result_handler(frame, dets, labels=[], config_data=CONFIG)
        # No traffic lights -> nothing drawn -> frame stays all-zero.
        assert not out.any()

    def test_json_summary_collected_for_red_light(self):
        frame = self._frame_with_red_light()
        dets = make_detections({9: [[0.10, 0.10, 0.30, 0.30, 0.87]]})
        summaries = []
        counter = [0]
        inference_result_handler(frame, dets, labels=[], config_data=CONFIG,
                                 frame_summaries=summaries, frame_counter=counter)
        assert counter[0] == 1
        assert len(summaries) == 1
        entry = summaries[0]
        assert entry["frame"] == 0
        assert len(entry["traffic_lights"]) == 1
        light = entry["traffic_lights"][0]
        assert light["state"] == "red"
        assert light["confidence"] == pytest.approx(0.87, abs=1e-3)
        assert len(light["bbox"]) == 4

    def test_json_summary_skips_empty_frames(self):
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        dets = make_detections({0: [[0.1, 0.1, 0.2, 0.2, 0.9]]})  # no TL
        summaries = []
        counter = [0]
        inference_result_handler(frame, dets, labels=[], config_data=CONFIG,
                                 frame_summaries=summaries, frame_counter=counter)
        # Counter still advances, but no summary appended for an empty frame.
        assert counter[0] == 1
        assert summaries == []

    def test_malformed_crop_dims_do_not_crash(self):
        # Degenerate box (zero-area / inverted) -> empty crop -> "unknown",
        # and the handler must not raise.
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        # x1==x2 and y1==y2 -> zero-area box after denorm.
        dets = make_detections({9: [[0.5, 0.5, 0.5, 0.5, 0.9]]})
        out = inference_result_handler(frame, dets, labels=[], config_data=CONFIG)
        assert out.shape == (100, 100, 3)
