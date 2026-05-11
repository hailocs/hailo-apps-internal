"""Background capture and EMA update logic for the vampire mirror effect.

Two public classes:

``BackgroundUpdater``
    Stateless EMA blend (cv2.addWeighted, SIMD).  Operates in-place on a
    uint8 buffer.  Used by both the in-process manager and the upcoming
    background subprocess.

``BackgroundManager``
    In-process facade that owns the full capture→EMA lifecycle.  Phase 1
    accumulates ``capture_frames`` frames (float64) and averages them to
    form the initial background.  Phase 2 delegates every ``update()`` call
    to ``BackgroundUpdater``, preserving pixels where a vampire mask is set.
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
        if bg.dtype != np.uint8 or frame.dtype != np.uint8:
            raise ValueError(
                f"bg and frame must be uint8, got bg={bg.dtype}, frame={frame.dtype}"
            )
        if bg.shape != frame.shape:
            raise ValueError(f"Shape mismatch: bg {bg.shape} vs frame {frame.shape}")
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

        self._updater: BackgroundUpdater = BackgroundUpdater(alpha=self._alpha)

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
        self._updater.apply(self.background, frame, person_mask=vampire_mask)
