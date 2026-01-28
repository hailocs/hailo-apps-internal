"""
Audio Player module.

Handles audio playback using sounddevice OutputStream for continuous streaming.
"""

import logging
import os
import queue
import threading
import time
import wave
from typing import Optional, Union

# Check dependencies before importing them
from .audio_diagnostics import check_voice_dependencies
check_voice_dependencies()

import numpy as np
import sounddevice as sd

from hailo_apps.python.core.common.defines import TARGET_PLAYBACK_SR, TARGET_SR
from .audio_diagnostics import AudioDiagnostics

# Setup logger
logger = logging.getLogger(__name__)

# Audio chunk size for writing (smaller = more responsive, larger = less jitter)
WRITE_CHUNK_SIZE = 8192  # ~0.5 seconds at 16kHz


class AudioPlayer:
    """
    Handles audio playback using sounddevice OutputStream with a persistent worker thread.

    This implementation uses a background thread to write to the OutputStream.
    Crucially, it keeps the stream OPEN and writes silence when no audio is available.
    This prevents:
    1. Jitter/Latency from opening/closing streams.
    2. ALSA client churn (multiple clients appearing).
    3. Buffer underruns (which happen easily with Python callbacks on some systems).
    """

    def _resample_numpy(self, data: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
        """
        Resample audio data using linear interpolation.

        Args:
            data (np.ndarray): Audio data usually float32.
            orig_sr (int): Original sample rate.
            target_sr (int): Target sample rate.

        Returns:
            np.ndarray: Resampled data.
        """
        if orig_sr == target_sr:
            return data

        duration = len(data) / orig_sr
        target_len = int(duration * target_sr)

        x_old = np.linspace(0, duration, len(data))
        x_new = np.linspace(0, duration, target_len)

        # Handle multi-channel resampling if input is already multi-channel
        if data.ndim == 2 and data.shape[1] > 1:
            resampled = np.zeros((target_len, data.shape[1]), dtype=data.dtype)
            for ch in range(data.shape[1]):
                resampled[:, ch] = np.interp(x_new, x_old, data[:, ch])
            return resampled
        else:
            return np.interp(x_new, x_old, data.flatten()).astype(data.dtype)


    def __init__(self, device_id: Optional[int] = None):
        """
        Initialize the player.

        Args:
            device_id (Optional[int]): Device ID to use. If None, uses saved preferences
                                     or auto-detects best device.
        """
        self.stream = None
        self.queue = queue.Queue()
        self._playback_thread = None
        self._stop_event = threading.Event()
        self._stream_lock = threading.Lock()
        self._is_writing = False

        # Suppress stderr at startup
        self._devnull_fd = None
        self._original_stderr_fd = None

        # Select device
        if device_id is None:
            _, self.device_id = AudioDiagnostics.get_preferred_devices()
            if self.device_id is None:
                logger.warning("No output device found. Will use system default.")
        else:
            self.device_id = device_id

        logger.debug("Initialized AudioPlayer with device_id=%s", self.device_id)

        # Start persistent playback worker
        self._playback_thread = threading.Thread(target=self._playback_worker, daemon=True)
        self._playback_thread.start()

    @property
    def is_playing(self) -> bool:
        """Check if audio is currently being played."""
        return not self.queue.empty() or self._is_writing

    def _create_stream(self):
        """Create a new output stream."""
        try:
            # Query device info
            try:
                device_info = sd.query_devices(self.device_id)
            except Exception:
                self.device_id = None
                device_info = sd.query_devices(kind='output')

            channels = device_info.get('max_output_channels', 1)
            if channels > 2:
                channels = 2

            stream_sr = TARGET_PLAYBACK_SR

            logger.debug("Creating output stream: device=%s, channels=%d, rate=%d",
                         self.device_id, channels, stream_sr)

            stream = sd.OutputStream(
                samplerate=stream_sr,
                device=self.device_id,
                channels=channels,
                dtype='float32',
                blocksize=WRITE_CHUNK_SIZE,
                latency=0.5 # Relaxed latency for stability
            )
            stream.start()
            logger.info("Audio output stream started.")
            return stream

        except Exception as e:
            logger.error("Failed to initialize audio stream: %s", e)
            raise

    def _playback_worker(self):
        """
        Worker thread that writes to the OutputStream.
        Maintains the stream active by writing silence when idle.
        """
        self._suppress_stderr()

        # Silence chunk to keep stream alive (e.g., 50ms)
        silence_size = int(TARGET_PLAYBACK_SR * 0.05)
        silence_chunk = None # Will be created once we know channels

        try:
            # Initialize stream once
            with self._stream_lock:
                try:
                    self.stream = self._create_stream()
                except Exception:
                    logger.error("Worker failed to create stream on startup.")
                    return

            while not self._stop_event.is_set():
                try:
                    # 1. Try to get data from queue (non-blocking)
                    try:
                        data = self.queue.get_nowait()
                    except queue.Empty:
                        data = None

                    # 2. Check for sentinel (shutdown)
                    if data is None and not self.queue.empty():
                         pass

                    if data is None:
                        # Queue is empty.
                        # Check buffer status before writing silence to avoid gaps.
                        if self.stream and self.stream.active:
                            try:
                                # write_available: number of frames that can be written without blocking.
                                # If this is small, the buffer is full (audio playing).
                                # If this is large, the buffer is draining/empty.
                                available = self.stream.write_available

                                # Threshold: 4000 frames is ~0.25s at 16k.
                                # If we have fewer than 4000 frames available to WRITE,
                                # it means we have > (Buffer_Size - 0.25s) FULL of audio.
                                # Safe to wait for next chunk.


                                if available < 4000:
                                    time.sleep(0.02)
                                    continue

                            except Exception:
                                pass

                            # If buffer is draining (available is high), write silence to prevent underrun.
                            if silence_chunk is None or silence_chunk.shape[0] != silence_size or (self.stream.channels > 1 and silence_chunk.shape[1] != self.stream.channels):
                                channels = self.stream.channels
                                if channels > 1:
                                    silence_chunk = np.zeros((silence_size, channels), dtype=np.float32)
                                else:
                                    silence_chunk = np.zeros((silence_size,), dtype=np.float32)

                            self.stream.write(silence_chunk)
                        else:
                             time.sleep(0.1)
                        continue

                    # 3. We have data
                    if data is None:
                         continue

                    # 4. Play the data
                    if self.stream and self.stream.active:
                         # Handle channel expansion
                        if self.stream.channels > 1 and (data.ndim == 1 or data.shape[1] == 1):
                            data = data.flatten()
                            data = np.tile(data[:, np.newaxis], (1, self.stream.channels))
                        elif data.ndim == 1 and self.stream.channels == 1:
                             pass

                        # Write (blocking if buffer full)
                        self._is_writing = True
                        try:
                            self.stream.write(data)
                        finally:
                            self._is_writing = False

                    self.queue.task_done()

                except Exception as e:
                   # logger.error(f"Error in playback worker: {e}")
                    # Try to recreate stream if it died?
                    if self.stream is None or not self.stream.active:
                        with self._stream_lock:
                             try:
                                 if self.stream:
                                     try:
                                         self.stream.close()
                                     except: pass
                                 self.stream = self._create_stream()
                                 # Reset silence chunk just in case channels changed
                                 silence_chunk = None
                             except Exception:
                                 time.sleep(1) # Backoff

        finally:
            with self._stream_lock:
                if self.stream:
                    try:
                        self.stream.stop()
                        self.stream.close()
                    except: pass
                    self.stream = None
            self._restore_stderr()


    def play(self, audio_data: Union[str, np.ndarray], block: bool = False):
        """
        Queue audio data for playback.

        Args:
            audio_data (Union[str, np.ndarray]): Path to WAV file or numpy array.
            block (bool): If True, blocks until this specific audio data is consumed.
                          (NOTE: approximate blocking by checking queue emptiness)
        """
        input_sr = TARGET_SR
        data = None

        if isinstance(audio_data, str):
            try:
                data, fs = self._read_wav(audio_data)
                input_sr = fs
            except Exception as e:
                logger.error("Failed to read WAV file: %s", e)
                return
        elif isinstance(audio_data, np.ndarray):
            data = audio_data
            input_sr = TARGET_SR
        else:
            logger.error("Unsupported audio data type: %s", type(audio_data))
            return

        # Ensure float32
        if data.dtype != np.float32:
            data = data.astype(np.float32)

        # Resample
        target_sr = TARGET_PLAYBACK_SR
        if input_sr != target_sr:
            try:
                data = self._resample_numpy(data, input_sr, target_sr)
            except Exception as e:
                logger.error("Resampling failed: %s", e)
                return

        # Enqueue
        self.queue.put(data)

        if block:
            while not self.queue.empty():
                time.sleep(0.1)


    def stop(self):
        """
        Clear the playback queue.
        """
        # Drain queue
        try:
            while True:
                self.queue.get_nowait()
                self.queue.task_done()
        except queue.Empty:
            pass

    def close(self):
        """Shutdown the player and release resources."""
        self._stop_event.set()
        # Wait for worker
        if self._playback_thread:
            self._playback_thread.join(timeout=1.0)

        self.stop()
        with self._stream_lock:
            if self.stream:
                try:
                    self.stream.stop()
                    self.stream.close()
                except Exception:
                    pass
                self.stream = None

    def _suppress_stderr(self):
        """Redirect stderr to /dev/null."""
        try:
            self._original_stderr_fd = os.dup(2)
            self._devnull_fd = os.open(os.devnull, os.O_WRONLY)
            os.dup2(self._devnull_fd, 2)
        except Exception:
            pass

    def _restore_stderr(self):
        """Restore stderr."""
        try:
            if self._original_stderr_fd is not None:
                os.dup2(self._original_stderr_fd, 2)
                os.close(self._original_stderr_fd)
                self._original_stderr_fd = None
            if self._devnull_fd is not None:
                os.close(self._devnull_fd)
                self._devnull_fd = None
        except Exception:
            pass

    def _read_wav(self, file_path: str) -> tuple[np.ndarray, int]:
        """Read WAV file to numpy array."""
        with wave.open(file_path, 'rb') as wf:
            fs = wf.getframerate()
            n_frames = wf.getnframes()
            data = wf.readframes(n_frames)

            width = wf.getsampwidth()
            if width == 2:
                dtype = np.int16
            elif width == 4:
                dtype = np.float32
            else:
                raise ValueError(f"Unsupported sample width: {width}")

            audio = np.frombuffer(data, dtype=dtype)

            if dtype == np.int16:
                audio = audio.astype(np.float32) / 32768.0

            return audio, fs
