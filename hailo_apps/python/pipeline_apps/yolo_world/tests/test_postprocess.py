"""Unit tests for YOLO World postprocess (pure numpy: grid decode + NMS)."""

import numpy as np
import pytest

from hailo_apps.python.pipeline_apps.yolo_world.postprocess import (
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
        _plant_detection(outs, stride=8, gy=40, gx=40, class_id=0, score=0.9)
        result = postprocess(outs, score_threshold=0.3)
        assert len(result) == 1
        det = result[0]
        assert det["class_id"] == 0
        assert det["score"] == pytest.approx(0.9, abs=1e-4)
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
        _plant_detection(outs, stride=8, gy=40, gx=40, class_id=0, score=0.9)
        _plant_detection(outs, stride=8, gy=40, gx=41, class_id=0, score=0.8)
        result = postprocess(outs, score_threshold=0.3, iou_threshold=0.5)
        assert len(result) == 1
        assert result[0]["score"] == pytest.approx(0.9, abs=1e-4)

    def test_different_classes_at_different_positions_both_kept(self):
        outs = _empty_outputs()
        _plant_detection(outs, stride=8, gy=10, gx=10, class_id=0, score=0.9)
        _plant_detection(outs, stride=8, gy=70, gx=70, class_id=5, score=0.85)
        result = postprocess(outs, score_threshold=0.3)
        class_ids = sorted(d["class_id"] for d in result)
        assert class_ids == [0, 5]

    def test_same_cell_multilabel_keeps_both_classes(self):
        """Multi-label: a single cell with two classes above threshold emits BOTH.
        (Regression for the person+can overlap bug — argmax would drop the can.)"""
        outs = _empty_outputs()
        _plant_detection(outs, stride=8, gy=40, gx=40, class_id=0, score=0.9)
        _plant_detection(outs, stride=8, gy=40, gx=40, class_id=5, score=0.85)
        result = postprocess(outs, score_threshold=0.3)
        assert len(result) == 2
        assert sorted(d["class_id"] for d in result) == [0, 5]

    def test_overlapping_objects_different_classes_both_detected(self):
        """A 'can' (class 1) inside a 'person' (class 0): the can's cell also has a
        high person score. Both must be detected — the can must not be argmax'd away."""
        outs = _empty_outputs()
        # Person: large box across many cells, high score over a region.
        for gy in range(30, 51):
            for gx in range(30, 51):
                outs["cls_8"][gy, gx, 0] = 0.85
                outs["reg_8"][gy, gx] = (30.0, 30.0, 30.0, 30.0)
        # Can: small object near the person's center; person also scores high here.
        outs["cls_8"][40, 40, 1] = 0.6   # can slightly lower than person's 0.85
        outs["reg_8"][40, 40] = (3.0, 3.0, 3.0, 3.0)
        result = postprocess(outs, score_threshold=0.3, iou_threshold=0.7)
        classes = {d["class_id"] for d in result}
        assert 0 in classes, "person should be detected"
        assert 1 in classes, "can should be detected even though person overlaps it"

    def test_num_classes_slicing(self):
        outs = _empty_outputs()
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
        outs = _empty_outputs()
        _plant_detection(outs, stride=8, gy=40, gx=40, class_id=0, score=0.9)
        outs_4d = {name: tensor[np.newaxis] for name, tensor in outs.items()}
        result = postprocess(outs_4d, score_threshold=0.3)
        assert len(result) == 1

    def test_malformed_tensor_count_returns_empty(self):
        outs = _empty_outputs()
        del outs["cls_32"]
        result = postprocess(outs)
        assert result == []

    def test_multi_scale_detections(self):
        outs = _empty_outputs()
        _plant_detection(outs, stride=8, gy=10, gx=10, class_id=0, score=0.9)
        _plant_detection(outs, stride=16, gy=5, gx=5, class_id=1, score=0.8)
        _plant_detection(outs, stride=32, gy=2, gx=2, class_id=2, score=0.7)
        result = postprocess(outs, score_threshold=0.3, iou_threshold=0.5)
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
            [0.0, 0.0, 1.0, 1.0],
            [0.0, 0.0, 1.0, 1.0],
        ])
        scores = np.array([0.5, 0.9])
        assert _nms(boxes, scores, 0.5) == [1]

    def test_non_overlapping_both_kept(self):
        boxes = np.array([
            [0.0, 0.0, 0.4, 0.4],
            [0.6, 0.6, 1.0, 1.0],
        ])
        scores = np.array([0.9, 0.8])
        assert sorted(_nms(boxes, scores, 0.5)) == [0, 1]

    def test_nested_box_suppressed_by_containment(self):
        # Small box fully inside a large box, large scores higher -> small dropped
        # even though IoU is low (intersection/union is small).
        boxes = np.array([
            [0.0, 0.0, 1.0, 1.0],   # large (whole plant)
            [0.4, 0.4, 0.6, 0.6],   # small part, fully inside
        ])
        scores = np.array([0.9, 0.7])
        assert _nms(boxes, scores, 0.7) == [0]

    def test_nested_low_iou_kept_without_containment(self):
        # Same geometry but containment disabled -> standard IoU keeps both.
        boxes = np.array([
            [0.0, 0.0, 1.0, 1.0],
            [0.4, 0.4, 0.6, 0.6],
        ])
        scores = np.array([0.9, 0.7])
        assert sorted(_nms(boxes, scores, 0.7, containment_threshold=1.01)) == [0, 1]

    def test_containing_box_survives_when_part_scores_higher(self):
        # If the small part scores higher, it's kept first; the large box is only
        # ~4% covered by the part, so containment doesn't drop the whole-object box.
        boxes = np.array([
            [0.0, 0.0, 1.0, 1.0],   # large
            [0.4, 0.4, 0.6, 0.6],   # small, higher score
        ])
        scores = np.array([0.7, 0.9])
        assert sorted(_nms(boxes, scores, 0.7)) == [0, 1]

    def test_iou_threshold_boundary(self):
        boxes = np.array([
            [0.0, 0.0, 1.0, 1.0],
            [0.5, 0.5, 1.5, 1.5],
        ])
        scores = np.array([0.9, 0.8])
        # IoU = 0.25 / 1.75 ≈ 0.143
        assert sorted(_nms(boxes, scores, 0.5)) == [0, 1]
        assert _nms(boxes, scores, 0.1) == [0]


class TestOnDeviceNMSDispatch:
    """The H8 HEF emits a single (1, C, max_dets, 5) tensor (NMS on-device).

    Postprocess must dispatch on output count: a single tensor goes through
    the score-filter-only path; six tensors keep the existing DFL+NMS path.
    """

    @staticmethod
    def _nms_output(rows_per_class):
        """Build a (1, 80, max_dets, 5) on-device-NMS tensor from a sparse map.

        ``rows_per_class`` is a dict ``cls_id -> [(x1,y1,x2,y2,score), ...]``.
        Within each class the rows are sorted descending by score (matches the
        on-device contract) and padded with zeros.
        """
        max_dets = max((len(v) for v in rows_per_class.values()), default=0) or 1
        arr = np.zeros((1, 80, max_dets, 5), dtype=np.float32)
        for cls_id, rows in rows_per_class.items():
            rows = sorted(rows, key=lambda r: -r[4])
            for i, row in enumerate(rows):
                arr[0, cls_id, i] = row
        return {"yolov8_nms_postprocess": arr}

    def test_single_tensor_route_returns_score_filtered_dets(self):
        out = self._nms_output({
            3: [(0.1, 0.1, 0.2, 0.2, 0.9), (0.3, 0.3, 0.4, 0.4, 0.4)],
            7: [(0.5, 0.5, 0.6, 0.6, 0.8)],
        })
        result = postprocess(out, score_threshold=0.5)
        assert len(result) == 2
        # sorted by score descending
        assert [d["class_id"] for d in result] == [3, 7]
        assert [round(d["score"], 2) for d in result] == [0.9, 0.8]
        # bboxes preserved
        assert result[0]["bbox"] == pytest.approx([0.1, 0.1, 0.2, 0.2])

    def test_single_tensor_threshold_filters_low_scores(self):
        out = self._nms_output({5: [(0.0, 0.0, 1.0, 1.0, 0.05)]})
        result = postprocess(out, score_threshold=0.5)
        assert result == []

    def test_single_tensor_respects_num_classes_cap(self):
        out = self._nms_output({3: [(0.1, 0.1, 0.2, 0.2, 0.9)],
                                79: [(0.5, 0.5, 0.6, 0.6, 0.9)]})
        # Only the first 4 classes are active; class 79's detection is sliced out.
        result = postprocess(out, score_threshold=0.5, num_classes=4)
        assert [d["class_id"] for d in result] == [3]

    def test_unrecognized_single_tensor_shape_returns_empty(self):
        result = postprocess({"weird": np.zeros((2, 3))}, score_threshold=0.5)
        assert result == []
