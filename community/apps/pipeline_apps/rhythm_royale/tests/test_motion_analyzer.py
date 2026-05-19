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
    beat = BeatState(f_beat_hz=2.0, phase_rad=0.0, phase_abs_rad=0.0,
                     t_window_start=0.0, confidence=10.0, timestamp=0.0)
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
    beat = BeatState(f_beat_hz=2.0, phase_rad=0.0, phase_abs_rad=0.0,
                     t_window_start=0.0, confidence=10.0, timestamp=0.0)
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
    beat = BeatState(f_beat_hz=2.0, phase_rad=0.0, phase_abs_rad=0.0,
                     t_window_start=0.0, confidence=10.0, timestamp=0.0)
    dt = 1 / 30
    score = None
    still = _make_dancer(0.0, f_dance_hz=2.0, phase=0.0, amp_px=0.0)
    for i in range(int(4.0 * 30)):
        t = i * dt
        analyzer.update_track(1, still, t)
        score = analyzer.compute_score(1, beat, t)
    assert score is None or score.value < 0.05


def _run_dancer(analyzer, beat, f_dance_hz, phase=0.0, duration_s=4.0):
    """Helper: drive a synthetic dancer through the analyzer; return final score."""
    dt = 1 / 30
    score = None
    for i in range(int(duration_s * 30)):
        t = i * dt
        analyzer.update_track(1, _make_dancer(t, f_dance_hz=f_dance_hz, phase=phase), t)
        score = analyzer.compute_score(1, beat, t)
    return score


def test_half_tempo_dancer_scores_comparably_to_fundamental():
    """A dancer bobbing at f_beat/2 (half-tempo, every other beat) should
    score nearly the same as a fundamental-tempo dancer. The harmonic-set
    Gaussian with equal weights makes both r=1 and r=1/2 valid lockings."""
    beat = BeatState(f_beat_hz=2.0, phase_rad=0.0, phase_abs_rad=0.0,
                     t_window_start=0.0, confidence=10.0, timestamp=0.0)
    s_fund = _run_dancer(MotionAnalyzer(30.0), beat, f_dance_hz=2.0)
    s_half = _run_dancer(MotionAnalyzer(30.0), beat, f_dance_hz=1.0)
    assert s_fund is not None and s_half is not None
    # Both should score high (>0.4 is the existing "good" bar).
    assert s_half.value > 0.4, f"half-tempo dancer scored {s_half.value}"
    # Half-tempo should be within ~20% of fundamental (not penalized).
    assert s_half.value > 0.8 * s_fund.value, (
        f"half-tempo scored {s_half.value} vs fundamental {s_fund.value}"
    )


def test_double_tempo_dancer_scores_comparably_to_fundamental():
    """A dancer at 2*f_beat (eighth-notes) should score similarly to one on
    the fundamental beat."""
    beat = BeatState(f_beat_hz=2.0, phase_rad=0.0, phase_abs_rad=0.0,
                     t_window_start=0.0, confidence=10.0, timestamp=0.0)
    s_fund = _run_dancer(MotionAnalyzer(30.0), beat, f_dance_hz=2.0)
    s_dbl = _run_dancer(MotionAnalyzer(30.0), beat, f_dance_hz=4.0)
    assert s_fund is not None and s_dbl is not None
    assert s_dbl.value > 0.4, f"double-tempo dancer scored {s_dbl.value}"
    assert s_dbl.value > 0.8 * s_fund.value, (
        f"double-tempo scored {s_dbl.value} vs fundamental {s_fund.value}"
    )


def test_per_kp_breakdown_is_exposed():
    """TrackScore.per_kp must carry one entry per signal that produced a
    spectrum. Each entry has per-harmonic Gaussian matches for the ladder UI."""
    analyzer = MotionAnalyzer(fps_hint=30.0)
    beat = BeatState(f_beat_hz=2.0, phase_rad=0.0, phase_abs_rad=0.0,
                     t_window_start=0.0, confidence=10.0, timestamp=0.0)
    score = _run_dancer(analyzer, beat, f_dance_hz=2.0)
    assert score is not None
    # The test fixture has shoulders, hips, nose, wrists — so 5 of 7 signals
    # are realisable (knees aren't in the fixture).
    assert set(score.per_kp.keys()).issuperset({
        "nose", "shoulders_mid", "L_wrist", "R_wrist", "hips_mid",
    })
    # Knees were never provided -> no spectrum -> not in per_kp.
    assert "L_knee" not in score.per_kp
    assert "R_knee" not in score.per_kp

    # The chosen harmonic should be r*=1.0 (dancer at exactly the beat freq).
    for name in ("nose", "L_wrist", "R_wrist"):
        assert score.per_kp[name].r_star == 1.0, (
            f"{name} chose r={score.per_kp[name].r_star} for fundamental dance"
        )
    # Per-harmonic ladder data is populated for all r in HARMONICS.
    assert set(score.per_kp["nose"].harmonic_freq_matches.keys()) == {0.5, 1.0, 2.0}


def test_phase_match_is_invariant_to_motion_window_timing():
    """The same dancer doing the same bob in two different time origins (the
    second simply starts 2.0 s later) must produce the same phase_match, as
    long as the beat phase is given in the same absolute reference. Without
    the t_window_start correction, the motion FFT bin phase shifts by
    2π·f·Δt and phase_match drifts wildly."""
    beat = BeatState(f_beat_hz=2.0, phase_rad=0.0, phase_abs_rad=0.0,
                     t_window_start=0.0, confidence=10.0, timestamp=0.0)

    # Same dancer, run A at t∈[0, 4) and run B at t∈[2, 6).
    # Both should end up reporting the SAME phase_match for upper-body kps,
    # because the dancer is locked to absolute beat at any time.
    a = MotionAnalyzer(fps_hint=30.0)
    b = MotionAnalyzer(fps_hint=30.0)
    dt = 1 / 30
    s_a = s_b = None
    for i in range(int(4.0 * 30)):
        t = i * dt
        a.update_track(1, _make_dancer(t, f_dance_hz=2.0, phase=0.0), t)
        s_a = a.compute_score(1, beat, t)
    for i in range(int(4.0 * 30)):
        t_offset = 2.0 + i * dt
        b.update_track(1, _make_dancer(t_offset, f_dance_hz=2.0, phase=0.0), t_offset)
        s_b = b.compute_score(1, beat, t_offset)

    assert s_a is not None and s_b is not None
    for kp in ("nose", "L_wrist", "R_wrist"):
        pa = s_a.per_kp[kp].phase_match
        pb = s_b.per_kp[kp].phase_match
        assert abs(pa - pb) < 0.05, (
            f"{kp} phase_match drifted: a={pa:.3f} vs b={pb:.3f}"
        )


def test_forgiving_combine_renormalizes_over_available_kps():
    """With knees missing (test fixture has ankles instead, which we ignore),
    forgiving combine divides by the SUM of available-kp weights — the
    dancer is judged on what we saw, not penalized to (knee_weight / 1.0)
    for the missing knees."""
    beat = BeatState(f_beat_hz=2.0, phase_rad=0.0, phase_abs_rad=0.0,
                     t_window_start=0.0, confidence=10.0, timestamp=0.0)
    score = _run_dancer(MotionAnalyzer(30.0), beat, f_dance_hz=2.0)
    assert score is not None
    # The test fixture has bobbing upper-body kps (nose, wrists, shoulders) and
    # still hips. Upper-body weighted sum ~0.70; hips still ~0; knees missing.
    # If we WEREN'T forgiving (denom = 1.0 fixed): raw ≈ 0.70.
    # WITH forgiving combine (denom = 0.85, knees dropped): raw ≈ 0.82.
    # Check `raw` (instantaneous) rather than `value` (which smooths with
    # ALPHA=0.15 and lags substantially after only 4 s of warm-up).
    assert score.raw > 0.75, (
        f"forgiving combine should yield raw>0.75 here, got {score.raw}"
    )
