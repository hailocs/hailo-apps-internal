"""Tracker adapters surface a Kalman-filtered tlwh in normalized [0..1] coords.

Task 7 of the post-merge plan: feed the controller from the KF-filtered bbox
state inside ByteTracker instead of the raw post-NMS detection. These tests
lock the contract: filtered_tlwh comes back in normalized frame fractions
(matching the HailoROI bbox space the rest of the app uses) and is smoother
than the raw input across frames with injected jitter.
"""

import numpy as np

from drone_follow.pipeline_adapter.byte_tracker import ByteTrackerAdapter


def _det(x, y, w, h, score=0.9, scale=1000.0):
    """Build a single Nx5 detection row in tracker-input units (SCALE=1000)."""
    return np.array([x*scale, y*scale, (x+w)*scale, (y+h)*scale, score], dtype=np.float32)


def test_byte_tracker_adapter_returns_normalized_filtered_tlwh():
    tracker = ByteTrackerAdapter(track_thresh=0.3, match_thresh=0.8,
                                 track_buffer=30, frame_rate=30)

    # Inject a stable detection across two frames so the KF activates and matches.
    dets = np.stack([_det(0.40, 0.40, 0.20, 0.30)])
    tracker.update(dets)
    tracker.update(dets)

    results = tracker.update(dets)
    assert len(results) >= 1
    t = results[0]
    assert t.filtered_tlwh, "filtered_tlwh must be populated"
    fx, fy, fw, fh = t.filtered_tlwh
    # Filtered values are in normalized [0..1] coords, close to the raw input.
    assert 0.35 <= fx <= 0.45, f"fx={fx}"
    assert 0.35 <= fy <= 0.45, f"fy={fy}"
    assert 0.18 <= fw <= 0.22, f"fw={fw}"
    assert 0.27 <= fh <= 0.33, f"fh={fh}"


def test_filtered_height_smoother_than_raw():
    """Inject jittery raw bbox heights; filtered fh variance < raw variance.

    Uses moderate jitter (~10% bbox-height noise around a 0.30 mean) so the
    track survives the IoU match threshold across frames. Heavier jitter
    breaks association and isn't a useful KF-smoothness probe.
    """
    tracker = ByteTrackerAdapter(track_thresh=0.3, match_thresh=0.8,
                                 track_buffer=30, frame_rate=30)

    raw_h = [0.30, 0.27, 0.33, 0.26, 0.32, 0.28, 0.31, 0.29]
    filtered_h = []
    for h in raw_h:
        dets = np.stack([_det(0.40, 0.40, 0.20, h)])
        results = tracker.update(dets)
        if results and results[0].filtered_tlwh:
            filtered_h.append(results[0].filtered_tlwh[3])

    assert len(filtered_h) >= len(raw_h) - 1, (
        f"tracker should hold the track for ~all {len(raw_h)} frames, "
        f"got {len(filtered_h)}"
    )
    import statistics
    raw_var = statistics.variance(raw_h)
    filt_var = statistics.variance(filtered_h)
    assert filt_var < raw_var, f"filtered_var={filt_var:.5f} not smoother than raw_var={raw_var:.5f}"
