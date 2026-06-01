"""Unit tests for the temporal DetectionStabilizer (hysteresis/coast/smooth)."""

from hailo_apps.python.pipeline_apps.yolo_world.detection_stabilizer import (
    DetectionStabilizer,
    _iou,
)

BOX = [0.4, 0.4, 0.6, 0.6]


def _det(score, bbox=BOX, cls=0):
    return {"bbox": list(bbox), "class_id": cls, "score": score}


class TestConfirmHysteresis:
    def test_single_frame_below_min_hits_not_shown(self):
        s = DetectionStabilizer(confirm_thr=0.3, min_hits=2)
        assert s.update([_det(0.9)]) == []  # 1 hit < min_hits

    def test_confirms_after_min_hits(self):
        s = DetectionStabilizer(confirm_thr=0.3, min_hits=2)
        s.update([_det(0.9)])
        out = s.update([_det(0.9)])
        assert len(out) == 1 and out[0]["class_id"] == 0

    def test_weak_only_never_confirms(self):
        s = DetectionStabilizer(confirm_thr=0.3, sustain_thr=0.15, min_hits=1)
        for _ in range(5):
            out = s.update([_det(0.2)])  # above sustain, below confirm
        assert out == []


class TestCoasting:
    def test_track_survives_dropped_frames(self):
        s = DetectionStabilizer(confirm_thr=0.3, min_hits=2, coast_frames=5)
        s.update([_det(0.9)]); s.update([_det(0.9)])  # confirmed
        # now drop detections for 4 frames — still emitted (coasting)
        for _ in range(4):
            out = s.update([])
            assert len(out) == 1, "confirmed track should coast through dropped frames"

    def test_track_expires_after_coast_window(self):
        s = DetectionStabilizer(confirm_thr=0.3, min_hits=2, coast_frames=3)
        s.update([_det(0.9)]); s.update([_det(0.9)])
        for _ in range(3):
            s.update([])           # within coast
        out = s.update([])         # 4th miss > coast_frames -> gone
        assert out == []


class TestSmoothing:
    def test_box_is_ema_smoothed(self):
        s = DetectionStabilizer(confirm_thr=0.3, min_hits=1, box_alpha=0.5)
        # Boxes overlap enough (IoU >= assoc_iou) to associate, then shift slightly.
        s.update([_det(0.9, bbox=[0.40, 0.40, 0.60, 0.60])])
        out = s.update([_det(0.9, bbox=[0.44, 0.40, 0.64, 0.60])])
        # EMA(0.5) on x1: 0.5*0.44 + 0.5*0.40 = 0.42 (lags the new box)
        assert abs(out[0]["bbox"][0] - 0.42) < 1e-6


class TestClassAware:
    def test_overlapping_different_classes_tracked_separately(self):
        s = DetectionStabilizer(confirm_thr=0.3, min_hits=1)
        s.update([_det(0.9, cls=0), _det(0.8, cls=1)])
        out = s.update([_det(0.9, cls=0), _det(0.8, cls=1)])
        assert sorted(d["class_id"] for d in out) == [0, 1]


class TestReset:
    def test_reset_clears_tracks(self):
        s = DetectionStabilizer(confirm_thr=0.3, min_hits=1)
        s.update([_det(0.9)])
        s.reset()
        assert s.update([]) == []


def test_iou_basic():
    assert abs(_iou([0, 0, 1, 1], [0, 0, 1, 1]) - 1.0) < 1e-6
    assert _iou([0, 0, 1, 1], [2, 2, 3, 3]) == 0.0
