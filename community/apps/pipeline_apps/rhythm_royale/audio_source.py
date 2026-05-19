"""AudioSource — file or mic capture into a ring buffer, optional playback.

Producer thread fills a numpy ring buffer. Consumers (the BeatExtractor) call
`read_latest(seconds)` to copy out the most-recent samples.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass
class _RingBuffer:
    capacity: int
    data: np.ndarray
    write_idx: int = 0
    filled: int = 0
    lock: threading.Lock = None

    @classmethod
    def make(cls, capacity: int) -> "_RingBuffer":
        return cls(
            capacity=capacity,
            data=np.zeros(capacity, dtype=np.float32),
            lock=threading.Lock(),
        )

    def write(self, chunk: np.ndarray) -> None:
        n = len(chunk)
        if n == 0:
            return
        with self.lock:
            end = self.write_idx + n
            if end <= self.capacity:
                self.data[self.write_idx:end] = chunk
            else:
                first = self.capacity - self.write_idx
                self.data[self.write_idx:] = chunk[:first]
                self.data[: n - first] = chunk[first:]
            self.write_idx = (self.write_idx + n) % self.capacity
            self.filled = min(self.capacity, self.filled + n)

    def read_latest(self, n: int) -> Optional[np.ndarray]:
        with self.lock:
            if self.filled < n:
                return None
            start = (self.write_idx - n) % self.capacity
            if start + n <= self.capacity:
                return self.data[start:start + n].copy()
            first = self.capacity - start
            out = np.empty(n, dtype=np.float32)
            out[:first] = self.data[start:]
            out[first:] = self.data[: n - first]
            return out


class AudioSource:
    def __init__(self, sample_rate: int, buffer_seconds: float = 4.0):
        self.sample_rate = sample_rate
        self._buf = _RingBuffer.make(int(sample_rate * buffer_seconds))
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._mode: Optional[str] = None

    @classmethod
    def from_file(cls, path: str, playback: bool = True,
                  buffer_seconds: float = 4.0) -> "AudioSource":
        import soundfile as sf
        data, sr = sf.read(path, dtype="float32", always_2d=False)
        if data.ndim == 2:
            data = data.mean(axis=1).astype(np.float32)
        src = cls(sample_rate=int(sr), buffer_seconds=buffer_seconds)
        src._file_data = data
        src._playback = playback
        src._mode = "file"
        return src

    @classmethod
    def from_mic(cls, device: Optional[str] = None, sample_rate: int = 44100,
                 buffer_seconds: float = 4.0) -> "AudioSource":
        src = cls(sample_rate=sample_rate, buffer_seconds=buffer_seconds)
        src._mic_device = device
        src._mode = "mic"
        return src

    def start(self) -> None:
        if self._mode == "file":
            self._thread = threading.Thread(target=self._run_file, daemon=True)
        elif self._mode == "mic":
            self._thread = threading.Thread(target=self._run_mic, daemon=True)
        else:
            raise RuntimeError("AudioSource: use from_file() or from_mic()")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)

    def read_latest(self, seconds: float) -> Optional[np.ndarray]:
        n = int(seconds * self.sample_rate)
        return self._buf.read_latest(n)

    def _run_file(self) -> None:
        try:
            import sounddevice as sd
        except Exception:
            sd = None

        data = self._file_data
        sr = self.sample_rate
        chunk = max(1, int(sr * 0.05))
        stream = None
        if self._playback and sd is not None:
            try:
                stream = sd.OutputStream(samplerate=sr, channels=1, dtype="float32")
                stream.start()
            except Exception:
                stream = None

        try:
            i = 0
            t_next = time.monotonic()
            while not self._stop.is_set() and i < len(data):
                end = min(i + chunk, len(data))
                block = data[i:end]
                self._buf.write(block)
                if stream is not None:
                    try:
                        stream.write(block.reshape(-1, 1))
                    except Exception:
                        pass
                i = end
                t_next += chunk / sr
                sleep_s = t_next - time.monotonic()
                if sleep_s > 0:
                    time.sleep(sleep_s)
        finally:
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass

    def _run_mic(self) -> None:
        import sounddevice as sd

        def cb(indata, frames, time_info, status):
            if self._stop.is_set():
                raise sd.CallbackStop
            self._buf.write(indata[:, 0].astype(np.float32, copy=False))

        with sd.InputStream(device=self._mic_device, samplerate=self.sample_rate,
                            channels=1, dtype="float32", callback=cb):
            while not self._stop.is_set():
                time.sleep(0.05)
