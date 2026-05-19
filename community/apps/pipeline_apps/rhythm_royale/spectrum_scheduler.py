"""SpectrumScheduler — fair, budgeted, round-robin FFT scheduling.

Per-frame motion compute scales as players × keypoints × axes. To keep
CPU bounded as crowds grow, the scheduler runs only a fixed number of
FFTs per second total (the budget), distributed round-robin across all
registered (player, keypoint, axis) keys. Scoring code reads the most-
recent cached spectrum for each key — at most one window-length stale,
which is the FFT's natural decorrelation horizon anyway.

The scheduler is intentionally data-source-agnostic: callers supply a
compute_fn that takes (player_id, kp_name, axis) and returns a spectrum
(numpy array). This keeps the scheduler unit-testable without the motion
analyzer or the audio chain.
"""
from __future__ import annotations

from collections import deque
from typing import Callable, Dict, Iterable, Optional, Tuple

import numpy as np


_Key = Tuple[int, str, str]  # (player_id, kp_name, axis)
_Cached = Tuple[np.ndarray, float]  # (spectrum, timestamp_when_computed)


class SpectrumScheduler:
    def __init__(self, fft_budget_per_sec: float = 40.0):
        self.budget = float(fft_budget_per_sec)
        self._queue: deque = deque()
        self._known: set = set()
        self._cache: Dict[_Key, _Cached] = {}
        self._last_tick: Optional[float] = None
        self._debt: float = 0.0  # accumulated fractional FFT budget

    def register(self, player_id: int, kp_names: Iterable[str]) -> None:
        for kp in kp_names:
            for axis in ("x", "y"):
                key = (player_id, kp, axis)
                if key not in self._known:
                    self._queue.append(key)
                    self._known.add(key)

    def unregister(self, player_id: int) -> None:
        to_drop = [k for k in self._known if k[0] == player_id]
        for k in to_drop:
            self._known.discard(k)
            self._cache.pop(k, None)
        # Rebuild queue without dropped keys (queues don't support arbitrary remove cheaply).
        self._queue = deque(k for k in self._queue if k[0] != player_id)

    def tick(self, t_now: float,
             compute_fn: Callable[[int, str, str], np.ndarray]) -> int:
        """Run as many FFTs as the budget permits since the last tick.

        Returns the number of FFTs actually computed this call. First call
        only seeds the clock and returns 0.
        """
        if self._last_tick is None:
            self._last_tick = t_now
            return 0
        dt = max(0.0, t_now - self._last_tick)
        self._last_tick = t_now
        self._debt += dt * self.budget
        n_run = int(self._debt)
        self._debt -= n_run
        if not self._queue:
            return 0
        for _ in range(n_run):
            key = self._queue.popleft()
            spectrum = compute_fn(*key)
            self._cache[key] = (spectrum, t_now)
            self._queue.append(key)
        return n_run

    def get(self, player_id: int, kp_name: str, axis: str) -> Optional[_Cached]:
        return self._cache.get((player_id, kp_name, axis))
