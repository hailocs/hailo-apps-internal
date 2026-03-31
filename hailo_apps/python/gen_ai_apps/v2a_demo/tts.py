"""
Text-to-Speech Engine

Interface:
    - __init__(): Initialize the engine
    - run(text): Synthesize text, return (audio_array, sample_rate)
    - close(): Clean up resources

To customize:
Replace the implementation in `__init__`, `run`, and `close` methods.
"""

import logging
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
from piper import PiperVoice

logger = logging.getLogger("v2a_demo")

RESOURCES_DIR = Path(__file__).resolve().parent / "resources"
TTS_MODEL_PATH = str(RESOURCES_DIR / "en_US-joe-medium.onnx")
TTS_CONFIG_PATH = str(RESOURCES_DIR / "en_US-joe-medium.onnx.json")

class TTSEngine:
    """Text-to-Speech engine using Piper."""

    def __init__(self):
        model_path = Path(TTS_MODEL_PATH).resolve()
        if not model_path.exists():
            raise FileNotFoundError(f"Piper model not found: {model_path}")

        config_path = Path(TTS_CONFIG_PATH).resolve()
        if not config_path.exists():
            raise FileNotFoundError(f"Piper config not found: {config_path}")

        self.voice = PiperVoice.load(str(model_path), config_path=str(config_path))

    def run(self, text: str) -> Optional[Tuple[np.ndarray, int]]:
        """Synthesize text to audio.

        Returns:
            (audio_array, sample_rate) or None if synthesis produced no audio.
        """
        audio_chunks = list(self.voice.synthesize(text))
        if not audio_chunks:
            logger.warning("TTS produced no audio (text length=%d)", len(text))
            return None

        sample_rate = audio_chunks[0].sample_rate
        audio_array = np.concatenate([c.audio_float_array for c in audio_chunks])
        return audio_array, sample_rate

    def close(self):
        self.voice = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
