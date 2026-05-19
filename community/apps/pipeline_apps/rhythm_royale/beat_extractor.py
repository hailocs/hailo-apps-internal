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


def compute_beat_state(audio: np.ndarray, sample_rate: int,
                       timestamp: Optional[float] = None,
                       t_window_start: float = 0.0) -> Optional[BeatState]:
    if audio is None or len(audio) < int(0.5 * sample_rate):
        return None

    # 0. Reject silence on absolute RMS — Hilbert envelope of pure noise can
    #    still produce a high peak/median ratio in the beat band.
    if float(np.sqrt(np.mean(audio.astype(np.float64) ** 2))) < MIN_INPUT_RMS:
        return None

    # 1. Amplitude envelope via analytic signal magnitude
    analytic = hilbert(audio.astype(np.float64))
    env = np.abs(analytic).astype(np.float32)

    # 2. Decimate to ~ENV_SR Hz
    q = int(round(sample_rate / ENV_SR))
    if q < 1:
        q = 1
    # scipy.signal.decimate has a per-call factor limit; chain if needed.
    env_ds = env
    eff_sr = float(sample_rate)
    while q > 1:
        step = min(q, 10)
        env_ds = decimate(env_ds, step, ftype="fir", zero_phase=True)
        eff_sr /= step
        q //= step
    env_ds = env_ds.astype(np.float32)

    # 3. Detrend
    env_ds = env_ds - env_ds.mean()
    if np.std(env_ds) < 1e-6:
        return None

    # 4. Band-pass [0.5, 4.0] Hz
    nyq = eff_sr / 2
    sos = butter(4, [BEAT_LO_HZ / nyq, BEAT_HI_HZ / nyq],
                 btype="band", output="sos")
    band = sosfiltfilt(sos, env_ds)

    # 5. FFT with Hann window
    n = len(band)
    win = np.hanning(n)
    spec = np.fft.rfft(band * win)
    freqs = np.fft.rfftfreq(n, d=1.0 / eff_sr)
    mag = np.abs(spec)

    # 6. Restrict peak search to the *interior* of the filter band — bins at
    #    the band edges carry filter rolloff energy and can spuriously win.
    peak_mask = (freqs >= PEAK_LO_HZ) & (freqs <= PEAK_HI_HZ)
    median_mask = (freqs >= BEAT_LO_HZ) & (freqs <= BEAT_HI_HZ)
    if not np.any(peak_mask):
        return None
    peak_global = int(np.argmax(np.where(peak_mask, mag, -np.inf)))
    peak_mag = float(mag[peak_global])
    # Noise floor: median of in-band bins outside ±PEAK_EXCL_HZ of the peak.
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


class BeatExtractor:
    """Stateful wrapper: polls an AudioSource on a worker thread."""

    def __init__(self, audio_source, update_hz: float = 10.0):
        self.audio_source = audio_source
        self._interval = 1.0 / update_hz
        self._state: Optional[BeatState] = None
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

    def _run(self) -> None:
        while not self._stop.is_set():
            result = self.audio_source.read_latest(WIN_AUDIO_S)
            if result is not None:
                buf, t_window_start = result
                try:
                    state = compute_beat_state(
                        buf, self.audio_source.sample_rate,
                        t_window_start=t_window_start,
                    )
                except Exception:
                    state = None
                with self._lock:
                    self._state = state
            time.sleep(self._interval)
