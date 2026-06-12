"""PlayerRanker — pick the top-K tracked dancers to actually score.

Selection key: bbox_area * centeredness, where centeredness is a Gaussian
falloff from the frame's horizontal center. The idea: big dancers near the
middle of the frame are the ones the user is watching; small folks at the
edges are usually background. Per-frame compute (FFTs etc.) is bounded by
K regardless of how many tracks the tracker emits.

All bbox coordinates are in normalized [0, 1] frame space (Hailo convention).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Tuple


@dataclass
class Bbox:
    xmin: float
    ymin: float
    width: float
    height: float


class PlayerRanker:
    def __init__(self, max_players: int = 4):
        self.max_players = max_players

    @staticmethod
    def _rank_score(bbox: Bbox) -> float:
        area = bbox.width * bbox.height
        cx = bbox.xmin + bbox.width / 2.0
        # Gaussian-ish centeredness: 1 at frame middle, ≈0.37 at quarter from
        # center, ≈0.018 at frame edge. Half-frame-width is the natural scale.
        d = (cx - 0.5) / 0.5
        centeredness = math.exp(-(d * d))
        return area * centeredness

    def select(self, players: List[Tuple[int, Bbox]]) -> List[int]:
        """Return up to max_players track_ids, sorted best→worst by rank."""
        scored = sorted(
            ((tid, self._rank_score(bbox)) for tid, bbox in players),
            key=lambda kv: kv[1],
            reverse=True,
        )
        return [tid for tid, _ in scored[: self.max_players]]
