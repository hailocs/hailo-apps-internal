"""MotionAnalyzer — per-track motion signal + alignment-to-beat score.

The motion signal is the *signed* weighted centroid of selected keypoints,
torso-normalized, tracked in two channels (x, y). Using a signed scalar
(not the norm of velocity) is critical: ||v|| of a sinusoidal bob is a
full-wave-rectified sinusoid, which puts energy at 2x the bob frequency
and is reported as the "motion frequency". The signed signal preserves
the true bob frequency directly.

For each track and each tick, the analyzer:
  1. Builds y_sig(t) = sum_k w_k * (y_k(t) - mean(y_k)) / torso_mean
     and the same for x.
  2. Resamples to ENV_SR, detrends, band-passes [0.5, 4.0] Hz.
  3. FFTs both channels. Picks the channel with the stronger peak in band
     as the "dominant" motion direction.
  4. Computes freq_match, phase_match, energy_gate against the beat.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import numpy as np
from scipy.signal import butter, sosfiltfilt

from community.apps.pipeline_apps.rhythm_royale.beat_extractor import (
    BeatState, BEAT_LO_HZ, BEAT_HI_HZ, ENV_SR,
)


WIN_MOTION_S = 4.0
KP_WEIGHTS = {
    "left_wrist": 1.0, "right_wrist": 1.0,
    "left_hip": 0.7,   "right_hip": 0.7,
    "left_ankle": 1.0, "right_ankle": 1.0,
    "nose": 0.3,
}
SIGMA_F = 0.4
RMS_GATE = 0.05
ALPHA = 0.15


@dataclass
class TrackScore:
    value: float
    raw: float
    f_motion_hz: float
    phase_motion_rad: float
    freq_match: float
    phase_match: float
    energy_gate: float
    dominant_axis: str  # "x" or "y"


def _bandpass_sos(eff_sr: float):
    nyq = eff_sr / 2
    return butter(4, [BEAT_LO_HZ / nyq, BEAT_HI_HZ / nyq],
                  btype="band", output="sos")


def _torso_length(kp: Dict[str, Tuple[float, float]]) -> float:
    try:
        ls = np.array(kp["left_shoulder"])
        rs = np.array(kp["right_shoulder"])
        lh = np.array(kp["left_hip"])
        rh = np.array(kp["right_hip"])
    except KeyError:
        return 0.0
    sh = 0.5 * (ls + rs)
    hp = 0.5 * (lh + rh)
    return float(np.linalg.norm(sh - hp))


def _weighted_centroid(kp: Dict[str, Tuple[float, float]]) -> Optional[Tuple[float, float]]:
    """Return (x_c, y_c) — weighted centroid of dance-relevant keypoints."""
    wsum = 0.0
    xs = 0.0
    ys = 0.0
    for name, w in KP_WEIGHTS.items():
        if name not in kp:
            continue
        x, y = kp[name]
        xs += w * x
        ys += w * y
        wsum += w
    if wsum < 1e-6:
        return None
    return xs / wsum, ys / wsum


class _TrackBuffer:
    def __init__(self):
        # (t, x_c, y_c, torso_len)
        self.samples: deque = deque(maxlen=int(WIN_MOTION_S * 120))
        self.last_t: Optional[float] = None
        self.smoothed_score: float = 0.0


class MotionAnalyzer:
    def __init__(self, fps_hint: float = 30.0):
        self._tracks: Dict[int, _TrackBuffer] = {}
        self._fps_hint = fps_hint

    def update_track(self, track_id: int,
                     keypoints: Dict[str, Tuple[float, float]],
                     t_seconds: float) -> None:
        buf = self._tracks.setdefault(track_id, _TrackBuffer())
        torso = _torso_length(keypoints)
        if torso < 1e-3:
            buf.last_t = t_seconds
            return
        c = _weighted_centroid(keypoints)
        if c is None:
            buf.last_t = t_seconds
            return
        x_c, y_c = c
        buf.samples.append((t_seconds, x_c, y_c, torso))
        buf.last_t = t_seconds

        cutoff = t_seconds - WIN_MOTION_S
        while buf.samples and buf.samples[0][0] < cutoff:
            buf.samples.popleft()

    def compute_score(self, track_id: int, beat: Optional[BeatState],
                      t_seconds: float) -> Optional[TrackScore]:
        if beat is None:
            return None
        buf = self._tracks.get(track_id)
        if buf is None or len(buf.samples) < int(0.5 * self._fps_hint):
            return None

        arr = np.array(buf.samples, dtype=np.float64)
        times = arr[:, 0]
        xs = arr[:, 1]
        ys = arr[:, 2]
        torsos = arr[:, 3]
        if times[-1] - times[0] < 1.0:
            return None
        torso_mean = float(np.mean(torsos)) + 1e-6
        # Normalize positions by torso (size-invariant), then detrend per-channel.
        xs = xs / torso_mean
        ys = ys / torso_mean

        grid = np.arange(times[0], times[-1], 1.0 / ENV_SR)
        if len(grid) < 16:
            return None
        x_sig = np.interp(grid, times, xs)
        y_sig = np.interp(grid, times, ys)
        x_sig = x_sig - x_sig.mean()
        y_sig = y_sig - y_sig.mean()

        sos = _bandpass_sos(ENV_SR)
        x_band = sosfiltfilt(sos, x_sig)
        y_band = sosfiltfilt(sos, y_sig)

        n = len(x_band)
        win = np.hanning(n)
        x_spec = np.fft.rfft(x_band * win)
        y_spec = np.fft.rfft(y_band * win)
        freqs = np.fft.rfftfreq(n, d=1.0 / ENV_SR)
        x_mag = np.abs(x_spec)
        y_mag = np.abs(y_spec)

        in_band = (freqs >= BEAT_LO_HZ) & (freqs <= BEAT_HI_HZ)
        if not np.any(in_band):
            return None
        x_peak_idx = int(np.argmax(np.where(in_band, x_mag, -np.inf)))
        y_peak_idx = int(np.argmax(np.where(in_band, y_mag, -np.inf)))

        if y_mag[y_peak_idx] >= x_mag[x_peak_idx]:
            dom_spec = y_spec
            dom_band = y_band
            dom_peak_idx = y_peak_idx
            dominant_axis = "y"
        else:
            dom_spec = x_spec
            dom_band = x_band
            dom_peak_idx = x_peak_idx
            dominant_axis = "x"

        f_motion = float(freqs[dom_peak_idx])
        bin_beat = int(np.argmin(np.abs(freqs - beat.f_beat_hz)))
        phase_motion = float(np.angle(dom_spec[bin_beat]))

        freq_match = float(np.exp(-((f_motion - beat.f_beat_hz) / SIGMA_F) ** 2))
        phase_match = 0.5 * (1.0 + float(np.cos(phase_motion - beat.phase_rad)))
        rms = float(np.sqrt(np.mean(dom_band ** 2)))
        energy_gate = float(np.clip(rms / RMS_GATE, 0.0, 1.0))

        raw = freq_match * phase_match * energy_gate
        buf.smoothed_score = ALPHA * raw + (1.0 - ALPHA) * buf.smoothed_score

        return TrackScore(
            value=buf.smoothed_score,
            raw=raw,
            f_motion_hz=f_motion,
            phase_motion_rad=phase_motion,
            freq_match=freq_match,
            phase_match=phase_match,
            energy_gate=energy_gate,
            dominant_axis=dominant_axis,
        )

    def prune_stale(self, t_seconds: float, max_age_s: float = 3.0) -> None:
        dead = [tid for tid, buf in self._tracks.items()
                if buf.last_t is not None and t_seconds - buf.last_t > max_age_s]
        for tid in dead:
            del self._tracks[tid]
