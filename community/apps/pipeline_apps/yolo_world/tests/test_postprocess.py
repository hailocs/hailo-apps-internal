"""Unit tests for YOLO World postprocess (pure numpy: grid decode + NMS)."""

import numpy as np
import pytest

from community.apps.pipeline_apps.yolo_world.postprocess import (
    IMAGE_SIZE,
    STRIDES,
    _nms,
    postprocess,
)


def _empty_outputs():
    """Build the 6 zero-filled tensors that postprocess() expects."""
    outs = {}
    for stride in STRIDES:
        hw = IMAGE_SIZE // stride
        outs[f"cls_{stride}"] = np.zeros((hw, hw, 80), dtype=np.float32)
        outs[f"reg_{stride}"] = np.zeros((hw, hw, 4), dtype=np.float32)
    return outs


def _plant_detection(outs, stride, gy, gx, class_id, score, reg_dists=(10.0, 10.0, 10.0, 10.0)):
    """Plant a single detection at grid (gy, gx) on the stride-`stride` head."""
    outs[f"cls_{stride}"][gy, gx, class_id] = score
    outs[f"reg_{stride}"][gy, gx] = reg_dists


class TestPostprocess:
    def test_empty_inputs_returns_empty_list(self):
        result = postprocess(_empty_outputs())
        assert result == []

    def test_single_detection_above_threshold(self):
        outs = _empty_outputs()
        # Plant a detection at center of the stride-8 head.
        _plant_detection(outs, stride=8, gy=40, gx=40, class_id=0, score=0.9)
        result = postprocess(outs, score_threshold=0.3)
        assert len(result) == 1
        det = result[0]
        assert det["class_id"] == 0
        assert det["score"] == pytest.approx(0.9, abs=1e-4)
        # bbox normalized [0,1]
        x1, y1, x2, y2 = det["bbox"]
        assert 0.0 <= x1 < x2 <= 1.0
        assert 0.0 <= y1 < y2 <= 1.0

    def test_threshold_filters_low_scores(self):
        outs = _empty_outputs()
        _plant_detection(outs, stride=8, gy=10, gx=10, class_id=0, score=0.2)
        result = postprocess(outs, score_threshold=0.3)
        assert result == []

    def test_two_overlapping_same_class_nms_dedups(self):
        outs = _empty_outputs()
        # Two detections at adjacent grid cells (same class) overlap heavily
        _plant_detection(outs, stride=8, gy=40, gx=40, class_id=0, score=0.9)
        _plant_detection(outs, stride=8, gy=40, gx=41, class_id=0, score=0.8)
        result = postprocess(outs, score_threshold=0.3, iou_threshold=0.5)
        assert len(result) == 1
        # The higher score wins
        assert result[0]["score"] == pytest.approx(0.9, abs=1e-4)

    def test_different_classes_at_different_positions_both_kept(self):
        outs = _empty_outputs()
        # Distinct spatial cells (no overlap) and distinct classes — both survive
        _plant_detection(outs, stride=8, gy=10, gx=10, class_id=0, score=0.9)
        _plant_detection(outs, stride=8, gy=70, gx=70, class_id=5, score=0.85)
        result = postprocess(outs, score_threshold=0.3)
        class_ids = sorted(d["class_id"] for d in result)
        assert class_ids == [0, 5]

    def test_same_cell_only_highest_class_kept(self):
        """YOLO World postprocess: per spatial cell, only argmax class is kept.
        Two classes at the same (gy, gx) collapse to the higher-scoring one."""
        outs = _empty_outputs()
        _plant_detection(outs, stride=8, gy=40, gx=40, class_id=0, score=0.9)
        _plant_detection(outs, stride=8, gy=40, gx=40, class_id=5, score=0.85)
        result = postprocess(outs, score_threshold=0.3)
        assert len(result) == 1
        assert result[0]["class_id"] == 0

    def test_num_classes_slicing(self):
        outs = _empty_outputs()
        # Plant a hit on class 50 but ask for only 10 classes — should be ignored
        _plant_detection(outs, stride=8, gy=10, gx=10, class_id=50, score=0.9)
        result = postprocess(outs, score_threshold=0.3, num_classes=10)
        assert result == []

    def test_sorted_by_score_descending(self):
        outs = _empty_outputs()
        _plant_detection(outs, stride=8, gy=10, gx=10, class_id=0, score=0.5)
        _plant_detection(outs, stride=8, gy=30, gx=30, class_id=1, score=0.9)
        _plant_detection(outs, stride=8, gy=50, gx=50, class_id=2, score=0.7)
        result = postprocess(outs, score_threshold=0.3)
        scores = [d["score"] for d in result]
        assert scores == sorted(scores, reverse=True)

    def test_handles_4d_batch_dim(self):
        # Same as test_single but with a leading batch dim
        outs = _empty_outputs()
        _plant_detection(outs, stride=8, gy=40, gx=40, class_id=0, score=0.9)
        # Add batch dim to each tensor
        outs_4d = {name: tensor[np.newaxis] for name, tensor in outs.items()}
        result = postprocess(outs_4d, score_threshold=0.3)
        assert len(result) == 1

    def test_malformed_tensor_count_returns_empty(self):
        # Only 2 cls tensors instead of 3 -> early return
        outs = _empty_outputs()
        del outs["cls_32"]
        result = postprocess(outs)
        assert result == []

    def test_multi_scale_detections(self):
        # Detections at all 3 scales
        outs = _empty_outputs()
        _plant_detection(outs, stride=8, gy=10, gx=10, class_id=0, score=0.9)
        _plant_detection(outs, stride=16, gy=5, gx=5, class_id=1, score=0.8)
        _plant_detection(outs, stride=32, gy=2, gx=2, class_id=2, score=0.7)
        result = postprocess(outs, score_threshold=0.3, iou_threshold=0.5)
        # All 3 are different classes so all survive NMS
        assert len(result) == 3


class TestNMS:
    def test_empty_boxes(self):
        assert _nms(np.zeros((0, 4)), np.zeros((0,)), 0.5) == []

    def test_single_box_kept(self):
        boxes = np.array([[0.0, 0.0, 1.0, 1.0]])
        scores = np.array([0.9])
        assert _nms(boxes, scores, 0.5) == [0]

    def test_full_overlap_kept_higher_score(self):
        boxes = np.array([
            [0.0, 0.0, 1.0, 1.0],   # box A
            [0.0, 0.0, 1.0, 1.0],   # box B (identical)
        ])
        scores = np.array([0.5, 0.9])
        keep = _nms(boxes, scores, 0.5)
        assert keep == [1]

    def test_non_overlapping_both_kept(self):
        boxes = np.array([
            [0.0, 0.0, 0.4, 0.4],
            [0.6, 0.6, 1.0, 1.0],
        ])
        scores = np.array([0.9, 0.8])
        keep = sorted(_nms(boxes, scores, 0.5))
        assert keep == [0, 1]

    def test_iou_threshold_boundary(self):
        # Two boxes with IoU ~0.33 (small overlap)
        boxes = np.array([
            [0.0, 0.0, 1.0, 1.0],
            [0.5, 0.5, 1.5, 1.5],   # intersect (0.5..1, 0.5..1) area 0.25
        ])
        # IoU = 0.25 / (1 + 1 - 0.25) = 0.143
        scores = np.array([0.9, 0.8])
        # At threshold 0.5, both should survive (0.143 < 0.5)
        keep_low = sorted(_nms(boxes, scores, 0.5))
        assert keep_low == [0, 1]
        # At threshold 0.1, second is suppressed (0.143 > 0.1)
        keep_high = _nms(boxes, scores, 0.1)
        assert keep_high == [0]
