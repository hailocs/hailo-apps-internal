"""Shared sys.modules stubs so the voice_controlled_camera app and the
voice_processing helpers import cleanly in a headless, device-free process.

The real app pulls in native / hardware-bound dependencies at *import time*
(OpenCV, sounddevice, webrtcvad, Piper TTS, the HailoRT ``hailo_platform`` and
``hailo_platform.genai`` LLM/VLM/Speech2Text backends). None of those are
available — or desirable — in a pure-Python unit-test run, so we register
lightweight stand-ins in ``sys.modules`` *before* the app module is imported.

Import this module (``from . import _stubs; _stubs.install()``) at the very top
of any test file that needs to import the app, before importing the app itself.
"""

import sys
import types
from unittest.mock import MagicMock


def _make_pkg(name: str) -> types.ModuleType:
    """Create an importable *package* (has ``__path__``) stub."""
    mod = types.ModuleType(name)
    mod.__path__ = []  # marks it as a package so submodule imports work
    sys.modules[name] = mod
    return mod


def install() -> None:
    """Register all heavy/native module stubs (idempotent)."""
    # Simple native modules -> plain MagicMock is enough.
    for name in ("cv2", "sounddevice", "webrtcvad"):
        sys.modules.setdefault(name, MagicMock())

    # Piper TTS is imported as ``from piper import PiperVoice`` AND
    # ``from piper.voice import SynthesisConfig`` -> needs to be a package.
    if "piper" not in sys.modules:
        piper = _make_pkg("piper")
        piper.PiperVoice = MagicMock()
        piper_voice = _make_pkg("piper.voice")
        piper_voice.SynthesisConfig = MagicMock()
        piper_voice.PiperVoice = MagicMock()

    # HailoRT platform + GenAI backends.
    if "hailo_platform" not in sys.modules:
        hp = types.ModuleType("hailo_platform")
        hp.VDevice = MagicMock()
        sys.modules["hailo_platform"] = hp
    if "hailo_platform.genai" not in sys.modules:
        hpg = types.ModuleType("hailo_platform.genai")
        for sym in ("LLM", "VLM", "Speech2Text", "Speech2TextTask", "TextToSpeech"):
            setattr(hpg, sym, MagicMock())
        sys.modules["hailo_platform.genai"] = hpg
