"""Lightweight per-stage profiler for GStreamer-app `app_callback` hot paths.

A `CallbackProfiler` collects per-stage timings (perf_counter() deltas in ms)
in fixed-size deques and prints rolling p50/p95 / mean every N frames. When
profiling is off the public methods are no-ops so it costs nothing in the
hot path.

Originally factored out of the YOLO World pipeline; usable by any pipeline
app that wants per-stage callback latency without pulling in GstShark.
"""
from __future__ import annotations

import statistics
from collections import deque
from time import perf_counter
from typing import Iterable, Optional

from hailo_apps.python.core.common.hailo_logger import get_logger

logger = get_logger(__name__)


# Sensible default for typical detection-style callbacks: frame extraction,
# inference, decode/NMS, attach metadata, plus an aggregate "total". Callers
# with a different breakdown can pass their own tuple to the constructor.
DEFAULT_STAGES = ("caps_and_copy", "infer", "postprocess", "attach", "total")


class CallbackProfiler:
    """Rolling per-stage timing.

    Usage from the callback:
        t = profiler.start()
        ... stage 1 ...
        t = profiler.mark(t, "stage_1")
        ... stage 2 ...
        t = profiler.mark(t, "stage_2")
        profiler.frame_done(t_start)   # report every N frames
    """

    def __init__(self,
                 enabled: bool = False,
                 window: int = 120,
                 report_every: int = 30,
                 stages: Optional[Iterable[str]] = None):
        self.enabled = bool(enabled)
        self._window = window
        self._report_every = report_every
        self._n_frames = 0
        self.stages = tuple(stages) if stages is not None else DEFAULT_STAGES
        self._stage_ms = {s: deque(maxlen=window) for s in self.stages}
        self._wall_start = perf_counter()
        self._last_report_wall = self._wall_start
        self._last_report_count = 0

    # ------------------------------------------------------------------ hot path

    def start(self):
        if not self.enabled:
            return None
        return perf_counter()

    def mark(self, ref, stage: str):
        """Record (now - ref) * 1000 ms under `stage`. No-op if disabled."""
        if not self.enabled or ref is None:
            return perf_counter()  # so caller can chain via re-use
        now = perf_counter()
        self._stage_ms[stage].append((now - ref) * 1000.0)
        return now

    def frame_done(self, t_start):
        if not self.enabled or t_start is None:
            return
        now = perf_counter()
        self._stage_ms["total"].append((now - t_start) * 1000.0)
        self._n_frames += 1
        if self._n_frames % self._report_every == 0:
            self._report(now)

    # ------------------------------------------------------------------ reporting

    @staticmethod
    def _pct(samples, p):
        if not samples:
            return 0.0
        s = sorted(samples)
        k = int(round((p / 100.0) * (len(s) - 1)))
        return s[k]

    def _report(self, now):
        frames_since = self._n_frames - self._last_report_count
        wall_since = now - self._last_report_wall
        rolling_fps = frames_since / wall_since if wall_since > 0 else 0.0
        avg_total_fps = self._n_frames / (now - self._wall_start)
        self._last_report_count = self._n_frames
        self._last_report_wall = now

        parts = []
        for s in self.stages:
            samples = self._stage_ms[s]
            if not samples:
                continue
            mean = statistics.mean(samples)
            p50 = self._pct(samples, 50)
            p95 = self._pct(samples, 95)
            parts.append(f"{s} mean={mean:.1f} p50={p50:.1f} p95={p95:.1f}")
        logger.info(
            "[profile] frame=%d rolling_fps=%.2f avg_fps=%.2f | %s",
            self._n_frames, rolling_fps, avg_total_fps, " | ".join(parts),
        )
