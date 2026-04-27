"""Tests for SharedDetectionState thread safety and correctness."""

import threading
import time

import pytest

from drone_follow.follow_api import (
    Detection,
    SharedDetectionState,
)


def _det(cx=0.5, cy=0.5, bh=0.3):
    return Detection(
        label="test", confidence=0.9,
        center_x=cx, center_y=cy, bbox_height=bh,
        timestamp=time.monotonic(),
    )


class TestSharedDetectionState:
    def test_initial_state_is_none(self):
        state = SharedDetectionState()
        det, count = state.get_latest()
        assert det is None
        assert count == 0

    def test_update_and_get(self):
        state = SharedDetectionState()
        d = _det(cx=0.7, cy=0.3)
        state.update(d)
        det, count = state.get_latest()
        assert det is d
        assert count == 1

    def test_frame_count_increments(self):
        state = SharedDetectionState()
        for i in range(10):
            state.update(_det())
        _, count = state.get_latest()
        assert count == 10

    def test_none_clears_detection(self):
        state = SharedDetectionState()
        state.update(_det())
        state.update(None)
        det, count = state.get_latest()
        assert det is None
        assert count == 2

    def test_only_latest_detection_kept(self):
        state = SharedDetectionState()
        state.update(_det(cx=0.1))
        state.update(_det(cx=0.2))
        state.update(_det(cx=0.9))
        det, _ = state.get_latest()
        assert det.center_x == 0.9

    def test_get_returns_snapshot(self):
        """get_latest should return consistent data even if update happens after."""
        state = SharedDetectionState()
        state.update(_det(cx=0.3))
        det, count = state.get_latest()
        # update after get
        state.update(_det(cx=0.8))
        # original snapshot unchanged
        assert det.center_x == 0.3
        assert count == 1

    def test_concurrent_updates(self):
        """Multiple threads writing shouldn't crash or corrupt state."""
        state = SharedDetectionState()
        n_threads = 8
        n_updates = 500
        barrier = threading.Barrier(n_threads)

        def writer(thread_id):
            barrier.wait()
            for i in range(n_updates):
                cx = (thread_id * n_updates + i) / (n_threads * n_updates)
                state.update(_det(cx=cx))

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        det, count = state.get_latest()
        assert count == n_threads * n_updates
        assert det is not None
        assert 0.0 <= det.center_x <= 1.0

    def test_concurrent_read_write(self):
        """Reader thread shouldn't see corrupted state during writes."""
        state = SharedDetectionState()
        errors = []
        stop = threading.Event()

        def writer():
            for i in range(2000):
                val = i / 2000.0
                state.update(_det(cx=val, cy=val, bh=val * 0.5 + 0.1))
            stop.set()

        def reader():
            while not stop.is_set():
                det, count = state.get_latest()
                if det is not None:
                    # All fields should be internally consistent
                    if not (0.0 <= det.center_x <= 1.0):
                        errors.append(f"bad center_x: {det.center_x}")
                    if not (0.0 <= det.center_y <= 1.0):
                        errors.append(f"bad center_y: {det.center_y}")
                    if not (0.0 <= det.bbox_height <= 1.1):
                        errors.append(f"bad bbox_height: {det.bbox_height}")

        w = threading.Thread(target=writer)
        r = threading.Thread(target=reader)
        r.start()
        w.start()
        w.join()
        r.join()

        assert errors == [], f"Concurrent read/write errors: {errors}"
