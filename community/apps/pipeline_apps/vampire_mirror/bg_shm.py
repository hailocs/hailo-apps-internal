"""Shared-memory helpers for the vampire mirror background service.

Thin wrappers around ``multiprocessing.shared_memory`` that expose a numpy
view backed by the shm segment.  ``create()`` allocates a new segment;
``attach()`` opens an existing one by name.  ``close_and_unlink()`` should
be called by the creator on shutdown; ``close()`` is enough for attachers.
"""
from __future__ import annotations

from multiprocessing import shared_memory
from typing import Tuple

import numpy as np


class ShmNdarray:
    """numpy ndarray backed by a named shared-memory segment."""

    def __init__(self, shm: shared_memory.SharedMemory, ndarray: np.ndarray, owned: bool) -> None:
        self._shm = shm
        self.ndarray = ndarray
        self._owned = owned

    @classmethod
    def create(cls, name: str, shape: Tuple[int, ...], dtype: np.dtype) -> "ShmNdarray":
        nbytes = int(np.prod(shape)) * np.dtype(dtype).itemsize
        shm = shared_memory.SharedMemory(name=name, create=True, size=nbytes)
        arr = np.ndarray(shape, dtype=dtype, buffer=shm.buf)
        arr[:] = 0
        return cls(shm, arr, owned=True)

    @classmethod
    def attach(cls, name: str, shape: Tuple[int, ...], dtype: np.dtype) -> "ShmNdarray":
        shm = shared_memory.SharedMemory(name=name, create=False)
        arr = np.ndarray(shape, dtype=dtype, buffer=shm.buf)
        return cls(shm, arr, owned=False)

    def close(self) -> None:
        # numpy view holds a reference to shm.buf; drop it first.
        self.ndarray = None  # type: ignore[assignment]
        self._shm.close()

    def close_and_unlink(self) -> None:
        self.close()
        if self._owned:
            self._shm.unlink()


class AtomicUint8:
    """Single uint8 in shm. GIL + single-byte writes give us atomicity on the value."""

    def __init__(self, shm: shared_memory.SharedMemory, owned: bool) -> None:
        self._shm = shm
        self._view = np.ndarray((1,), dtype=np.uint8, buffer=shm.buf)
        if owned:
            self._view[0] = 0
        self._owned = owned

    @classmethod
    def create(cls, name: str) -> "AtomicUint8":
        shm = shared_memory.SharedMemory(name=name, create=True, size=1)
        return cls(shm, owned=True)

    @classmethod
    def attach(cls, name: str) -> "AtomicUint8":
        shm = shared_memory.SharedMemory(name=name, create=False)
        return cls(shm, owned=False)

    def get(self) -> int:
        return int(self._view[0])

    def set(self, value: int) -> None:
        self._view[0] = value & 0xFF

    def close(self) -> None:
        self._view = None  # type: ignore[assignment]
        self._shm.close()

    def close_and_unlink(self) -> None:
        self.close()
        if self._owned:
            self._shm.unlink()
