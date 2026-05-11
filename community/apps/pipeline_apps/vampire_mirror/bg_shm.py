"""Shared-memory helpers for the vampire mirror background service.

Thin wrappers around ``multiprocessing.shared_memory`` that expose a numpy
view backed by the shm segment.  ``create()`` allocates a new segment;
``attach()`` opens an existing one by name.  ``close_and_unlink()`` should
be called by the creator on shutdown; ``close()`` is enough for attachers.
"""
from __future__ import annotations

from multiprocessing import shared_memory

import numpy as np


class ShmNdarray:
    """numpy ndarray backed by a named shared-memory segment."""

    def __init__(self, shm: shared_memory.SharedMemory, ndarray: np.ndarray, owned: bool) -> None:
        self._shm = shm
        self.ndarray = ndarray
        self._owned = owned
        self._closed = False
        self._unlinked = False

    @classmethod
    def create(cls, name: str, shape: tuple[int, ...], dtype: np.dtype) -> "ShmNdarray":
        nbytes = int(np.prod(shape)) * np.dtype(dtype).itemsize
        shm = shared_memory.SharedMemory(name=name, create=True, size=nbytes)
        try:
            arr = np.ndarray(shape, dtype=dtype, buffer=shm.buf)
            arr[:] = 0
        except Exception:
            shm.close()
            try:
                shm.unlink()
            except FileNotFoundError:
                pass
            raise
        return cls(shm, arr, owned=True)

    @classmethod
    def attach(cls, name: str, shape: tuple[int, ...], dtype: np.dtype) -> "ShmNdarray":
        shm = shared_memory.SharedMemory(name=name, create=False)
        try:
            arr = np.ndarray(shape, dtype=dtype, buffer=shm.buf)
        except Exception:
            shm.close()
            raise
        return cls(shm, arr, owned=False)

    def close(self) -> None:
        if self._closed:
            return
        # numpy view holds a reference to shm.buf; drop it first.
        self.ndarray = None  # type: ignore[assignment]
        self._shm.close()
        self._closed = True

    def close_and_unlink(self) -> None:
        self.close()
        if self._owned and not self._unlinked:
            self._shm.unlink()
            self._unlinked = True


class AtomicUint8:
    """Single uint8 in shm.

    Single-byte writes are atomic on all common CPU architectures (x86, ARM),
    making cross-process reads safe without a lock.
    """

    def __init__(self, shm: shared_memory.SharedMemory, owned: bool) -> None:
        self._shm = shm
        self._view = np.ndarray((1,), dtype=np.uint8, buffer=shm.buf)
        if owned:
            self._view[0] = 0
        self._owned = owned
        self._closed = False
        self._unlinked = False

    @classmethod
    def create(cls, name: str) -> "AtomicUint8":
        shm = shared_memory.SharedMemory(name=name, create=True, size=1)
        try:
            return cls(shm, owned=True)
        except Exception:
            shm.close()
            try:
                shm.unlink()
            except FileNotFoundError:
                pass
            raise

    @classmethod
    def attach(cls, name: str) -> "AtomicUint8":
        shm = shared_memory.SharedMemory(name=name, create=False)
        try:
            return cls(shm, owned=False)
        except Exception:
            shm.close()
            raise

    def get(self) -> int:
        return int(self._view[0])

    def set(self, value: int) -> None:
        self._view[0] = value & 0xFF

    def close(self) -> None:
        if self._closed:
            return
        self._view = None  # type: ignore[assignment]
        self._shm.close()
        self._closed = True

    def close_and_unlink(self) -> None:
        self.close()
        if self._owned and not self._unlinked:
            self._shm.unlink()
            self._unlinked = True
