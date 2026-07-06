"""Beat extractor tests.

Test fixtures synthesize MP3 files (per project convention: MP3 for audio
test input). The synthetic signal is amplitude-modulated noise at a known
BPM — this approximates how real music's amplitude envelope looks (kick on
the beat, dynamic content between beats), unlike an idealized impulse train
whose harmonics all have equal magnitude.
"""
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from community.apps.pipeline_apps.rhythm_royale.beat_extractor import (
    compute_beat_state,
    BeatState,
)


def _write_beat_mp3(path: Path, bpm: float, duration_s: float = 4.0,
                    sr: int = 44100, seed: int = 42) -> Path:
    """Generate AM-noise audio at the given BPM and write as MP3.

    `mod` is a half-wave-rectified sine at the beat frequency, so the audio
    is loud on the down-beat and silent between beats — matches the dynamics
    of a kick-drum-led track.
    """
    rng = np.random.default_rng(seed)
    n = int(duration_s * sr)
    t = np.arange(n) / sr
    f_beat = bpm / 60.0
    mod = np.maximum(0.0, np.sin(2 * np.pi * f_beat * t)).astype(np.float32)
    # Smooth the modulator slightly so beat envelope is not razor-sharp.
    kernel = int(0.02 * sr)
    mod = np.convolve(mod, np.ones(kernel, dtype=np.float32) / kernel, mode="same")
    carrier = (0.5 * rng.standard_normal(n)).astype(np.float32)
    x = (mod * carrier).astype(np.float32)
    x = x / (np.max(np.abs(x)) + 1e-9) * 0.6
    sf.write(path, x, sr, format="MP3")
    return path


@pytest.mark.parametrize("bpm,expected_hz", [
    (60.0, 1.0),
    (120.0, 2.0),
    (180.0, 3.0),
    # New-bandpass coverage: BPMs whose fundamental sits *outside* the legacy
    # peak-search window [0.75, 3.8] Hz but inside the new [0.6, 5.8] Hz one.
    # 40 BPM = 0.67 Hz (very slow ballad), 270 BPM = 4.5 Hz (footwork / dnb).
    (40.0, 0.67),
    (270.0, 4.5),
])
def test_mp3_beat_track_yields_correct_beat_freq(tmp_path, bpm, expected_hz):
    p = _write_beat_mp3(tmp_path / f"beat_{int(bpm)}.mp3", bpm=bpm)
    audio, sr = sf.read(p, dtype="float32", always_2d=False)
    if audio.ndim == 2:
        audio = audio.mean(axis=1)
    state = compute_beat_state(audio.astype(np.float32), sample_rate=int(sr))
    assert state is not None, f"no beat detected for {bpm} BPM"
    assert isinstance(state, BeatState)
    assert abs(state.f_beat_hz - expected_hz) < 0.3, (
        f"got {state.f_beat_hz} Hz, expected {expected_hz} Hz "
        f"(conf={state.confidence:.2f})"
    )


def test_absolute_phase_is_invariant_to_window_start(tmp_path):
    """Same synthetic beat track, two different t_window_start values:
    BeatState.phase_abs_rad must be the same (mod 2π).

    This is the bug-fix anchor for phase alignment — without time-origin
    correction, the bin phase shifts by 2π·f·Δt as the window slides, and
    any phase comparison between audio and motion picks up that drift.
    """
    p = _write_beat_mp3(tmp_path / "beat_120.mp3", bpm=120.0, duration_s=8.0)
    audio, sr = sf.read(p, dtype="float32", always_2d=False)
    if audio.ndim == 2:
        audio = audio.mean(axis=1)
    audio = audio.astype(np.float32)

    win_n = int(4.0 * sr)
    win_a = audio[:win_n]
    win_b = audio[int(1.0 * sr):int(1.0 * sr) + win_n]  # same content shifted +1.0 s

    state_a = compute_beat_state(win_a, sample_rate=int(sr), t_window_start=0.0)
    state_b = compute_beat_state(win_b, sample_rate=int(sr), t_window_start=1.0)
    assert state_a is not None and state_b is not None
    # Same music content -> same beat frequency (within bin resolution).
    assert abs(state_a.f_beat_hz - state_b.f_beat_hz) < 0.3
    # And same ABSOLUTE phase, modulo 2π. Compare via cos of difference
    # (avoids wrap-around comparison headaches).
    cos_diff = np.cos(state_a.phase_abs_rad - state_b.phase_abs_rad)
    assert cos_diff > 0.9, (
        f"phase_abs drifted with window: a={state_a.phase_abs_rad:.3f}, "
        f"b={state_b.phase_abs_rad:.3f}, cos(Δ)={cos_diff:.3f}"
    )


def test_beat_state_exposes_window_start(tmp_path):
    """BeatState.t_window_start is the t_window_start argument we passed in."""
    p = _write_beat_mp3(tmp_path / "beat_120.mp3", bpm=120.0)
    audio, sr = sf.read(p, dtype="float32", always_2d=False)
    if audio.ndim == 2:
        audio = audio.mean(axis=1)
    state = compute_beat_state(audio.astype(np.float32), sample_rate=int(sr),
                               t_window_start=3.5)
    assert state is not None
    assert state.t_window_start == 3.5


def test_silence_mp3_yields_none(tmp_path):
    p = tmp_path / "silence.mp3"
    sr = 44100
    x = np.zeros(int(4.0 * sr), dtype=np.float32)
    sf.write(p, x, sr, format="MP3")
    audio, sr2 = sf.read(p, dtype="float32", always_2d=False)
    if audio.ndim == 2:
        audio = audio.mean(axis=1)
    state = compute_beat_state(audio.astype(np.float32), sample_rate=int(sr2))
    assert state is None
