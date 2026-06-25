"""Pop sound for Bubble Pop — synthesized once, played via paplay/aplay.

No audio library dependency: the pop is generated with numpy into a WAV
file in the temp dir on first run, then each play is a fire-and-forget
``paplay``/``aplay`` subprocess (a few ms of latency, fine for a game).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
import wave

import numpy as np

from hailo_apps.python.core.common.hailo_logger import get_logger

logger = get_logger(__name__)

_SAMPLE_RATE = 44100
_WAV_NAME = "hailo_bubble_pop.wav"
_CAST_WAV_NAME = "hailo_bubble_cast.wav"
_MIN_INTERVAL_S = 0.05  # don't spawn more than ~20 plays/sec


def _write_wav(path: str, samples: np.ndarray) -> None:
    with wave.open(path, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(_SAMPLE_RATE)
        wav.writeframes(samples.tobytes())


def _synth_pop_wav(path: str) -> None:
    """Write a short 'blop' — a downward frequency sweep with fast decay."""
    duration = 0.09
    t = np.linspace(0.0, duration, int(_SAMPLE_RATE * duration), endpoint=False)
    # Frequency sweeps 750 Hz -> 160 Hz exponentially (water-drop feel)
    freq = 750.0 * (160.0 / 750.0) ** (t / duration)
    phase = 2 * np.pi * np.cumsum(freq) / _SAMPLE_RATE
    envelope = np.exp(-t * 40.0)
    _write_wav(path, (0.6 * np.sin(phase) * envelope * 32767).astype(np.int16))


def _synth_cast_wav(path: str) -> None:
    """Write a magic 'cast' — a rising shimmer sweep with vibrato."""
    duration = 0.22
    t = np.linspace(0.0, duration, int(_SAMPLE_RATE * duration), endpoint=False)
    # Frequency sweeps 300 Hz -> 1200 Hz with a sparkle vibrato on top
    freq = 300.0 * (1200.0 / 300.0) ** (t / duration)
    freq *= 1.0 + 0.02 * np.sin(2 * np.pi * 40 * t)
    phase = 2 * np.pi * np.cumsum(freq) / _SAMPLE_RATE
    envelope = np.sin(np.pi * t / duration)  # gentle fade in/out
    _write_wav(path, (0.45 * np.sin(phase) * envelope * 32767).astype(np.int16))


class PopSound:
    """Throttled, non-blocking pop-sound player. Silently disabled if no
    audio player binary is available."""

    def __init__(self, enabled: bool = True):
        self._player = shutil.which("paplay") or shutil.which("aplay")
        self.enabled = bool(enabled and self._player)
        self._wav_path = os.path.join(tempfile.gettempdir(), _WAV_NAME)
        self._cast_path = os.path.join(tempfile.gettempdir(), _CAST_WAV_NAME)
        self._last_play = 0.0
        self._last_cast = 0.0

        if enabled and not self._player:
            logger.warning("No paplay/aplay found — pop sound disabled")
        if self.enabled:
            if not os.path.exists(self._wav_path):
                _synth_pop_wav(self._wav_path)
                logger.info("Synthesized pop sound: %s", self._wav_path)
            if not os.path.exists(self._cast_path):
                _synth_cast_wav(self._cast_path)
                logger.info("Synthesized cast sound: %s", self._cast_path)

    def play(self) -> None:
        now = time.monotonic()
        if now - self._last_play < _MIN_INTERVAL_S:
            return
        self._last_play = now
        self._spawn(self._wav_path)

    def play_cast(self) -> None:
        now = time.monotonic()
        if now - self._last_cast < 0.2:
            return
        self._last_cast = now
        self._spawn(self._cast_path)

    def _spawn(self, wav_path: str) -> None:
        if not self.enabled:
            return
        try:
            # start_new_session detaches the player into its own session so it
            # doesn't accumulate as a zombie over a long game (we never wait()).
            subprocess.Popen(
                [self._player, wav_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            logger.warning("Sound failed (%s) — disabling sound", exc)
            self.enabled = False
