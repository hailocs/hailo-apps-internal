"""Background worker that runs ReIDManager.update_gallery off the GStreamer streaming thread.

The ReID gallery update involves a frame-buffer copy + an NPU embedding extraction.
Running it inline in app_callback adds per-frame latency to the streaming thread
and can cause back-pressure into the GStreamer pipeline. This worker decouples
the gallery update from the streaming thread by buffering submissions in a bounded
queue and processing them in a daemon thread.

Only update_gallery is async. try_reidentify stays synchronous in the callback —
its return value (a track_id from the current frame's person_by_id) must be applied
to the same frame, which would require frame-delay handling. Out of scope here.

Bounded queue + drop-oldest semantics: under sustained backpressure we keep the
freshest frame and drop the oldest pending one. A stale gallery embedding is
worse than no update — the gallery is supposed to track the target's *current*
appearance.
"""

import logging
import queue
import threading
from typing import Any, Optional

LOGGER = logging.getLogger(__name__)


class ReIDWorker:
    """Daemon-thread wrapper that calls ReIDManager.update_gallery asynchronously."""

    # Sentinel pushed onto the queue to signal shutdown.
    _STOP = object()

    def __init__(self, reid_manager: Any, max_queue: int = 2):
        """
        Args:
            reid_manager: object with `.update_gallery(frame_bgr, bbox, w, h)`.
            max_queue: maximum pending submissions. Beyond this, the OLDEST queued
                submission is dropped to make room for the new one.
        """
        self._reid_manager = reid_manager
        self._queue: queue.Queue = queue.Queue(maxsize=max_queue)
        self._thread: Optional[threading.Thread] = None
        self._stopped = threading.Event()
        self._dropped_count = 0
        self._dropped_lock = threading.Lock()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stopped.clear()
        self._thread = threading.Thread(
            target=self._run, name="reid-worker", daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        if self._thread is None:
            return
        self._stopped.set()
        try:
            self._queue.put_nowait(self._STOP)
        except queue.Full:
            # Make room for the sentinel.
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(self._STOP)
            except queue.Full:
                pass
        self._thread.join(timeout=timeout)
        self._thread = None

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def submit_gallery_update(self, frame_bgr, hailo_bbox, video_width: int,
                              video_height: int) -> None:
        """Enqueue a gallery-update job. Returns immediately.

        If the queue is full, the OLDEST pending submission is discarded.
        Submissions made after stop() are silently dropped.
        """
        if self._stopped.is_set() or self._thread is None:
            return
        item = (frame_bgr, hailo_bbox, video_width, video_height)
        try:
            self._queue.put_nowait(item)
            return
        except queue.Full:
            pass
        # Drop oldest, retry once.
        try:
            self._queue.get_nowait()
            with self._dropped_lock:
                self._dropped_count += 1
        except queue.Empty:
            pass
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            with self._dropped_lock:
                self._dropped_count += 1

    def dropped_count(self) -> int:
        with self._dropped_lock:
            return self._dropped_count

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is self._STOP:
                break
            frame_bgr, hailo_bbox, w, h = item
            try:
                self._reid_manager.update_gallery(frame_bgr, hailo_bbox, w, h)
            except Exception:
                LOGGER.exception("[reid-worker] update_gallery raised — continuing")
