"""BackgroundService — runs the EMA background update in a subprocess.

Lifecycle:
    svc = BackgroundService(width, height, channels=3, capture_frames=30, alpha=0.05)
    svc.start()
    svc.submit_frame(frame, person_mask)   # non-blocking
    bg_view = svc.get_background_view()    # zero-copy uint8 ndarray (or None if not ready)
    svc.stop()                             # joins subprocess, unlinks shm

Internal layout (all via multiprocessing.shared_memory):
    <prefix>frame  : H x W x C  uint8   — callback writes input frame here
    <prefix>mask   : H x W      uint8   — callback writes person mask here (0/1)
    <prefix>bg_a   : H x W x C  uint8   — double-buffer A for current bg
    <prefix>bg_b   : H x W x C  uint8   — double-buffer B for current bg
    <prefix>idx    : 1          uint8   — current readable buffer (0 = a, 1 = b)
    <prefix>ready  : 1          uint8   — 1 once capture phase complete

Signalling:
    A multiprocessing.Event ``frame_ready`` is set by submit_frame() after
    writing into ``frame``/``mask`` slots.  The subprocess waits on the
    event, processes one update, clears the event, and loops.

Double-buffering invariant:
    The subprocess writes only to bg_(1 - current_idx), then flips idx to the
    new buffer.  The reader (parent process) always picks bg_idx, which is
    stable until the next flip.  Breaking this protocol causes torn reads.

Fork safety note:
    mp.Process defaults to fork on Linux.  This subprocess is pure numpy/cv2
    and does not touch GStreamer or Hailo SDK, so fork should be safe.  If
    tests hang or crash due to fork-related global state, try:
        mp.set_start_method("spawn", force=True)
    in the test fixture or at module import time.

Cleanup hygiene:
    svc.stop() joins the subprocess and unlinks all shm.  If a test fails
    before reaching stop(), /dev/shm/<prefix>* segments may leak.  The unique
    shm_prefix fixture in tests mitigates this.
"""
from __future__ import annotations

import multiprocessing as mp
import os
from typing import Optional

import numpy as np

from community.apps.pipeline_apps.vampire_mirror.background_manager import BackgroundUpdater
from community.apps.pipeline_apps.vampire_mirror.bg_shm import AtomicUint8, ShmNdarray


def _run_bg_process(
    shm_prefix: str,
    width: int,
    height: int,
    channels: int,
    capture_frames: int,
    alpha: float,
    frame_ready: mp.Event,
    stop_event: mp.Event,
) -> None:
    """Subprocess entry — owns the EMA loop."""
    frame_shm  = ShmNdarray.attach(f"{shm_prefix}frame", (height, width, channels), np.uint8)
    mask_shm   = ShmNdarray.attach(f"{shm_prefix}mask",  (height, width),           np.uint8)
    bg_a_shm   = ShmNdarray.attach(f"{shm_prefix}bg_a",  (height, width, channels), np.uint8)
    bg_b_shm   = ShmNdarray.attach(f"{shm_prefix}bg_b",  (height, width, channels), np.uint8)
    idx_atom   = AtomicUint8.attach(f"{shm_prefix}idx")
    ready_atom = AtomicUint8.attach(f"{shm_prefix}ready")

    accumulator = np.zeros((height, width, channels), dtype=np.float64)
    frames_seen = 0
    updater = BackgroundUpdater(alpha=alpha)

    try:
        while not stop_event.is_set():
            if not frame_ready.wait(timeout=0.1):
                continue
            frame_ready.clear()

            current_idx = idx_atom.get()
            write_idx = 1 - current_idx
            bg_write = bg_b_shm.ndarray if write_idx == 1 else bg_a_shm.ndarray
            bg_read  = bg_a_shm.ndarray if current_idx == 0 else bg_b_shm.ndarray

            frame    = frame_shm.ndarray
            mask_u8  = mask_shm.ndarray
            has_mask = bool(mask_u8.any())
            person_mask = mask_u8.astype(bool) if has_mask else None

            if frames_seen < capture_frames:
                accumulator += frame
                frames_seen += 1
                if frames_seen == capture_frames:
                    avg = (accumulator / capture_frames).astype(np.uint8)
                    bg_write[:] = avg
                    idx_atom.set(write_idx)
                    ready_atom.set(1)
            else:
                bg_write[:] = bg_read
                updater.apply(bg_write, frame, person_mask=person_mask)
                idx_atom.set(write_idx)
    finally:
        for s in (frame_shm, mask_shm, bg_a_shm, bg_b_shm):
            s.close()
        idx_atom.close()
        ready_atom.close()


class BackgroundService:
    """Client-side handle for the background subprocess.

    Spawns a daemon process that owns the capture→EMA background update loop.
    The parent communicates via shared memory (frames, mask, bg buffers) and a
    multiprocessing.Event for frame signalling.

    Args:
        width: Frame width in pixels.
        height: Frame height in pixels.
        channels: Number of colour channels (default 3 for BGR).
        capture_frames: Number of frames to average for the initial background.
        alpha: EMA blend factor for subsequent updates (0 < alpha <= 1).
        shm_prefix: Prefix for shared memory segment names.  Per-process PID
                    is appended automatically to avoid clashes between
                    concurrent instances.
    """

    def __init__(
        self,
        width: int,
        height: int,
        channels: int = 3,
        capture_frames: int = 30,
        alpha: float = 0.05,
        shm_prefix: str = "vampire_mirror_",
    ) -> None:
        self._w, self._h, self._c = width, height, channels
        self._prefix = f"{shm_prefix}{os.getpid()}_"
        self._cap = capture_frames
        self._alpha = alpha

        self._frame_shm: Optional[ShmNdarray] = None
        self._mask_shm:  Optional[ShmNdarray] = None
        self._bg_a_shm:  Optional[ShmNdarray] = None
        self._bg_b_shm:  Optional[ShmNdarray] = None
        self._idx:   Optional[AtomicUint8] = None
        self._ready: Optional[AtomicUint8] = None
        self._proc:  Optional[mp.Process] = None
        self._frame_ready: Optional[mp.Event] = None
        self._stop:        Optional[mp.Event] = None

    @property
    def shm_prefix(self) -> str:
        """Full shm prefix (including PID suffix) used for all segments."""
        return self._prefix

    def start(self) -> None:
        """Allocate shared memory and spawn the background subprocess."""
        self._frame_shm = ShmNdarray.create(f"{self._prefix}frame", (self._h, self._w, self._c), np.uint8)
        self._mask_shm  = ShmNdarray.create(f"{self._prefix}mask",  (self._h, self._w),          np.uint8)
        self._bg_a_shm  = ShmNdarray.create(f"{self._prefix}bg_a",  (self._h, self._w, self._c), np.uint8)
        self._bg_b_shm  = ShmNdarray.create(f"{self._prefix}bg_b",  (self._h, self._w, self._c), np.uint8)
        self._idx   = AtomicUint8.create(f"{self._prefix}idx")
        self._ready = AtomicUint8.create(f"{self._prefix}ready")

        self._frame_ready = mp.Event()
        self._stop = mp.Event()
        self._proc = mp.Process(
            target=_run_bg_process,
            args=(
                self._prefix, self._w, self._h, self._c,
                self._cap, self._alpha,
                self._frame_ready, self._stop,
            ),
            daemon=True,
        )
        self._proc.start()

    def submit_frame(self, frame: np.ndarray, person_mask: np.ndarray | None) -> None:
        """Copy ``frame`` (and optional mask) into shm, then signal the subprocess.

        Returns immediately (non-blocking).  If the subprocess has not yet
        consumed the previous frame, the new frame overwrites it — this is
        intentional; freshness beats backpressure in a live video pipeline.
        """
        assert frame.shape == (self._h, self._w, self._c)
        assert frame.dtype == np.uint8
        self._frame_shm.ndarray[:] = frame
        if person_mask is None:
            self._mask_shm.ndarray[:] = 0
        else:
            assert person_mask.shape == (self._h, self._w)
            np.copyto(self._mask_shm.ndarray, person_mask.astype(np.uint8))
        self._frame_ready.set()

    def is_ready(self) -> bool:
        """Return True once the capture phase is complete and a bg is available."""
        return self._ready is not None and self._ready.get() == 1

    def get_background_view(self) -> np.ndarray | None:
        """Return a zero-copy view of the currently readable background buffer.

        The view is valid until the subprocess flips idx on the next frame.
        For a stable copy, use :meth:`get_background_copy`.

        Returns None if the capture phase is not yet complete.
        """
        if not self.is_ready():
            return None
        return (
            self._bg_a_shm.ndarray
            if self._idx.get() == 0
            else self._bg_b_shm.ndarray
        )

    def get_background_copy(self) -> np.ndarray | None:
        """Return a stable uint8 copy of the current background, or None if not ready."""
        v = self.get_background_view()
        return None if v is None else v.copy()

    def stop(self) -> None:
        """Signal the subprocess to stop, join it, then unlink all shm segments."""
        if self._stop is not None:
            self._stop.set()
        if self._proc is not None:
            self._proc.join(timeout=2.0)
            if self._proc.is_alive():
                self._proc.terminate()
                self._proc.join(timeout=1.0)
        for s in (self._frame_shm, self._mask_shm, self._bg_a_shm, self._bg_b_shm):
            if s is not None:
                s.close_and_unlink()
        for a in (self._idx, self._ready):
            if a is not None:
                a.close_and_unlink()
