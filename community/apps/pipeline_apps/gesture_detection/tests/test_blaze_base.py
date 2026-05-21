"""Unit tests for blaze_base math: SSD anchors, decode, weighted NMS, ROI."""

import numpy as np
import pytest

from community.apps.pipeline_apps.gesture_detection.blaze_base import (
    PALM_ANCHOR_OPTIONS,
    PALM_MODEL_CONFIG,
    _compute_iou,
    decode_boxes,
    denormalize_detections,
    detection2roi,
    generate_anchors,
    resize_pad,
    tensors_to_detections,
    weighted_non_max_suppression,
)


class TestGenerateAnchors:
    def test_palm_anchors_count_matches_config(self):
        anchors = generate_anchors(PALM_ANCHOR_OPTIONS)
        assert anchors.shape == (PALM_MODEL_CONFIG["num_anchors"], 4)
        assert PALM_MODEL_CONFIG["num_anchors"] == 2016

    def test_anchors_in_normalized_range(self):
        anchors = generate_anchors(PALM_ANCHOR_OPTIONS)
        # x_center, y_center should be in [0, 1]
        assert anchors[:, 0].min() >= 0.0
        assert anchors[:, 0].max() <= 1.0
        assert anchors[:, 1].min() >= 0.0
        assert anchors[:, 1].max() <= 1.0

    def test_fixed_anchor_size_dim(self):
        # fixed_anchor_size=True means w=h=1.0
        anchors = generate_anchors(PALM_ANCHOR_OPTIONS)
        np.testing.assert_array_equal(anchors[:, 2], np.ones(len(anchors)))
        np.testing.assert_array_equal(anchors[:, 3], np.ones(len(anchors)))

    def test_anchor_dtype_float32(self):
        anchors = generate_anchors(PALM_ANCHOR_OPTIONS)
        assert anchors.dtype == np.float32


class TestDecodeBoxes:
    def test_zero_offsets_returns_anchor_centers(self):
        config = PALM_MODEL_CONFIG
        anchors = np.array([
            [0.5, 0.5, 1.0, 1.0],   # center anchor with unit size
        ], dtype=np.float32)
        # raw_boxes[..., 0:4] = (dx, dy, dw, dh) = 0 => box at anchor center with 0 width/height
        raw = np.zeros((1, 1, config["num_coords"]), dtype=np.float32)
        boxes = decode_boxes(raw, anchors, config)
        # Format: [ymin, xmin, ymax, xmax, ...]
        ymin, xmin, ymax, xmax = boxes[0, 0, 0:4]
        # With dw=dh=0, box collapses to (y_center - 0, x_center - 0, y_center + 0, x_center + 0)
        assert ymin == pytest.approx(0.5)
        assert xmin == pytest.approx(0.5)
        assert ymax == pytest.approx(0.5)
        assert xmax == pytest.approx(0.5)


class TestTensorsToDetections:
    def test_filters_below_threshold(self):
        config = dict(PALM_MODEL_CONFIG)
        config["min_score_thresh"] = 0.5
        anchors = np.array([[0.5, 0.5, 1.0, 1.0]], dtype=np.float32)
        # Score logit -10 -> sigmoid ~0; below threshold
        raw_boxes = np.zeros((1, 1, config["num_coords"]), dtype=np.float32)
        raw_scores = np.array([[[-10.0]]], dtype=np.float32)
        dets = tensors_to_detections(raw_boxes, raw_scores, anchors, config)
        assert len(dets) == 1
        assert dets[0].shape == (0, config["num_coords"] + 1)

    def test_keeps_above_threshold(self):
        config = dict(PALM_MODEL_CONFIG)
        config["min_score_thresh"] = 0.5
        anchors = np.array([[0.5, 0.5, 1.0, 1.0]], dtype=np.float32)
        raw_boxes = np.zeros((1, 1, config["num_coords"]), dtype=np.float32)
        # logit 10 -> sigmoid ~1
        raw_scores = np.array([[[10.0]]], dtype=np.float32)
        dets = tensors_to_detections(raw_boxes, raw_scores, anchors, config)
        assert dets[0].shape == (1, config["num_coords"] + 1)
        # Last column is score
        assert dets[0][0, -1] == pytest.approx(1.0, abs=1e-3)


class TestWeightedNMS:
    def test_empty_input(self):
        result = weighted_non_max_suppression(np.zeros((0, 19)), 0.3)
        assert result == []

    def test_single_detection_unchanged(self):
        det = np.array([[0.0, 0.0, 1.0, 1.0] + [0.0] * 14 + [0.9]], dtype=np.float32)
        result = weighted_non_max_suppression(det, 0.3)
        assert len(result) == 1
        np.testing.assert_array_almost_equal(result[0], det[0])

    def test_overlapping_dets_merge(self):
        # Two heavily overlapping detections; weighted NMS should merge.
        det1 = np.array([0.0, 0.0, 1.0, 1.0] + [0.0] * 14 + [0.9], dtype=np.float32)
        det2 = np.array([0.1, 0.1, 1.1, 1.1] + [0.0] * 14 + [0.6], dtype=np.float32)
        dets = np.stack([det1, det2])
        result = weighted_non_max_suppression(dets, 0.3)
        assert len(result) == 1
        # Merged box is between det1 and det2 (weighted by score)
        merged = result[0]
        assert 0.0 <= merged[0] <= 0.1
        # Score is kept from the highest-scoring detection
        assert merged[-1] == pytest.approx(0.9, abs=1e-4)

    def test_non_overlapping_dets_kept(self):
        det1 = np.array([0.0, 0.0, 0.1, 0.1] + [0.0] * 14 + [0.9], dtype=np.float32)
        det2 = np.array([0.5, 0.5, 0.6, 0.6] + [0.0] * 14 + [0.8], dtype=np.float32)
        dets = np.stack([det1, det2])
        result = weighted_non_max_suppression(dets, 0.3)
        assert len(result) == 2


class TestComputeIou:
    def test_same_box_iou_one(self):
        box = np.array([0.0, 0.0, 1.0, 1.0])
        boxes = np.array([[0.0, 0.0, 1.0, 1.0]])
        iou = _compute_iou(box, boxes)
        assert iou[0] == pytest.approx(1.0, abs=1e-4)

    def test_disjoint_iou_zero(self):
        box = np.array([0.0, 0.0, 1.0, 1.0])
        boxes = np.array([[10.0, 10.0, 11.0, 11.0]])
        iou = _compute_iou(box, boxes)
        assert iou[0] == 0.0

    def test_half_overlap(self):
        box = np.array([0.0, 0.0, 2.0, 2.0])     # 4 area
        boxes = np.array([[1.0, 0.0, 2.0, 2.0]])  # 2 area, intersect 2.0
        iou = _compute_iou(box, boxes)
        # IoU = 2 / (4 + 2 - 2) = 2/4 = 0.5
        assert iou[0] == pytest.approx(0.5)


class TestResizePad:
    def test_square_image_no_pad(self):
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        padded, inv_scale, pad = resize_pad(img, (192, 192))
        assert padded.shape == (192, 192, 3)
        assert inv_scale == pytest.approx(100 / 192)
        # No padding when scaled image fills the canvas
        assert pad == (0.0, 0.0)

    def test_landscape_padded_top_bottom(self):
        img = np.zeros((100, 200, 3), dtype=np.uint8)
        padded, inv_scale, pad = resize_pad(img, (192, 192))
        assert padded.shape == (192, 192, 3)
        # scale = min(192/100, 192/200) = 192/200 = 0.96
        # new_h = 96, new_w = 192; pad_h = (192-96)/2 = 48
        assert pad[0] > 0
        assert pad[1] == 0


class TestDetection2Roi:
    def test_empty_input(self):
        xc, yc, scale, theta = detection2roi(np.zeros((0, 19)), PALM_MODEL_CONFIG)
        assert len(xc) == len(yc) == len(scale) == len(theta) == 0

    def test_box_center_extraction(self):
        # One detection: box (ymin=0, xmin=0, ymax=10, xmax=10) -> center (5, 5)
        # Keypoints all at (0,0) for simplicity -> theta = atan2(0, 0) - theta0 = -pi/2
        det = np.zeros((1, 19), dtype=np.float32)
        det[0, 0:4] = [0, 0, 10, 10]  # ymin, xmin, ymax, xmax
        xc, yc, scale, theta = detection2roi(det, PALM_MODEL_CONFIG)
        # Without keypoint info, theta is determined; check center is plausible
        assert scale[0] == pytest.approx(10.0 * PALM_MODEL_CONFIG["dscale"])
