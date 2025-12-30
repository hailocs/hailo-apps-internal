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
    Handles audio playback using sounddevice OutputStream.
    Uses a persistent stream and queue to ensure gapless playback of chunks.
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

        # Handle multi-channel resampling if input is already multi-channel (unlikely for TTS but possible)
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
        self._reinit_event = threading.Event()
        self._flush_event = threading.Event()
        self._stream_lock = threading.Lock()
        self._is_writing = False

        # Suppress stderr at startup and keep it suppressed for this player
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
        return self._is_writing or not self.queue.empty()

    def play(self, audio_data: Union[str, np.ndarray], block: bool = False):
        """
        Queue audio data for playback.

        Args:
            audio_data (Union[str, np.ndarray]): Path to WAV file or numpy array.
            block (bool): Ignored in this streaming implementation. Kept for API compatibility.
        """
        self._flush_event.clear()
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
            # For raw numpy arrays, we assume TARGET_SR (16kHz) as per app convention
            input_sr = TARGET_SR
        else:
            logger.error("Unsupported audio data type: %s", type(audio_data))
            return

        # Ensure float32
        if data.dtype != np.float32:
            data = data.astype(np.float32)

        # Resample to stream rate (TARGET_PLAYBACK_SR)
        # We enforce TARGET_PLAYBACK_SR for the stream to ensure compatibility with devices
        # that might play 16kHz content at 3x speed if they don't support 16kHz natively.
        target_sr = TARGET_PLAYBACK_SR

        if input_sr != target_sr:
            try:
                data = self._resample_numpy(data, input_sr, target_sr)
            except Exception as e:
                logger.error("Resampling failed: %s", e)
                return

        # Enqueue for playback
        logger.debug("Queuing audio data for playback: %d samples", len(data))
        self.queue.put(data)


    def stop(self):
        """
        Clear the playback queue and stop audio immediately.
        """
        # Clear queue
        with self.queue.mutex:
            self.queue.queue.clear()

        # Signal flush to stop current chunk playback
        self._flush_event.set()

        # Brief wait to allow worker to see the event and stop writing
        time.sleep(0.02)

    def close(self):
        """Shutdown the player and release resources."""
        self._stop_event.set()
        self._reinit_event.set()

        with self._stream_lock:
            if self.stream:
                try:
                    self.stream.abort()
                    self.stream.close()
                except Exception:
                    pass
                self.stream = None

        if self._playback_thread:
            self._playback_thread.join(timeout=1.0)

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

    def _create_stream(self):
        """Create a new output stream."""
        try:
            # query_devices can fail if the device ID is no longer valid (e.g. disconnected)
            try:
                device_info = sd.query_devices(self.device_id)
            except Exception as e:
                logger.warning("Failed to query device %s: %s. Attempting to rediscover preferred device.", self.device_id, e)

                # Try to re-detect preferred device (it might have a new ID)
                try:
                    _, new_device_id = AudioDiagnostics.get_preferred_devices()
                    if new_device_id is not None:
                        self.device_id = new_device_id
                        logger.info("Rediscovered preferred device: %s", self.device_id)
                        device_info = sd.query_devices(self.device_id)
                    else:
                        raise ValueError("No preferred device found")
                except Exception as discovery_error:
                    logger.warning("Could not rediscover preferred device: %s. Falling back to system default.", discovery_error)
                    self.device_id = None
                    device_info = sd.query_devices(kind='output')

            channels = device_info.get('max_output_channels', 1)
            # Cap channels at 2 (Stereo) for TTS to avoid expensive tiling on multi-channel virtual devices
            # PulseAudio/ALSA will handle downmixing/mapping if the physical device has more.
            if channels > 2:
                channels = 2


            logger.debug("Creating output stream for device %s with %d channels", self.device_id, channels)

            # Use TARGET_PLAYBACK_SR (standard) or device default if higher
            # 16kHz on 48kHz hardware causes 3x speedup if not resampled/negotiated.
            # We explicitly ask for TARGET_PLAYBACK_SR to match modern hardware.
            stream_sr = TARGET_PLAYBACK_SR

            # Check if device supports it? sounddevice/portaudio usually handles conversion
            # if we request a specific rate.
            # But the issue we saw is that raw ALSA `hw:` device might NOT do conversion.
            # So we must feed it what it wants (likely 48k).

            logger.debug("Creating output stream for device %s with %d channels at %d Hz",
                        self.device_id, channels, stream_sr)

            stream = sd.OutputStream(
                samplerate=stream_sr,
                device=self.device_id,
                channels=channels,
                dtype='float32',
                blocksize=WRITE_CHUNK_SIZE,
                latency=0.5  # 500ms buffer to prevent underruns
            )
            stream.start()
            logger.debug("Audio output stream created successfully (device_id=%s, active=%s, channels=%d)",
                        self.device_id, stream.active, channels)
            return stream
        except Exception as e:
            logger.error("Failed to create audio output stream (device_id=%s): %s", self.device_id, e)
            raise

    def _play_chunk(self, data: np.ndarray):
        """Helper to write a single chunk to the stream."""
        if not self.stream:
            return

        with self._stream_lock:
             # Double check stream inside lock
            if not self.stream:
                return

            self._is_writing = True
            try:
                offset = 0
                while offset < len(data):
                    if self._stop_event.is_set() or self._flush_event.is_set():
                        break

                    chunk = data[offset:offset + WRITE_CHUNK_SIZE]
                    offset += WRITE_CHUNK_SIZE

                    if self.stream and self.stream.active:
                        # Handle channel expansion
                        should_expand = self.stream.channels > 1 and (chunk.ndim == 1 or chunk.shape[1] == 1)
                        if should_expand:
                            if chunk.ndim == 1:
                                chunk = chunk.reshape(-1, 1)
                            chunk = np.tile(chunk, (1, self.stream.channels))

                        self.stream.write(chunk)
                    else:
                         # Stream died?
                         logger.warning("Stream died during write.")
                         break
                    time.sleep(0) # Yield
            except Exception as e:
                logger.error(f"Error writing audio chunk: {e}")
                raise
            finally:
                self._is_writing = False

    def _playback_worker(self):
        """Worker thread that writes to the OutputStream on-demand."""
        # Suppress stderr for the entire worker thread lifetime
        self._suppress_stderr()


        # Idle timeout to keep stream open for a bit between chunks (e.g. between sentences)
        IDLE_TIMEOUT = 3.0


        try:
            while not self._stop_event.is_set():
                try:
                    # Wait for data.
                    # If stream is OPEN, use short timeout to detect idle.
                    # If stream is CLOSED, block (with long timeout/loop to check stop_event).
                    timeout = IDLE_TIMEOUT if self.stream else 0.5

                    try:
                        data = self.queue.get(timeout=timeout)
                    except queue.Empty:
                        # Timeout occurred
                        if self.stream:
                            # Stream was open but went idle -> Close it
                            with self._stream_lock:
                                logger.debug("Audio stream idle, closing.")
                                try:
                                    self.stream.stop()
                                    self.stream.close()
                                except Exception as e:
                                    logger.warning(f"Error closing stream: {e}")
                                self.stream = None
                        continue

                    # We have data! Ensure stream is open.
                    if not self.stream:
                         with self._stream_lock:
                             if not self.stream:
                                 logger.debug("Opening audio stream on-demand...")
                                 try:
                                     self.stream = self._create_stream()
                                     self._reinit_event.clear()
                                 except Exception as e:
                                     logger.error(f"Failed to open stream: {e}")
                                     self.queue.task_done()
                                     continue

                    # Play the data
                    try:
                        self._play_chunk(data)
                    except Exception as e:
                        logger.error(f"Playback error: {e}")
                        # Maybe force close stream?
                        with self._stream_lock:
                             if self.stream:
                                try:
                                    self.stream.close()
                                except Exception:
                                    pass
                                self.stream = None

                    self.queue.task_done()

                except Exception as e:
                    logger.error(f"Unexpected error in playback loop: {e}")
                    time.sleep(0.1)

            # Cleanup at end of loop
            with self._stream_lock:
                if self.stream:
                    try:
                        self.stream.close()
                    except Exception:
                        pass
                    self.stream = None

        finally:
            self._restore_stderr()

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
