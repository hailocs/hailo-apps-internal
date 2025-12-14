"""
Audio Recorder module.

Handles microphone recording and audio processing using sounddevice.
"""

import logging
from datetime import datetime
import wave
import numpy as np
import sounddevice as sd
from typing import Optional

from hailo_apps.python.core.common.defines import TARGET_SR, CHUNK_SIZE
from .audio_diagnostics import AudioDiagnostics

# Setup logger
logger = logging.getLogger(__name__)


class AudioRecorder:
    """
    Handles recording from the microphone and processing the audio.

    This class manages the sounddevice stream to capture audio from the
    specified or auto-detected input device. It converts the raw audio
    into a format suitable for the speech-to-text model (float32 mono 16kHz little-endian).
    """

    def __init__(self, device_id: Optional[int] = None, debug: bool = False):
        """
        Initialize the recorder.

        Args:
            device_id (Optional[int]): Device ID to use. If None, auto-detects best device.
            debug (bool): If True, saves recorded audio to WAV files.
        """
        self.audio_frames = []
        self.is_recording = False
        self.debug = debug
        self.recording_counter = 0
        self.stream = None

        # Select device
        if device_id is None:
            self.device_id, _ = AudioDiagnostics.auto_detect_devices()
            if self.device_id is None:
                logger.warning("No input device found during auto-detection. Will use system default.")
        else:
            self.device_id = device_id

        logger.debug(f"Initialized AudioRecorder with device_id={self.device_id}")

    def start(self):
        """Start recording from the microphone."""
        self.audio_frames = []
        self.is_recording = True

        try:
            self.stream = sd.InputStream(
                samplerate=TARGET_SR,
                blocksize=CHUNK_SIZE,
                device=self.device_id,
                channels=1,
                dtype='float32',
                callback=self._callback
            )
            self.stream.start()
            logger.debug("Recording started")
        except Exception as e:
            logger.error(f"Failed to start recording stream: {e}")
            self.is_recording = False
            raise RuntimeError(
                f"Could not start recording on device {self.device_id}. "
                "Check if microphone is connected and not in use."
            ) from e

    def stop(self) -> np.ndarray:
        """
        Stops the recording and processes the audio.

        Returns:
            np.ndarray: The processed audio data as a float32 mono 16kHz
                        little-endian NumPy array.
        """
        if not self.is_recording:
            return np.array([], dtype=np.float32)

        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        self.is_recording = False

        if not self.audio_frames:
            return np.array([], dtype=np.float32)

        # Concatenate frames
        audio_data = np.concatenate(self.audio_frames, axis=0)

        # Flatten if necessary (handle (N, 1) shape from sounddevice)
        if audio_data.ndim > 1:
            audio_data = audio_data.flatten()

        # Ensure the audio data is in little-endian format
        audio_le = audio_data.astype('<f4')

        # Save a copy for debugging if enabled
        if self.debug:
            self._save_debug_audio(audio_le)

        return audio_le

    def _save_debug_audio(self, audio_data: np.ndarray):
        """
        Save the recorded audio to a WAV file for debugging purposes.

        Args:
            audio_data (np.ndarray): Processed audio data to save.
        """
        try:
            # Generate a unique filename with a timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.recording_counter += 1
            filename = f"debug_audio_{timestamp}_{self.recording_counter:03d}.wav"

            # Convert float32 audio back to int16 for WAV file compatibility
            audio_int16 = (audio_data * 32767).astype(np.int16)

            # Save as a WAV file
            with wave.open(filename, 'wb') as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)  # 16-bit
                wav_file.setframerate(TARGET_SR)
                wav_file.writeframes(audio_int16.tobytes())

            logger.debug("Audio saved to %s", filename)

        except Exception as e:
            logger.warning("Failed to save debug audio: %s", e)

    def close(self):
        """Release resources."""
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None
        logger.debug("Audio recorder closed")

    def _callback(self, indata, frames, time, status):
        """
        Stream callback. Appends incoming audio to the frames buffer.
        """
        if status:
            logger.debug(f"Audio callback status: {status}")

        if self.is_recording:
            self.audio_frames.append(indata.copy())
