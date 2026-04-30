"""Unit tests for ReIDWorker — runs ReIDManager.update_gallery off the streaming thread."""

import threading
import time

import numpy as np
import pytest

from drone_follow.pipeline_adapter.reid_worker import ReIDWorker


class _FakeReIDManager:
    """Stand-in for ReIDManager — records calls and (optionally) blocks."""

    def __init__(self, sleep_s: float = 0.0):
        self._sleep_s = sleep_s
        self._calls = []
        self._lock = threading.Lock()

    def update_gallery(self, frame_bgr, hailo_bbox, video_width, video_height):
        if self._sleep_s:
            time.sleep(self._sleep_s)
        with self._lock:
            self._calls.append((frame_bgr.shape, hailo_bbox, video_width, video_height))

    @property
    def calls(self):
        with self._lock:
            return list(self._calls)


def _frame(h=720, w=1280):
    return np.zeros((h, w, 3), dtype=np.uint8)


def test_submit_returns_immediately_even_when_handler_is_slow():
    fake = _FakeReIDManager(sleep_s=0.1)
    worker = ReIDWorker(fake, max_queue=4)
    worker.start()
    try:
        t0 = time.monotonic()
        worker.submit_gallery_update(_frame(), object(), 1280, 720)
        elapsed = time.monotonic() - t0
        # Submit must not wait on the slow handler.
        assert elapsed < 0.02, f"submit blocked for {elapsed * 1000:.1f}ms"
    finally:
        worker.stop()


def test_worker_processes_submissions_off_caller_thread():
    fake = _FakeReIDManager()
    worker = ReIDWorker(fake, max_queue=4)
    worker.start()
    try:
        bbox = object()
        worker.submit_gallery_update(_frame(), bbox, 1280, 720)
        # Wait up to 1s for the worker to process.
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and not fake.calls:
            time.sleep(0.01)
        assert len(fake.calls) == 1
        shape, recv_bbox, w, h = fake.calls[0]
        assert shape == (720, 1280, 3)
        assert recv_bbox is bbox
        assert (w, h) == (1280, 720)
    finally:
        worker.stop()


def test_overflow_drops_oldest_to_keep_freshest_frame():
    """When the queue is full, the worker prefers the newest frame.

    Why: ReID gallery is most useful with current pixels — a stale frame buffered
    behind newer ones is worse than dropping it. Dropping NEWEST would defeat
    the point (old gallery never updates with current target appearance).
    """
    fake = _FakeReIDManager(sleep_s=0.5)  # blocks the worker so the queue fills
    worker = ReIDWorker(fake, max_queue=2)
    worker.start()
    try:
        # First submission starts running in the worker (queue empty).
        worker.submit_gallery_update(_frame(), "bbox-0", 1280, 720)
        # Next 3 fill+overflow the queue while the worker is asleep.
        for i in range(1, 4):
            worker.submit_gallery_update(_frame(), f"bbox-{i}", 1280, 720)
        # Let the worker drain.
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and len(fake.calls) < 3:
            time.sleep(0.01)
        seen_bboxes = [c[1] for c in fake.calls]
        # bbox-0 ran first; bbox-3 is the freshest and must NOT be dropped.
        assert "bbox-0" in seen_bboxes
        assert "bbox-3" in seen_bboxes
    finally:
        worker.stop()


def test_stop_is_idempotent_and_joins_thread():
    fake = _FakeReIDManager()
    worker = ReIDWorker(fake, max_queue=2)
    worker.start()
    worker.stop()
    worker.stop()  # second call is a no-op
    assert not worker.is_alive()


def test_submit_after_stop_is_silently_ignored():
    """Race-safe: pipeline may still emit one buffer between EOS and stop()."""
    fake = _FakeReIDManager()
    worker = ReIDWorker(fake, max_queue=2)
    worker.start()
    worker.stop()
    worker.submit_gallery_update(_frame(), object(), 1280, 720)
    time.sleep(0.05)
    assert fake.calls == []
