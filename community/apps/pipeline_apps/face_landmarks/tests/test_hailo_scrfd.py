"""Unit tests for SCRFD post-processing math (pure-numpy static methods).

Only static methods of HailoScrfd are tested — the constructor requires a
real HEF file and a Hailo device, which we skip.
"""

import sys
from unittest.mock import MagicMock

import numpy as np
import pytest

# hailo_platform import would fail without HailoRT; stub it so module import works.
for mod_name in ["hailo_platform"]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

from community.apps.pipeline_apps.face_landmarks.hailo_scrfd import HailoScrfd


class TestDistance2Bbox:
    def test_zero_distances_returns_centers_as_degenerate_box(self):
        centers = np.array([[100.0, 200.0]])
        distance = np.zeros((1, 4))
        boxes = HailoScrfd._distance2bbox(centers, distance)
        assert boxes.shape == (1, 4)
        np.testing.assert_array_equal(boxes[0], [100.0, 200.0, 100.0, 200.0])

    def test_uniform_distances(self):
        centers = np.array([[100.0, 200.0]])
        distance = np.array([[10.0, 20.0, 30.0, 40.0]])  # left, top, right, bottom
        boxes = HailoScrfd._distance2bbox(centers, distance)
        x1, y1, x2, y2 = boxes[0]
        assert x1 == 90.0   # 100 - 10
        assert y1 == 180.0  # 200 - 20
        assert x2 == 130.0  # 100 + 30
        assert y2 == 240.0  # 200 + 40

    def test_batch_of_boxes(self):
        centers = np.array([[100.0, 200.0], [50.0, 50.0]])
        distance = np.array([[10.0, 10.0, 10.0, 10.0], [5.0, 5.0, 5.0, 5.0]])
        boxes = HailoScrfd._distance2bbox(centers, distance)
        assert boxes.shape == (2, 4)
        np.testing.assert_array_equal(boxes[0], [90, 190, 110, 210])
        np.testing.assert_array_equal(boxes[1], [45, 45, 55, 55])


class TestDistance2Kps:
    def test_zero_offsets_keypoints_at_center(self):
        centers = np.array([[100.0, 200.0]])
        distance = np.zeros((1, 10))
        kps = HailoScrfd._distance2kps(centers, distance)
        assert kps.shape == (1, 5, 2)
        np.testing.assert_array_equal(kps[0], np.tile([100.0, 200.0], (5, 1)))

    def test_each_keypoint_offset_independently(self):
        centers = np.array([[100.0, 200.0]])
        # 5 keypoints with offsets (i*1, i*2)
        distance = np.array([[0, 0, 1, 2, 2, 4, 3, 6, 4, 8]], dtype=np.float32)
        kps = HailoScrfd._distance2kps(centers, distance)
        # kp_i = center + (i, 2i)
        expected = np.array([
            [100, 200],
            [101, 202],
            [102, 204],
            [103, 206],
            [104, 208],
        ], dtype=np.float32)
        np.testing.assert_array_equal(kps[0], expected)


class TestSCRFDNms:
    def test_empty_input(self):
        result = HailoScrfd._nms(np.zeros((0, 4)), np.zeros((0,)), 0.5)
        assert result.shape == (0,)
        assert result.dtype == np.int64

    def test_single_box_kept(self):
        boxes = np.array([[0, 0, 10, 10]])
        scores = np.array([0.9])
        result = HailoScrfd._nms(boxes, scores, 0.5)
        assert list(result) == [0]

    def test_overlapping_higher_score_kept(self):
        boxes = np.array([
            [0, 0, 10, 10],
            [1, 1, 11, 11],   # heavy overlap
        ])
        scores = np.array([0.5, 0.9])
        result = HailoScrfd._nms(boxes, scores, 0.3)
        assert list(result) == [1]   # higher score kept

    def test_non_overlapping_both_kept(self):
        boxes = np.array([
            [0, 0, 10, 10],
            [100, 100, 110, 110],
        ])
        scores = np.array([0.9, 0.8])
        result = HailoScrfd._nms(boxes, scores, 0.5)
        assert sorted(result.tolist()) == [0, 1]

    def test_returns_in_descending_score_order(self):
        boxes = np.array([
            [0, 0, 5, 5],
            [50, 50, 55, 55],
            [200, 200, 205, 205],
        ])
        scores = np.array([0.5, 0.9, 0.7])
        result = HailoScrfd._nms(boxes, scores, 0.5)
        # order should match descending score: indices 1, 2, 0
        assert list(result) == [1, 2, 0]


class TestSCRFDConstants:
    def test_input_size(self):
        assert HailoScrfd.INPUT_SIZE == 640

    def test_strides(self):
        assert HailoScrfd.FEAT_STRIDES == [8, 16, 32]

    def test_num_anchors(self):
        assert HailoScrfd.NUM_ANCHORS == 2
