"""FastTracker adapter — wraps the vendored FastTracker to satisfy the Tracker protocol.

Source: https://github.com/Hamidreza-Hashempoor/FastTracker

The adapter translates between our Nx5 ``[x1, y1, x2, y2, conf]`` input format
and FastTracker's ``update(output_results, img_info, img_size)`` API, and maps
returned STracks back to ``TrackedObject`` instances with ``input_index``.
"""

from __future__ import annotations

import numpy as np

from .tracker import Tracker, TrackedObject


def _match_track_to_detection(track_tlbr, det_array: np.ndarray) -> int:
    """Find the input detection index best matching a track box (by IoU).

    FastTracker STracks don't carry ``input_index``, so we recover it here.
    """
    if len(det_array) == 0:
        return -1

    tx1, ty1, tx2, ty2 = track_tlbr

    best_idx = -1
    best_iou = 0.0
    for i in range(len(det_array)):
        dx1, dy1, dx2, dy2 = det_array[i, :4]
        ix1 = max(tx1, dx1)
        iy1 = max(ty1, dy1)
        ix2 = min(tx2, dx2)
        iy2 = min(ty2, dy2)
        inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
        area_t = (tx2 - tx1) * (ty2 - ty1)
        area_d = (dx2 - dx1) * (dy2 - dy1)
        iou = inter / max(area_t + area_d - inter, 1e-6)
        if iou > best_iou:
            best_iou = iou
            best_idx = i

    return best_idx if best_iou > 0.3 else -1


class FastTrackerAdapter(Tracker):
    """Wraps FastTracker to conform to the :class:`Tracker` protocol.

    Accepts the same keyword arguments as :class:`ByteTrackerAdapter` for
    easy swapping: ``track_thresh``, ``track_buffer``, ``match_thresh``,
    ``frame_rate``.
    """

    def __init__(self, *, track_thresh: float = 0.4, track_buffer: int = 90,
                 match_thresh: float = 0.5, frame_rate: int = 30):
        self._kwargs = dict(track_thresh=track_thresh, track_buffer=track_buffer,
                            match_thresh=match_thresh, frame_rate=frame_rate)
        self._init_inner()

    def _init_inner(self):
        from ._fasttracker import Fasttracker

        class _Args:
            mot20 = False

        config = {
            "track_thresh": self._kwargs["track_thresh"],
            "track_buffer": self._kwargs["track_buffer"],
            "match_thresh": self._kwargs["match_thresh"],
        }

        self._ft = Fasttracker(_Args(), config, frame_rate=self._kwargs["frame_rate"])
        self._img_size = (1080, 1920)

    def update(self, detections: np.ndarray) -> list[TrackedObject]:
        if len(detections) == 0:
            stracks = self._ft.update(
                np.empty((0, 5), dtype=np.float32),
                self._img_size, self._img_size,
            )
        else:
            # Pass img_info == img_size so scale=1.0 (our detections are already in pixels)
            stracks = self._ft.update(detections, self._img_size, self._img_size)

        results = []
        for t in stracks:
            tlbr = t.tlbr
            input_index = _match_track_to_detection(tlbr, detections)
            results.append(TrackedObject(
                track_id=t.track_id,
                input_index=input_index,
                is_activated=t.is_activated,
                score=t.score,
                # FastTracker's STrack uses the same KF math as ByteTracker;
                # divide back out from the SCALE=1000 input units the caller
                # passed in to recover normalized [0..1] frame fractions.
                filtered_tlwh=tuple(float(v) / 1000.0 for v in t.tlwh),
            ))
        return results

    def reset(self) -> None:
        self._init_inner()
