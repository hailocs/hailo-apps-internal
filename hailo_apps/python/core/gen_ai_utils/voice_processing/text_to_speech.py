"""
Text-to-Speech module for Hailo Voice Assistant.

This module handles speech synthesis using Piper TTS.
"""

import os
import queue
import re
import subprocess
import tempfile
import threading
import time
import wave
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from typing import Optional

from piper import PiperVoice
from piper.voice import SynthesisConfig

from hailo_apps.python.core.common.defines import (
    TEMP_WAV_DIR,
    TTS_JSON_PATH,
    TTS_LENGTH_SCALE,
    TTS_MODEL_NAME,
    TTS_MODELS_DIR,
    TTS_NOISE_SCALE,
    TTS_ONNX_PATH,
    TTS_VOLUME,
    TTS_W_SCALE,
)


def check_piper_model_installed(onnx_path: str = TTS_ONNX_PATH, json_path: str = TTS_JSON_PATH) -> bool:
    """
    Check if Piper TTS model files are installed.

    Args:
        onnx_path (str): Path to the Piper TTS ONNX model file.
        json_path (str): Path to the Piper TTS JSON config file.

    Returns:
        bool: True if both model files exist, False otherwise.

    Raises:
        FileNotFoundError: If model files are not found, with reference to documentation.
    """
    onnx_exists = os.path.exists(onnx_path)
    json_exists = os.path.exists(json_path)

    if not onnx_exists or not json_exists:
        missing_files = []
        if not onnx_exists:
            missing_files.append(onnx_path)
        if not json_exists:
            missing_files.append(json_path)

        error_msg = f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                     PIPER TTS MODEL NOT FOUND                                ║
╚══════════════════════════════════════════════════════════════════════════════╝
Please install the Piper TTS model before running this application.
For detailed installation instructions, see:
  hailo_apps/python/core/gen_ai_utils/voice_processing/README.md
"""
        raise FileNotFoundError(error_msg)

    return True


def clean_text_for_tts(text: str) -> str:
    """
    Clean text for TTS to prevent artifacts and noise.

    Removes markdown formatting, special symbols, and characters that often cause
    issues with Piper TTS (like white noise).

    Args:
        text (str): Input text.

    Returns:
        str: Cleaned text safe for TTS.
    """
    if not text:
        return ""

    # 1. Remove Markdown formatting
    # Remove bold/italic asterisks/underscores (*, **, _, __)
    text = re.sub(r"[*_]{1,3}", "", text)
    # Remove code block backticks
    text = re.sub(r"`+", "", text)
    # Remove headers (#)
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    # Remove links [text](url) -> text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)

    # 2. Remove noisy characters
    # Filter out characters that are not:
    # - Alphanumeric (a-z, A-Z, 0-9, including accents/unicode letters)
    # - Basic punctuation (.,!?:;'-)
    # - Whitespace
    # - Currency symbols ($€£)
    # - Percent (%)
    # This regex keeps "word characters", spaces, and listed punctuation.
    # \w includes alphanumeric + underscore, but we stripped underscore above if it was markdown.
    # We allow underscore inside words if any remain, or we can be stricter.
    # Let's be permissive with \w but strip specific problematic symbols.

    # Common symbols causing noise: ~ @ ^ | \ < > { } [ ] #
    text = re.sub(r"[~@^|\\<>{}\[\]#]", " ", text)

    # 3. Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()

    return text


class TextToSpeechProcessor:
    """
    Handles text-to-speech synthesis and playback using Piper.
    """

    def __init__(self, onnx_path: str = TTS_ONNX_PATH):
        """
        Initialize the TextToSpeechProcessor.

        Args:
            onnx_path (str): Path to the Piper TTS ONNX model.

        Raises:
            FileNotFoundError: If Piper model files are not found.
        """
        # Check if Piper model is installed
        json_path = onnx_path + ".json"
        check_piper_model_installed(onnx_path, json_path)

        # Suppress Piper warning messages
        with redirect_stderr(StringIO()):
            self.piper_voice = PiperVoice.load(onnx_path)
            self.syn_config = SynthesisConfig(
                volume=TTS_VOLUME,
                length_scale=TTS_LENGTH_SCALE,
                noise_scale=TTS_NOISE_SCALE,
                noise_w_scale=TTS_W_SCALE,
                normalize_audio=True,
            )

        self.speech_queue = queue.Queue()
        self.current_speech_process = None
        self._speech_lock = threading.Lock()
        self.generation_id = 0
        self._gen_id_lock = threading.Lock()
        self._interrupted = threading.Event()
        self._running = True

        # Start the background worker for speech synthesis and playback
        self.speech_thread = threading.Thread(target=self._speech_worker, daemon=True)
        self.speech_thread.start()

    def interrupt(self):
        """
        Interrupts any ongoing speech.

        Stops current playback, increments generation ID to invalidate stale chunks,
        and clears the queue.
        """
        self._interrupted.set()
        with self._gen_id_lock:
            self.generation_id += 1

        with self._speech_lock:
            if self.current_speech_process:
                try:
                    # Terminate the 'aplay' process to stop audio instantly
                    self.current_speech_process.kill()
                except OSError:
                    pass
                self.current_speech_process = None

        # Drain the queue of any stale audio chunks
        while not self.speech_queue.empty():
            try:
                self.speech_queue.get_nowait()
            except queue.Empty:
                continue

    def queue_text(self, text: str, gen_id: Optional[int] = None):
        """
        Add text to the speech queue.

        Args:
            text (str): The text to speak.
            gen_id (Optional[int]): Generation ID. If None, uses current ID.
        """
        if gen_id is None:
            with self._gen_id_lock:
                gen_id = self.generation_id
        self.speech_queue.put((gen_id, text))

    def chunk_and_queue(self, buffer: str, gen_id: int, is_first_chunk: bool) -> str:
        """
        Chunk text buffer based on delimiters and queue for speech.

        Args:
            buffer (str): The accumulated text buffer.
            gen_id (int): The generation ID for the speech.
            is_first_chunk (bool): Whether this is the first chunk being processed.

        Returns:
            str: The remaining buffer after queuing complete chunks.
        """
        # Use a comma as a delimiter only for the first chunk for faster response.
        delimiters = ['.', '?', '!']
        if is_first_chunk:
            delimiters.append(',')

        while True:
            # Find the first occurrence of any delimiter.
            positions = {buffer.find(d): d for d in delimiters if buffer.find(d) != -1}
            if not positions:
                break  # No delimiters found

            first_pos = min(positions.keys())
            chunk = buffer[:first_pos + 1]

            if chunk.strip():
                self.queue_text(chunk.strip(), gen_id)

            buffer = buffer[first_pos + 1:]

        return buffer

    def get_current_gen_id(self) -> int:
        """Get the current generation ID."""
        with self._gen_id_lock:
            return self.generation_id

    def clear_interruption(self):
        """Clear the interruption flag."""
        self._interrupted.clear()

    def stop(self):
        """Stop the worker thread and cleanup."""
        self._running = False
        if self.speech_thread.is_alive():
            self.speech_thread.join(timeout=1.0)
        self.interrupt()

    def _speech_worker(self):
        """
        Background thread that processes the speech queue.
        """
        while self._running:
            try:
                gen_id, text = self.speech_queue.get(timeout=0.1)

                # If an interruption is signaled, discard this chunk
                if self._interrupted.is_set():
                    self.speech_queue.task_done()
                    continue

                # If this chunk is from a previous generation, discard it
                with self._gen_id_lock:
                    if gen_id != self.generation_id:
                        self.speech_queue.task_done()
                        continue

                self._synthesize_and_play(text)
                self.speech_queue.task_done()

            except queue.Empty:
                time.sleep(0.1)

    def _synthesize_and_play(self, text: str):
        """
        Synthesizes text to audio and plays it using aplay.

        Args:
            text (str): The text to be spoken.
        """
        # Clean text before synthesis to prevent artifacts
        text = clean_text_for_tts(text)
        if not text.strip():
            return

        playback_process = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".wav", delete=True, dir=TEMP_WAV_DIR
            ) as temp_wav_file:
                temp_wav_path = temp_wav_file.name
                with wave.open(temp_wav_path, "wb") as wav_file:
                    with redirect_stderr(StringIO()):
                        self.piper_voice.synthesize_wav(
                            text, wav_file, self.syn_config
                        )

                with self._speech_lock:
                    # Check if we should still play (might have been interrupted during synthesis)
                    if self._interrupted.is_set():
                        return

                    self.current_speech_process = subprocess.Popen(
                        ["aplay", temp_wav_path],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    playback_process = self.current_speech_process

                # Wait for playback to finish
                if playback_process:
                    playback_process.wait()

        finally:
            with self._speech_lock:
                if (
                    self.current_speech_process
                    and playback_process
                    and self.current_speech_process.pid == playback_process.pid
                ):
                    self.current_speech_process = None
