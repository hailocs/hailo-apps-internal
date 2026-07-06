"""Overlay widget smoke tests. We can't pixel-verify here; we just confirm
each widget runs end-to-end on a synthetic frame without exceptions and
mutates the frame (vs returning it).
"""
import numpy as np

from community.apps.pipeline_apps.rhythm_royale import overlay
from community.apps.pipeline_apps.rhythm_royale.beat_extractor import (
    BeatEnvelope, BeatState,
)
from community.apps.pipeline_apps.rhythm_royale.motion_analyzer import (
    PerKpResult, TrackScore,
)


def _blank(h=720, w=1280):
    return np.zeros((h, w, 3), dtype=np.uint8)


def _kp_full():
    """A complete keypoint dict matching what _extract_keypoints produces."""
    return {
        "nose": (640.0, 200.0),
        "left_eye": (630.0, 195.0),
        "right_eye": (650.0, 195.0),
        "left_ear": (625.0, 200.0),
        "right_ear": (655.0, 200.0),
        "left_shoulder": (600.0, 250.0),
        "right_shoulder": (680.0, 250.0),
        "left_elbow": (580.0, 300.0),
        "right_elbow": (700.0, 300.0),
        "left_wrist": (560.0, 350.0),
        "right_wrist": (720.0, 350.0),
        "left_hip": (610.0, 400.0),
        "right_hip": (670.0, 400.0),
        "left_knee": (605.0, 500.0),
        "right_knee": (675.0, 500.0),
        "left_ankle": (600.0, 600.0),
        "right_ankle": (680.0, 600.0),
    }


def _beat():
    return BeatState(f_beat_hz=2.0, phase_rad=0.0, phase_abs_rad=0.5,
                     t_window_start=10.0, confidence=4.5, timestamp=10.0)


def _envelope():
    samples = (np.sin(np.linspace(0, 16 * np.pi, 400)) * 0.5).astype(np.float32)
    return BeatEnvelope(samples=samples, eff_sr=100.0, t_start=10.0)


def _track_score():
    kp_res = PerKpResult(
        f_motion_hz=2.0, phase_motion_abs_rad=0.4, r_star=1.0,
        freq_match=0.95, phase_match=0.9, energy_gate=1.0,
        kp_score=0.85, dominant_axis="y",
        harmonic_freq_matches={0.5: 0.1, 1.0: 0.95, 2.0: 0.05},
    )
    return TrackScore(value=0.8, raw=0.85, per_kp={
        "nose": kp_res, "L_wrist": kp_res, "shoulders_mid": kp_res,
    })


def test_draw_skeleton_with_per_kp_colors_runs():
    f = _blank()
    kp = _kp_full()
    colors = {"left_wrist": (0, 255, 0), "right_wrist": (255, 0, 0)}
    overlay.draw_skeleton(f, kp, color=(200, 200, 200), kp_colors=colors)
    assert f.sum() > 0  # something was drawn


def test_draw_skeleton_respects_confidence_gate():
    f = _blank()
    kp = _kp_full()
    # Below conf_min — should NOT be drawn.
    kp_conf = {name: 0.1 for name in kp}
    overlay.draw_skeleton(f, kp, color=(200, 200, 200), kp_conf=kp_conf, conf_min=0.5)
    assert f.sum() == 0


def test_draw_beat_tape_with_envelope_and_beats():
    f = _blank()
    env = _envelope()
    beat = _beat()
    overlay.draw_beat_tape(f, env, beat, t_now=14.0)
    assert f.sum() > 0


def test_draw_beat_tape_handles_missing_envelope():
    f = _blank()
    overlay.draw_beat_tape(f, None, None, t_now=0.0)
    assert f.sum() > 0  # still draws the empty strip with label


def test_draw_harmonic_ladder_runs():
    f = _blank()
    kp = _kp_full()
    overlay.draw_harmonic_ladder(f, kp, _track_score())
    assert f.sum() > 0


def test_draw_phase_clock_with_dancers():
    f = _blank()
    overlay.draw_phase_clock(f, _beat(), [(1, _track_score()), (2, _track_score())],
                             t_now=12.5)
    assert f.sum() > 0


def test_draw_phase_clock_without_beat():
    f = _blank()
    overlay.draw_phase_clock(f, None, [], t_now=0.0)
    assert f.sum() > 0  # still draws the empty face


def test_per_kp_glow_colors_maps_midpoints():
    score = _track_score()
    # Add a shoulders_mid entry — it should color BOTH left/right shoulders.
    score.per_kp["shoulders_mid"] = score.per_kp["nose"]
    colors = overlay.per_kp_glow_colors(score.per_kp)
    assert "left_shoulder" in colors
    assert "right_shoulder" in colors
    assert "nose" in colors
    assert "left_wrist" in colors
