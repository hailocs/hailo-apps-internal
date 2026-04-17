"""Frame geometry utilities for the vampire mirror app.

The vampire mirror captures video in landscape mode but presents a portrait
center crop to the viewer (the "mirror view"). The portions of the frame to the
left and right of the mirror crop are "buffer zones" — people can be detected
there before they step into the visible mirror area.

This module is a pure Python/NumPy helper with no Hailo or GStreamer dependencies
so it can be unit-tested in isolation.
"""

from __future__ import annotations

import numpy as np


class FrameGeometry:
    """Pre-compute crop coordinates for a landscape frame → portrait mirror view.

    Parameters
    ----------
    frame_width:
        Width of the full landscape frame in pixels.
    frame_height:
        Height of the full landscape frame in pixels.
    mirror_ratio:
        (width_parts, height_parts) of the desired portrait aspect ratio.
        Default ``(9, 16)`` produces a standard 9∶16 portrait crop.

    Attributes
    ----------
    mirror_width:  Width of the portrait mirror crop (pixels).
    mirror_height: Height of the portrait mirror crop — equals ``frame_height``.
    crop_x1:       Left edge of the mirror region (inclusive).
    crop_x2:       Right edge of the mirror region (exclusive).
    """

    def __init__(
        self,
        frame_width: int,
        frame_height: int,
        mirror_ratio: tuple[int, int] = (9, 16),
    ) -> None:
        ratio_w, ratio_h = mirror_ratio

        self.mirror_height: int = frame_height
        # Ideal portrait width scaled from the frame height, clamped to frame width
        ideal_width = int(frame_height * ratio_w / ratio_h)
        self.mirror_width: int = min(ideal_width, frame_width)

        # Centre the mirror crop horizontally
        self.crop_x1: int = (frame_width - self.mirror_width) // 2
        self.crop_x2: int = self.crop_x1 + self.mirror_width

    # ------------------------------------------------------------------
    # Crop helper
    # ------------------------------------------------------------------

    def center_crop(self, frame: np.ndarray) -> np.ndarray:
        """Return the portrait mirror slice of *frame*.

        Parameters
        ----------
        frame:
            Full landscape frame with shape ``(H, W, C)`` in any dtype.

        Returns
        -------
        np.ndarray
            Cropped array with shape ``(H, mirror_width, C)``.
        """
        return frame[:, self.crop_x1 : self.crop_x2]

    # ------------------------------------------------------------------
    # Overlap detection
    # ------------------------------------------------------------------

    def is_in_mirror(
        self,
        bbox_xmin: float,
        bbox_width: float,
        frame_width: int,  # kept for API symmetry / future normalisation use
    ) -> bool:
        """Return ``True`` if the bounding box overlaps the mirror region.

        A person detected in a buffer zone (entirely outside the mirror crop)
        returns ``False``; any overlap with the mirror region returns ``True``.

        Parameters
        ----------
        bbox_xmin:
            Left edge of the bounding box in absolute pixel coordinates.
        bbox_width:
            Width of the bounding box in pixels.
        frame_width:
            Width of the full frame (unused in the current pixel-coordinate
            implementation; present for future normalised-coordinate support).

        Returns
        -------
        bool
        """
        bbox_xmax = bbox_xmin + bbox_width
        # Intervals [crop_x1, crop_x2) and [bbox_xmin, bbox_xmax) overlap when:
        #   bbox_xmax > crop_x1  AND  bbox_xmin < crop_x2
        return bbox_xmax > self.crop_x1 and bbox_xmin < self.crop_x2
