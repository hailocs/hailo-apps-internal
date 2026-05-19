import numpy as np

from community.apps.pipeline_apps.rhythm_royale.motion_analyzer import (
    MotionAnalyzer,
)
from community.apps.pipeline_apps.rhythm_royale.beat_extractor import BeatState


def _make_dancer(t_seconds, f_dance_hz=2.0, phase=0.0, amp_px=30.0):
    """Synthetic dancer. phase=0 means y is at maximum (bottom of bob) at t=0,
    aligned with BeatState(phase_rad=0) which is cos-aligned peak at t=0.
    """
    base = {
        "nose": (320.0, 200.0),
        "left_shoulder": (300.0, 250.0),
        "right_shoulder": (340.0, 250.0),
        "left_hip": (305.0, 350.0),
        "right_hip": (335.0, 350.0),
        "left_wrist": (250.0, 300.0),
        "right_wrist": (390.0, 300.0),
        "left_ankle": (305.0, 450.0),
        "right_ankle": (335.0, 450.0),
    }
    bob = amp_px * np.cos(2 * np.pi * f_dance_hz * t_seconds + phase)
    out = {}
    for name, (x, y) in base.items():
        # Bob most keypoints together so the centroid moves clearly.
        if name in ("nose", "left_wrist", "right_wrist", "left_shoulder", "right_shoulder"):
            out[name] = (x, y + bob)
        else:
            out[name] = (x, y)
    return out


def test_dancer_in_sync_scores_high():
    analyzer = MotionAnalyzer(fps_hint=30.0)
    beat = BeatState(f_beat_hz=2.0, phase_rad=0.0, confidence=10.0, timestamp=0.0)
    dt = 1 / 30
    score = None
    for i in range(int(4.0 * 30)):
        t = i * dt
        kp = _make_dancer(t, f_dance_hz=2.0, phase=0.0)
        analyzer.update_track(track_id=1, keypoints=kp, t_seconds=t)
        score = analyzer.compute_score(track_id=1, beat=beat, t_seconds=t)
    assert score is not None
    assert score.value > 0.4, f"in-sync dancer scored only {score.value}"


def test_dancer_out_of_phase_scores_lower_than_in_phase():
    a1 = MotionAnalyzer(fps_hint=30.0)
    a2 = MotionAnalyzer(fps_hint=30.0)
    beat = BeatState(f_beat_hz=2.0, phase_rad=0.0, confidence=10.0, timestamp=0.0)
    dt = 1 / 30
    s1 = s2 = None
    for i in range(int(4.0 * 30)):
        t = i * dt
        a1.update_track(1, _make_dancer(t, 2.0, phase=0.0), t)
        a2.update_track(1, _make_dancer(t, 2.0, phase=np.pi), t)
        s1 = a1.compute_score(1, beat, t)
        s2 = a2.compute_score(1, beat, t)
    assert s1 is not None and s2 is not None
    assert s1.value > s2.value


def test_still_person_scores_zero():
    analyzer = MotionAnalyzer(fps_hint=30.0)
    beat = BeatState(f_beat_hz=2.0, phase_rad=0.0, confidence=10.0, timestamp=0.0)
    dt = 1 / 30
    score = None
    still = _make_dancer(0.0, f_dance_hz=2.0, phase=0.0, amp_px=0.0)
    for i in range(int(4.0 * 30)):
        t = i * dt
        analyzer.update_track(1, still, t)
        score = analyzer.compute_score(1, beat, t)
    assert score is None or score.value < 0.05
