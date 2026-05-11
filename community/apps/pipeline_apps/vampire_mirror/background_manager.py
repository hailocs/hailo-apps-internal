"""BackgroundManager: captures and dynamically updates a scene background.

Phase 1 — Initial capture:
    Accumulates ``capture_frames`` frames and averages them to form the
    initial background.  The accumulator uses float64 for precision.

Phase 2 — Dynamic EMA update:
    After the background is ready, every call to ``update()`` blends the new
    frame into the background using an exponential moving average:

        bg[~mask] = alpha * frame[~mask] + (1 - alpha) * bg[~mask]

    Pixels where ``vampire_mask`` is True are **not** updated, preserving the
    background that was behind the vampire before they appeared.
"""
from __future__ import annotations

import cv2
import numpy as np


class BackgroundUpdater:
    """Pure EMA blend logic — no IPC, no state besides alpha.

    Operates in-place on a uint8 background buffer using cv2.addWeighted
    (SIMD). When ``person_mask`` is provided, pixels under the mask are
    preserved (the background does not adapt where a person is segmented).
    """

    def __init__(self, alpha: float) -> None:
        self._alpha = float(alpha)

    def apply(
        self,
        bg: np.ndarray,
        frame: np.ndarray,
        person_mask: np.ndarray | None,
    ) -> None:
        """Update ``bg`` in-place with one EMA step from ``frame``."""
        assert bg.dtype == np.uint8 and frame.dtype == np.uint8
        assert bg.shape == frame.shape
        alpha = self._alpha

        if person_mask is None:
            cv2.addWeighted(frame, alpha, bg, 1.0 - alpha, 0.0, dst=bg)
            return

        saved = bg[person_mask].copy()
        cv2.addWeighted(frame, alpha, bg, 1.0 - alpha, 0.0, dst=bg)
        bg[person_mask] = saved


class BackgroundManager:
    """Manages a dynamically-updated background for the vampire mirror effect.

    Args:
        capture_frames: Number of initial frames to average for the background.
        alpha: EMA blending factor (0 < alpha <= 1).  Higher values make the
               background adapt faster to changes.
    """

    def __init__(self, capture_frames: int = 30, alpha: float = 0.05) -> None:
        self._capture_frames: int = capture_frames
        self._alpha: float = float(alpha)

        self.background: np.ndarray | None = None   # uint8, set once ready
        self._accumulator: np.ndarray | None = None  # float64, used during capture
        self._frame_count: int = 0                   # frames seen so far

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_ready(self) -> bool:
        """True once the initial capture phase is complete."""
        return self._frame_count >= self._capture_frames

    @property
    def frames_remaining(self) -> int:
        """Number of frames still needed before the background is ready."""
        return max(0, self._capture_frames - self._frame_count)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, frame: np.ndarray, vampire_mask: np.ndarray | None = None) -> None:
        """Update the background with a new frame.

        Args:
            frame: HxWxC uint8 image (or any numeric dtype).
            vampire_mask: Optional boolean array of shape (H, W).  Where True,
                          the background pixel is **not** updated (vampire is
                          there).  Ignored during the initial capture phase.
        """
        if not self.is_ready:
            self._accumulate(frame)
        else:
            self._ema_update(frame, vampire_mask)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _accumulate(self, frame: np.ndarray) -> None:
        """Accumulate frame into the float64 accumulator."""
        frame_f = frame.astype(np.float64)

        if self._accumulator is None:
            self._accumulator = np.zeros_like(frame_f)

        self._accumulator += frame_f
        self._frame_count += 1

        if self.is_ready:
            # Compute mean and convert directly to uint8 — keeps later EMA
            # updates SIMD-friendly via cv2.addWeighted.
            self.background = (self._accumulator / self._capture_frames).astype(np.uint8)
            self._accumulator = None

    def _ema_update(self, frame: np.ndarray, vampire_mask: np.ndarray | None) -> None:
        """Apply EMA blend on non-vampire pixels (in-place, uint8, SIMD)."""
        assert self.background is not None
        if not hasattr(self, "_updater"):
            self._updater = BackgroundUpdater(alpha=self._alpha)
        self._updater.apply(self.background, frame, person_mask=vampire_mask)
