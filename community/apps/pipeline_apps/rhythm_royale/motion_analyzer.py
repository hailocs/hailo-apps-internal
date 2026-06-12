"""MotionAnalyzer — per-keypoint motion-to-beat alignment scoring.

A dancer's body is modeled as 7 independent (x, y) motion signals:
nose, shoulders_mid, L_wrist, R_wrist, hips_mid, L_knee, R_knee. Each
signal is buffered, band-passed, FFT'd. Per-keypoint scoring is:

    freq_match  = max over r in {1/2, 1, 2} of exp(-((f_motion - r*f_beat)/SIGMA_F)^2)
    phase_match = 0.5 * (1 + cos(phase_motion_abs - r* * phase_beat_abs))
    energy_gate = clip(rms_band / RMS_GATE, 0, 1)
    kp_score    = freq_match * phase_match * energy_gate

Per-dancer combine: weighted average over keypoints with valid spectra,
*renormalized* over what's available — a partially-tracked dancer is
judged on what we can see, not penalized for missing limbs.

Phases are absolute (corrected to t_ref=0 via t_window_start) so the
audio FFT phase and motion FFT phase live in the same time origin and
can be compared meaningfully.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Optional, Tuple

import numpy as np
from scipy.signal import butter, sosfiltfilt

from community.apps.pipeline_apps.rhythm_royale.beat_extractor import (
    BeatState, BEAT_LO_HZ, BEAT_HI_HZ, ENV_SR, _to_absolute_phase,
)


WIN_MOTION_S = 4.0
SIGMA_F = 0.4
RMS_GATE = 0.05
ALPHA = 0.15
KP_CONF_MIN = 0.3

# Harmonic set used by the freq_match max-Gaussian. Equal weights — a dancer
# locked at half- or double-tempo scores identically to one on the fundamental.
HARMONICS: Tuple[Tuple[float, float], ...] = (
    (0.5, 1.0),
    (1.0, 1.0),
    (2.0, 1.0),
)

# 7 per-dancer signal points and their combine weights (sum = 1.0,
# upper-body-biased). Identical for every dancer for fairness.
KP_WEIGHTS: Dict[str, float] = {
    "nose":          0.10,
    "shoulders_mid": 0.20,
    "L_wrist":       0.20,
    "R_wrist":       0.20,
    "hips_mid":      0.15,
    "L_knee":        0.075,
    "R_knee":        0.075,
}

# Maps each analyzer signal name to the raw Hailo keypoint(s) it derives from.
# Midpoint signals require BOTH source keypoints to pass the confidence gate.
SIGNAL_SOURCES: Dict[str, Tuple[str, ...]] = {
    "nose":          ("nose",),
    "shoulders_mid": ("left_shoulder", "right_shoulder"),
    "L_wrist":       ("left_wrist",),
    "R_wrist":       ("right_wrist",),
    "hips_mid":      ("left_hip", "right_hip"),
    "L_knee":        ("left_knee",),
    "R_knee":        ("right_knee",),
}


@dataclass
class PerKpResult:
    f_motion_hz: float
    phase_motion_abs_rad: float
    r_star: float
    freq_match: float
    phase_match: float
    energy_gate: float
    kp_score: float
    dominant_axis: str
    # For the harmonic-ladder UI: per-r match value (freq_match only, before
    # multiplying by phase_match/energy_gate — so each bar represents only
    # the tempo-tolerance side of the score).
    harmonic_freq_matches: Dict[float, float] = field(default_factory=dict)


@dataclass
class TrackScore:
    value: float                       # smoothed weighted average over kps
    raw: float                         # unsmoothed
    per_kp: Dict[str, PerKpResult]     # populated only for kps with valid spectra


def _bandpass_sos(eff_sr: float):
    nyq = eff_sr / 2.0
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


def _resolve_signal_point(
    signal_name: str,
    raw_kp: Dict[str, Tuple[float, float]],
    confidences: Optional[Dict[str, float]] = None,
    conf_min: float = KP_CONF_MIN,
) -> Optional[Tuple[float, float]]:
    """Return the (x, y) of a signal point, or None if any required source is
    missing / below the confidence gate."""
    sources = SIGNAL_SOURCES[signal_name]
    pts = []
    for src in sources:
        if src not in raw_kp:
            return None
        if confidences is not None and confidences.get(src, 1.0) < conf_min:
            return None
        pts.append(raw_kp[src])
    if len(pts) == 1:
        return pts[0]
    # Midpoint
    x = sum(p[0] for p in pts) / len(pts)
    y = sum(p[1] for p in pts) / len(pts)
    return (x, y)


class _KpBuffer:
    """Per-keypoint ring buffer for one signal of one dancer."""

    def __init__(self):
        self.samples: Deque[Tuple[float, float, float]] = deque(
            maxlen=int(WIN_MOTION_S * 120)
        )  # (t_abs, x, y)


class _TrackBuffer:
    """All per-keypoint buffers for one dancer."""

    def __init__(self):
        self.kps: Dict[str, _KpBuffer] = {n: _KpBuffer() for n in KP_WEIGHTS}
        self.torso: Deque[Tuple[float, float]] = deque(maxlen=int(WIN_MOTION_S * 120))
        self.last_t: Optional[float] = None
        self.smoothed_score: float = 0.0


def _build_signal(samples: Deque[Tuple[float, float, float]],
                  torso_mean: float, t_now: float
                  ) -> Optional[Tuple[np.ndarray, np.ndarray, float]]:
    """Build a torso-normalized, resampled, detrended signal pair (x, y).

    Returns (x_band, y_band, t_window_start_abs) or None when the buffer is
    too short / too short a time-span. t_window_start_abs is the absolute
    timestamp of the first sample in the analysis window — needed for the
    absolute-phase correction in the FFT step.
    """
    if len(samples) < 16:
        return None
    arr = np.fromiter(
        (v for s in samples for v in s),
        dtype=np.float64, count=len(samples) * 3,
    ).reshape(-1, 3)
    times = arr[:, 0]
    xs = arr[:, 1] / torso_mean
    ys = arr[:, 2] / torso_mean
    if times[-1] - times[0] < 1.0:
        return None
    grid = np.arange(times[0], times[-1], 1.0 / ENV_SR)
    if len(grid) < 16:
        return None
    x_sig = np.interp(grid, times, xs)
    y_sig = np.interp(grid, times, ys)
    x_sig -= x_sig.mean()
    y_sig -= y_sig.mean()
    sos = _bandpass_sos(ENV_SR)
    x_band = sosfiltfilt(sos, x_sig)
    y_band = sosfiltfilt(sos, y_sig)
    return x_band, y_band, float(times[0])


def _score_keypoint(x_band: np.ndarray, y_band: np.ndarray,
                    t_window_start: float,
                    beat: BeatState) -> Optional[PerKpResult]:
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
        dom_spec, dom_band, dom_peak = y_spec, y_band, y_peak_idx
        dominant_axis = "y"
    else:
        dom_spec, dom_band, dom_peak = x_spec, x_band, x_peak_idx
        dominant_axis = "x"

    f_motion = float(freqs[dom_peak])

    # Harmonic-set Gaussian: pick the r that maximizes the weighted match.
    best_r = 1.0
    best_freq_match = 0.0
    harmonic_freq_matches: Dict[float, float] = {}
    for r, w in HARMONICS:
        target = r * beat.f_beat_hz
        if target <= 0:
            continue
        m = w * float(np.exp(-((f_motion - target) / SIGMA_F) ** 2))
        harmonic_freq_matches[r] = m
        if m > best_freq_match:
            best_freq_match = m
            best_r = r

    # Phase at r* · f_beat — read the motion's bin nearest that target.
    target_motion = best_r * beat.f_beat_hz
    bin_target = int(np.argmin(np.abs(freqs - target_motion)))
    phase_motion_window = float(np.angle(dom_spec[bin_target]))
    phase_motion_abs = _to_absolute_phase(
        phase_motion_window, freqs[bin_target], t_window_start,
    )
    # Compare to beat phase scaled to the same harmonic.
    # cos handles the (mod 2π) wrap implicitly.
    phase_match = 0.5 * (
        1.0 + float(np.cos(phase_motion_abs - best_r * beat.phase_abs_rad))
    )

    rms = float(np.sqrt(np.mean(dom_band ** 2)))
    energy_gate = float(np.clip(rms / RMS_GATE, 0.0, 1.0))

    kp_score = best_freq_match * phase_match * energy_gate

    return PerKpResult(
        f_motion_hz=f_motion,
        phase_motion_abs_rad=phase_motion_abs,
        r_star=best_r,
        freq_match=best_freq_match,
        phase_match=phase_match,
        energy_gate=energy_gate,
        kp_score=kp_score,
        dominant_axis=dominant_axis,
        harmonic_freq_matches=harmonic_freq_matches,
    )


class MotionAnalyzer:
    def __init__(self, fps_hint: float = 30.0):
        self._tracks: Dict[int, _TrackBuffer] = {}
        self._fps_hint = fps_hint

    def update_track(self, track_id: int,
                     keypoints: Dict[str, Tuple[float, float]],
                     t_seconds: float,
                     confidences: Optional[Dict[str, float]] = None) -> None:
        buf = self._tracks.setdefault(track_id, _TrackBuffer())
        torso = _torso_length(keypoints)
        if torso < 1e-3:
            buf.last_t = t_seconds
            return
        buf.torso.append((t_seconds, torso))
        buf.last_t = t_seconds

        cutoff = t_seconds - WIN_MOTION_S
        while buf.torso and buf.torso[0][0] < cutoff:
            buf.torso.popleft()

        for signal_name in KP_WEIGHTS:
            pt = _resolve_signal_point(signal_name, keypoints, confidences)
            if pt is None:
                # Don't append — the kp's deque just doesn't get this sample.
                continue
            x, y = pt
            kpbuf = buf.kps[signal_name]
            kpbuf.samples.append((t_seconds, x, y))
            while kpbuf.samples and kpbuf.samples[0][0] < cutoff:
                kpbuf.samples.popleft()

    def compute_score(self, track_id: int, beat: Optional[BeatState],
                      t_seconds: float) -> Optional[TrackScore]:
        if beat is None:
            return None
        buf = self._tracks.get(track_id)
        if buf is None or not buf.torso:
            return None
        torso_mean = float(np.mean([t[1] for t in buf.torso])) + 1e-6

        per_kp: Dict[str, PerKpResult] = {}
        weighted_sum = 0.0
        weight_total = 0.0
        for kp_name, w in KP_WEIGHTS.items():
            kpbuf = buf.kps[kp_name]
            signal = _build_signal(kpbuf.samples, torso_mean, t_seconds)
            if signal is None:
                continue
            x_band, y_band, t_window_start = signal
            res = _score_keypoint(x_band, y_band, t_window_start, beat)
            if res is None:
                continue
            per_kp[kp_name] = res
            weighted_sum += w * res.kp_score
            weight_total += w

        if weight_total <= 0.0:
            return None

        raw = weighted_sum / weight_total
        buf.smoothed_score = ALPHA * raw + (1.0 - ALPHA) * buf.smoothed_score
        return TrackScore(
            value=buf.smoothed_score,
            raw=raw,
            per_kp=per_kp,
        )

    def prune_stale(self, t_seconds: float, max_age_s: float = 3.0) -> None:
        dead = [tid for tid, buf in self._tracks.items()
                if buf.last_t is not None and t_seconds - buf.last_t > max_age_s]
        for tid in dead:
            del self._tracks[tid]
