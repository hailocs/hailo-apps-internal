import time
from pathlib import Path

import numpy as np
import soundfile as sf

from community.apps.pipeline_apps.rhythm_royale.audio_source import AudioSource


def _make_tone_mp3(tmp_path: Path, freq: float = 440.0, dur: float = 2.0, sr: int = 44100) -> Path:
    t = np.arange(int(sr * dur)) / sr
    x = (0.3 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    p = tmp_path / "tone.mp3"
    sf.write(p, x, sr, format="MP3")
    return p


def test_file_source_yields_samples_at_expected_rate(tmp_path):
    p = _make_tone_mp3(tmp_path)
    src = AudioSource.from_file(str(p), playback=False, buffer_seconds=2.0)
    src.start()
    try:
        deadline = time.monotonic() + 3.0
        result = None
        while time.monotonic() < deadline:
            result = src.read_latest(1.0)
            if result is not None and len(result[0]) >= int(src.sample_rate * 1.0) * 0.9:
                break
            time.sleep(0.05)
        assert result is not None, "no samples produced within 3 s"
        buf, t_start = result
        assert src.sample_rate == 44100
        assert buf.dtype == np.float32
        assert buf.ndim == 1
        assert np.sqrt(np.mean(buf**2)) > 0.05
        # t_start advances as buffer fills; first 1-s window starts at >= 0.
        assert t_start >= 0.0
    finally:
        src.stop()


def test_ring_buffer_returns_none_when_empty(tmp_path):
    p = _make_tone_mp3(tmp_path, dur=0.5)
    src = AudioSource.from_file(str(p), playback=False, buffer_seconds=1.0)
    assert src.read_latest(0.5) is None


def test_read_latest_returns_absolute_window_timestamp():
    """Each read_latest() returns (samples, t_start_abs) where t_start_abs is
    the absolute timestamp (seconds since AudioSource origin) of the first
    sample of the returned window. Sample N has timestamp N/sample_rate."""
    sr = 1000  # easy arithmetic
    src = AudioSource(sample_rate=sr, buffer_seconds=2.0)

    chunk_a = np.ones(500, dtype=np.float32)
    src._buf.write(chunk_a)
    # 500 samples written; read latest 0.2 s = 200 samples.
    # First returned sample = sample index 500 - 200 = 300, t_abs = 0.300.
    result = src.read_latest(0.2)
    assert result is not None
    samples, t_start = result
    assert len(samples) == 200
    assert abs(t_start - 0.300) < 1e-9, f"got {t_start}, expected 0.300"

    chunk_b = np.zeros(700, dtype=np.float32)
    src._buf.write(chunk_b)
    # 1200 samples written total; read latest 0.5 s = 500 samples.
    # First returned sample = 1200 - 500 = 700, t_abs = 0.700.
    result2 = src.read_latest(0.5)
    assert result2 is not None
    samples2, t_start2 = result2
    assert len(samples2) == 500
    assert abs(t_start2 - 0.700) < 1e-9, f"got {t_start2}, expected 0.700"


def test_read_latest_returns_none_with_no_timestamp_when_empty():
    """When the buffer hasn't accumulated enough samples, read_latest returns
    None (not a tuple of (None, t))."""
    sr = 1000
    src = AudioSource(sample_rate=sr, buffer_seconds=2.0)
    assert src.read_latest(0.5) is None
