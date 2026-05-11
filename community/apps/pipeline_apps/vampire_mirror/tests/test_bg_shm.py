"""Tests for bg_shm — shared-memory helpers used by BackgroundService."""
import os

import numpy as np
import pytest

from community.apps.pipeline_apps.vampire_mirror.bg_shm import (
    ShmNdarray, AtomicUint8,
)


class TestShmNdarray:
    def test_create_and_read_view(self):
        """Creator allocates an shm-backed ndarray; view sees writes immediately."""
        shm = ShmNdarray.create("vm_test_create", shape=(4, 4, 3), dtype=np.uint8)
        try:
            view = shm.ndarray
            view[:] = 42
            assert (shm.ndarray == 42).all()
        finally:
            shm.close_and_unlink()

    def test_attach_sees_writes(self):
        """Attaching from another handle observes writes via shared memory."""
        creator = ShmNdarray.create("vm_test_attach", shape=(2, 2), dtype=np.uint8)
        try:
            attacher = ShmNdarray.attach("vm_test_attach", shape=(2, 2), dtype=np.uint8)
            try:
                creator.ndarray[:] = 99
                assert (attacher.ndarray == 99).all()
            finally:
                attacher.close()
        finally:
            creator.close_and_unlink()

    def test_close_and_unlink_is_idempotent(self):
        """Calling close_and_unlink() twice must not raise."""
        shm = ShmNdarray.create("vm_test_idempotent", shape=(2, 2), dtype=np.uint8)
        shm.close_and_unlink()
        # Second call must be silent, not raise FileNotFoundError.
        shm.close_and_unlink()

    def test_attach_after_unlink_raises(self):
        """Attaching to an already-unlinked segment raises FileNotFoundError."""
        shm = ShmNdarray.create("vm_test_gone", shape=(2, 2), dtype=np.uint8)
        shm.close_and_unlink()
        with pytest.raises(FileNotFoundError):
            ShmNdarray.attach("vm_test_gone", shape=(2, 2), dtype=np.uint8)


class TestAtomicUint8:
    def test_initial_value_zero(self):
        a = AtomicUint8.create("vm_test_atomic")
        try:
            assert a.get() == 0
        finally:
            a.close_and_unlink()

    def test_set_and_get(self):
        a = AtomicUint8.create("vm_test_atomic_set")
        try:
            a.set(1)
            assert a.get() == 1
            a.set(0)
            assert a.get() == 0
        finally:
            a.close_and_unlink()

    def test_close_and_unlink_is_idempotent(self):
        """Calling close_and_unlink() twice must not raise."""
        a = AtomicUint8.create("vm_test_atomic_idempotent")
        a.close_and_unlink()
        # Second call must be silent, not raise FileNotFoundError.
        a.close_and_unlink()
