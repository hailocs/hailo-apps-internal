"""BeatExtractor — pure-DSP estimation of music tempo and phase.

Given a window of mono audio at `sample_rate`, returns the dominant beat
frequency in 0.5-4 Hz (30-240 BPM), the phase at that frequency, and a
confidence (peak / median in band).
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy.signal import butter, sosfiltfilt, hilbert, decimate


BEAT_LO_HZ = 0.4       # filter passband lower edge (24 BPM)
BEAT_HI_HZ = 6.0       # filter passband upper edge (360 BPM)
PEAK_LO_HZ = 0.6       # peak search lower bound (skip filter-edge bin)
PEAK_HI_HZ = 5.8       # peak search upper bound
ENV_SR = 100           # Hz — envelope sample rate
WIN_AUDIO_S = 4.0
PEAK_EXCL_HZ = 0.5     # exclude ±0.5 Hz around peak when computing noise floor
MIN_CONF = 2.0         # peak / (median of off-peak bins)
MIN_INPUT_RMS = 1e-3   # silence floor (linear)


@dataclass
class BeatState:
    f_beat_hz: float
    phase_rad: float          # FFT bin phase, relative to window start
    phase_abs_rad: float      # absolute phase at t_ref=0 (AudioSource origin)
    t_window_start: float     # absolute timestamp of window's first sample
    confidence: float
    timestamp: float


@dataclass
class BeatEnvelope:
    """Snapshot of the band-passed amplitude envelope of the last analyzed
    audio window — what the beat-tape widget visualizes. Lets the operator
    visually compare the algorithm's view of the music to the audible kicks.
    """
    samples: "np.ndarray"  # 1-D, length ~ WIN_AUDIO_S * eff_sr
    eff_sr: float          # envelope sample rate (~ENV_SR Hz)
    t_start: float         # absolute timestamp of samples[0]


def _to_absolute_phase(phase_window_rad: float, freq_hz: float,
                       t_window_start: float) -> float:
    """Convert an FFT bin phase to absolute phase at t_ref = 0.

    The FFT bin at frequency f models the windowed signal as
        s(t_local) = |A| cos(2π f t_local + phase_window),    t_local ∈ [0, T_win].
    In absolute time t_abs = t_local + t_window_start:
        s(t_abs)   = |A| cos(2π f t_abs - 2π f t_window_start + phase_window).
    So the absolute phase, in convention cos(2π f t_abs + phase_abs), is:
        phase_abs = phase_window - 2π f t_window_start    (mod 2π).
    """
    phi = phase_window_rad - 2.0 * np.pi * freq_hz * t_window_start
    # Wrap into (-π, π] for stable comparisons.
    return float(np.angle(np.exp(1j * phi)))


def _compute_envelope(audio: np.ndarray,
                      sample_rate: int) -> Optional[tuple]:
    """Hilbert → decimate → detrend → band-pass.
    Returns (band_passed_envelope, eff_sr) or None if input is silent/unusable.
    """
    if audio is None or len(audio) < int(0.5 * sample_rate):
        return None
    if float(np.sqrt(np.mean(audio.astype(np.float64) ** 2))) < MIN_INPUT_RMS:
        return None
    analytic = hilbert(audio.astype(np.float64))
    env = np.abs(analytic).astype(np.float32)

    q = int(round(sample_rate / ENV_SR))
    if q < 1:
        q = 1
    env_ds = env
    eff_sr = float(sample_rate)
    while q > 1:
        step = min(q, 10)
        env_ds = decimate(env_ds, step, ftype="fir", zero_phase=True)
        eff_sr /= step
        q //= step
    env_ds = env_ds.astype(np.float32)

    env_ds = env_ds - env_ds.mean()
    if np.std(env_ds) < 1e-6:
        return None

    nyq = eff_sr / 2
    sos = butter(4, [BEAT_LO_HZ / nyq, BEAT_HI_HZ / nyq],
                 btype="band", output="sos")
    band = sosfiltfilt(sos, env_ds).astype(np.float32)
    return band, eff_sr


def _compute_beat_from_envelope(band: np.ndarray, eff_sr: float,
                                t_window_start: float,
                                timestamp: Optional[float]) -> Optional[BeatState]:
    n = len(band)
    win = np.hanning(n)
    spec = np.fft.rfft(band * win)
    freqs = np.fft.rfftfreq(n, d=1.0 / eff_sr)
    mag = np.abs(spec)

    peak_mask = (freqs >= PEAK_LO_HZ) & (freqs <= PEAK_HI_HZ)
    median_mask = (freqs >= BEAT_LO_HZ) & (freqs <= BEAT_HI_HZ)
    if not np.any(peak_mask):
        return None
    peak_global = int(np.argmax(np.where(peak_mask, mag, -np.inf)))
    peak_mag = float(mag[peak_global])
    floor_mask = median_mask & (np.abs(freqs - freqs[peak_global]) > PEAK_EXCL_HZ)
    if np.any(floor_mask):
        floor_mag = float(np.median(mag[floor_mask])) + 1e-9
    else:
        floor_mag = float(np.median(mag[median_mask])) + 1e-9
    conf = peak_mag / floor_mag
    if conf < MIN_CONF:
        return None

    f_beat = float(freqs[peak_global])
    phase = float(np.angle(spec[peak_global]))
    phase_abs = _to_absolute_phase(phase, f_beat, t_window_start)
    return BeatState(
        f_beat_hz=f_beat,
        phase_rad=phase,
        phase_abs_rad=phase_abs,
        t_window_start=t_window_start,
        confidence=conf,
        timestamp=timestamp if timestamp is not None else time.monotonic(),
    )


def compute_beat_state(audio: np.ndarray, sample_rate: int,
                       timestamp: Optional[float] = None,
                       t_window_start: float = 0.0) -> Optional[BeatState]:
    """Convenience: envelope + beat detection in one call. The BeatExtractor
    splits these steps so it can publish the envelope for the beat-tape UI."""
    env_res = _compute_envelope(audio, sample_rate)
    if env_res is None:
        return None
    band, eff_sr = env_res
    return _compute_beat_from_envelope(band, eff_sr, t_window_start, timestamp)


class BeatExtractor:
    """Stateful wrapper: polls an AudioSource on a worker thread."""

    def __init__(self, audio_source, update_hz: float = 10.0):
        self.audio_source = audio_source
        self._interval = 1.0 / update_hz
        self._state: Optional[BeatState] = None
        self._envelope: Optional[BeatEnvelope] = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)

    def latest(self) -> Optional[BeatState]:
        with self._lock:
            return self._state

    def latest_envelope(self) -> Optional[BeatEnvelope]:
        """Snapshot of the most-recent band-passed audio envelope.
        Returns a copy — safe for the GStreamer callback to draw from."""
        with self._lock:
            return self._envelope

    def _run(self) -> None:
        while not self._stop.is_set():
            result = self.audio_source.read_latest(WIN_AUDIO_S)
            if result is not None:
                buf, t_window_start = result
                try:
                    env_res = _compute_envelope(buf, self.audio_source.sample_rate)
                    if env_res is None:
                        state = None
                        envelope = None
                    else:
                        band, eff_sr = env_res
                        state = _compute_beat_from_envelope(
                            band, eff_sr, t_window_start, timestamp=None,
                        )
                        envelope = BeatEnvelope(
                            samples=band.copy(),
                            eff_sr=eff_sr,
                            t_start=t_window_start,
                        )
                except Exception:
                    state = None
                    envelope = None
                with self._lock:
                    self._state = state
                    self._envelope = envelope
            time.sleep(self._interval)
