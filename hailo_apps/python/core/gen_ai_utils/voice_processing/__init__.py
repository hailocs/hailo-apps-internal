"""
Voice Processing Module.

Provides components for speech-to-text, text-to-speech, and audio recording.
"""

from .audio_recorder import AudioRecorder
from .interaction import VoiceInteractionManager
from .speech_to_text import SpeechToTextProcessor
from .text_to_speech import TextToSpeechProcessor

__all__ = [
    "AudioRecorder",
    "VoiceInteractionManager",
    "SpeechToTextProcessor",
    "TextToSpeechProcessor",
]
