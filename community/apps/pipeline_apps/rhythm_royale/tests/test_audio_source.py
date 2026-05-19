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
        buf = None
        while time.monotonic() < deadline:
            buf = src.read_latest(1.0)
            if buf is not None and len(buf) >= int(src.sample_rate * 1.0) * 0.9:
                break
            time.sleep(0.05)
        assert buf is not None, "no samples produced within 3 s"
        assert src.sample_rate == 44100
        assert buf.dtype == np.float32
        assert buf.ndim == 1
        assert np.sqrt(np.mean(buf**2)) > 0.05
    finally:
        src.stop()


def test_ring_buffer_returns_none_when_empty(tmp_path):
    p = _make_tone_mp3(tmp_path, dur=0.5)
    src = AudioSource.from_file(str(p), playback=False, buffer_seconds=1.0)
    assert src.read_latest(0.5) is None
