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
import sys
from pathlib import Path
from hailo_platform import VDevice
from hailo_platform.genai import Speech2Text, Speech2TextTask

try:
    from hailo_apps.python.core.common.core import resolve_hef_path
    from hailo_apps.python.core.common.defines import HAILO10H_ARCH, V2A_DEMO_APP
except ImportError:
    repo_root = None
    for p in Path(__file__).resolve().parents:
        if (p / "hailo_apps" / "config" / "config_manager.py").exists():
            repo_root = p
            break
    if repo_root is not None:
        sys.path.insert(0, str(repo_root))
    from hailo_apps.python.core.common.core import resolve_hef_path
    from hailo_apps.python.core.common.defines import HAILO10H_ARCH, V2A_DEMO_APP

class STTEngine:
    """Speech-to-Text engine using Hailo Speech2Text."""

    DEFAULT_LANGUAGE = "en"

    def __init__(self, vdevice: VDevice):
        model_path = resolve_hef_path(
            hef_path="Whisper-Base",
            app_name=V2A_DEMO_APP,
            arch=HAILO10H_ARCH,
        )
        if model_path is None:
            raise RuntimeError("Failed to resolve HEF path for STT model 'Whisper-Base'")
        self._speech2text = Speech2Text(vdevice, str(model_path))

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
