"""Tracker protocol helpers: TrackedObject, MetricsTracker wrapper."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol, Sequence

import numpy as np


@dataclass
class TrackedObject:
    """Single tracked detection returned by a tracker's ``update()``."""
    track_id: int
    input_index: int
    is_activated: bool
    score: float


class Tracker(Protocol):
    """Minimal tracker interface."""

    def update(self, detections: np.ndarray, embeddings=None) -> Sequence[TrackedObject]: ...

    def reset(self) -> None: ...


@dataclass
class TrackerMetrics:
    """Live metrics updated by :class:`MetricsTracker`."""

    init_ms: float = 0.0
    total_frames: int = 0
    fps: float = 0.0
    update_ms: float = 0.0
    match_ratio: float = 0.0
    active_tracks: int = 0
    id_switches: int = 0

    # internal
    _last_time: float = field(default_factory=time.monotonic, repr=False)
    _last_frame: int = field(default=0, repr=False)
    _prev_ids: set = field(default_factory=set, repr=False)

    def snapshot(self) -> dict:
        return {
            "init_ms": round(self.init_ms, 2),
            "total_frames": self.total_frames,
            "fps": round(self.fps, 1),
            "update_ms": round(self.update_ms, 2),
            "match_ratio": round(self.match_ratio, 3),
            "active_tracks": self.active_tracks,
            "id_switches": self.id_switches,
        }


class MetricsTracker:
    """Wraps any :class:`Tracker` and records per-frame metrics."""

    def __init__(self, inner: Tracker, *, init_time_ms: float = 0.0):
        self._inner = inner
        self.metrics = TrackerMetrics(init_ms=init_time_ms)

    def update(self, detections: np.ndarray, embeddings=None) -> Sequence[TrackedObject]:
        t0 = time.monotonic()
        results = self._inner.update(detections, embeddings=embeddings)
        elapsed_ms = (time.monotonic() - t0) * 1000.0

        m = self.metrics
        m.total_frames += 1
        m.update_ms = elapsed_ms
        m.active_tracks = len(results)

        # FPS (updated every second)
        now = time.monotonic()
        dt = now - m._last_time
        if dt >= 1.0:
            m.fps = (m.total_frames - m._last_frame) / dt
            m._last_time = now
            m._last_frame = m.total_frames

        # Match ratio: fraction of input detections that matched a track
        n_dets = len(detections) if len(detections) else 1
        matched = sum(1 for r in results if r.input_index >= 0)
        m.match_ratio = matched / n_dets

        # ID switches: track IDs that disappeared from previous frame
        current_ids = {r.track_id for r in results}
        if m._prev_ids:
            lost = m._prev_ids - current_ids
            m.id_switches += len(lost)
        m._prev_ids = current_ids

        return results

    def reset(self) -> None:
        self._inner.reset()
