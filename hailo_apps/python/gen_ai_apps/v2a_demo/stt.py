"""
Speech-to-Text Engine

Interface:
    - __init__(vdevice): Initialize the engine
    - run(audio_data) -> str: Transcribe audio to text (float32, 16kHz, mono)
    - close(): Clean up resources

To customize:
Replace the implementation in `__init__`, `run`, and `close` methods.
"""

import numpy as np
from hailo_platform import VDevice
from hailo_platform.genai import Speech2Text, Speech2TextTask

STT_MODEL_PATH = "resources/Whisper-Base.hef"

class STTEngine:
    """Speech-to-Text engine using Hailo Speech2Text."""

    DEFAULT_LANGUAGE = "en"

    def __init__(self, vdevice: VDevice):
        self._speech2text = Speech2Text(vdevice, STT_MODEL_PATH)

    def run(self, audio_data: np.ndarray, language: str = DEFAULT_LANGUAGE) -> str:
        text = self._speech2text.generate_all_text(
            task=Speech2TextTask.TRANSCRIBE,
            language=language,
            audio_data=audio_data.astype("<f4")
        )
        return text.strip()

    def close(self):
        if self._speech2text:
            self._speech2text.release()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
