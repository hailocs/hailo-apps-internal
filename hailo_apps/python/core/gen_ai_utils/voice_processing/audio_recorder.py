"""
Audio Recorder module.

Handles microphone recording and audio processing.
"""

import logging
from datetime import datetime
import wave
import numpy as np
import pyaudio
from hailo_apps.python.core.common.defines import TARGET_SR, CHUNK_SIZE

# Setup logger
logger = logging.getLogger(__name__)


class AudioRecorder:
    """
    Handles recording from the microphone and processing the audio.

    This class manages the PyAudio stream to capture audio from the default
    input device. It converts the raw audio into a format suitable for the
    speech-to-text model (float32 mono 16kHz little-endian).
    """

    def __init__(self, debug: bool = False):
        """
        Initialize the recorder.

        Args:
            debug (bool): If True, saves recorded audio to WAV files.
        """
        self.p = pyaudio.PyAudio()
        self.stream = None
        self.audio_frames = []
        self.is_recording = False
        self.debug = debug
        self.recording_counter = 0

    def start(self):
        """Start recording from the default microphone."""
        self.audio_frames = []
        self.is_recording = True
        self.stream = self.p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=TARGET_SR,
            input=True,
            frames_per_buffer=CHUNK_SIZE,
            stream_callback=self._callback
        )
        self.stream.start_stream()
        logger.debug("Recording started")

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
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None
        self.is_recording = False

        if not self.audio_frames:
            return np.array([], dtype=np.float32)

        # 1. Convert raw bytes to a NumPy array of 16-bit integers.
        audio_s16 = np.frombuffer(b''.join(self.audio_frames), dtype=np.int16)

        # 2. Convert from 16-bit integers to float32, normalized between -1 and 1.
        audio_f32 = audio_s16.astype(np.float32) / 32768.0

        # 4. Ensure the audio data is in little-endian format, as expected by the model.
        audio_le = audio_f32.astype('<f4')

        # 5. Save a copy for debugging if enabled.
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
            # Generate a unique filename with a timestamp.
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.recording_counter += 1
            filename = f"debug_audio_{timestamp}_{self.recording_counter:03d}.wav"

            # Convert float32 audio back to int16 for WAV file compatibility.
            audio_int16 = (audio_data * 32767).astype(np.int16)

            # Save as a WAV file.
            with wave.open(filename, 'wb') as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)  # 16-bit
                wav_file.setframerate(TARGET_SR)
                wav_file.writeframes(audio_int16.tobytes())

            logger.info("Audio saved to %s", filename)

        except Exception as e:
            logger.warning("Failed to save debug audio: %s", e)

    def close(self):
        """Release PyAudio resources."""
        if self.p:
            self.p.terminate()
            self.p = None
            logger.debug("Audio recorder closed")

    def _callback(self, in_data, frame_count, time_info, status):
        """
        PyAudio stream callback. Appends incoming raw audio to the frames buffer.
        """
        if self.is_recording:
            self.audio_frames.append(in_data)
        return (in_data, pyaudio.paContinue)

