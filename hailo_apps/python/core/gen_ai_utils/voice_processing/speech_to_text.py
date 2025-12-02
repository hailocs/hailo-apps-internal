"""
Speech-to-Text module for Hailo Voice Assistant.

This module handles the transcription of audio using Hailo's Speech2Text model.
"""

import logging
import time
from typing import List, Optional

import numpy as np
from hailo_platform import VDevice
from hailo_platform.genai import Speech2Text, Speech2TextTask

from hailo_apps.python.core.common.core import get_resource_path
from hailo_apps.python.core.common.defines import (
    RESOURCES_MODELS_DIR_NAME,
    WHISPER_MODEL_NAME_H10,
)

# Setup logger
logger = logging.getLogger(__name__)


class SpeechToTextProcessor:
    """
    Handles speech-to-text transcription using Hailo's AI models.

    This class encapsulates the Speech2Text functionality, providing a simplified
    interface for transcribing audio data.
    """

    def __init__(self, vdevice: VDevice, model_name: str = WHISPER_MODEL_NAME_H10):
        """
        Initialize the SpeechToTextProcessor.

        Args:
            vdevice (VDevice): The Hailo VDevice instance to use.
            model_name (str): Name of the Whisper model to load. Defaults to WHISPER_MODEL_NAME_H10.
        """
        model_path = str(
            get_resource_path(
                pipeline_name=None,
                resource_type=RESOURCES_MODELS_DIR_NAME,
                model=model_name,
            )
        )
        logger.info("Initializing Speech2Text with model: %s", model_name)
        self.speech2text = Speech2Text(vdevice, model_path)

    def transcribe(
        self,
        audio_data: np.ndarray,
        language: str = "en",
        timeout_ms: int = 15000,
    ) -> str:
        """
        Transcribe audio data to text.

        Args:
            audio_data (np.ndarray): The raw audio data to transcribe.
            language (str): The language of the audio. Defaults to "en".
            timeout_ms (int): Timeout in milliseconds for the transcription. Defaults to 15000.

        Returns:
            str: The transcribed text.
        """
        segments = self.speech2text.generate_all_segments(
            audio_data=audio_data,
            task=Speech2TextTask.TRANSCRIBE,
            language=language,
            timeout_ms=timeout_ms,
        )

        if not segments:
            logger.debug("No transcription segments returned")
            return ""

        # Log first segment for debugging/feedback
        logger.debug("Transcription: text='%s', time=%.2fs", segments[0].text, segments[0].end_sec)

        full_text = "".join([seg.text for seg in segments])
        logger.debug("Full transcription: %d segments, %d chars", len(segments), len(full_text))
        return full_text

