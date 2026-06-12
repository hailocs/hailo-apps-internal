"""Gesture detection for Bubble Pop magic — pure logic, unit-testable.

Works on COCO pose keypoints (wrists / nose / shoulders) of each tracked
person. No Hailo or GStreamer imports.

Emitted events (tuples, consumed by ``BubbleGame.cast()``):
    ("shockwave", x, y)          — hands pressed together
    ("rain",)                    — both hands raised above the head
    ("bolt", x, y, vx, vy)       — fast hand flick ("wand" swipe)
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

Point = Tuple[float, float]

# Hands-together: wrists closer than this fraction of the shoulder width
HANDS_TOGETHER_FACTOR = 0.45
HANDS_TOGETHER_FALLBACK_PX = 70.0   # used when shoulders aren't visible

SWIPE_SPEED_PX_S = 900.0            # at 720p; scaled by frame height
BOLT_SPEED_PX_S = 750.0             # bolt projectile speed at 720p

SHOCKWAVE_COOLDOWN_S = 1.5
RAIN_COOLDOWN_S = 6.0
BOLT_COOLDOWN_S = 0.6

_MAX_HIST_AGE_S = 0.2               # wrist history older than this is stale


class PersonPose:
    """Keypoints of one tracked person (pixel coords, already mirrored)."""

    __slots__ = ("left_wrist", "right_wrist", "nose", "shoulder_width")

    def __init__(self,
                 left_wrist: Optional[Point] = None,
                 right_wrist: Optional[Point] = None,
                 nose: Optional[Point] = None,
                 shoulder_width: Optional[float] = None):
        self.left_wrist = left_wrist
        self.right_wrist = right_wrist
        self.nose = nose
        self.shoulder_width = shoulder_width

    def mirrored(self, width: int) -> "PersonPose":
        def flip(p):
            return (width - p[0], p[1]) if p else None
        return PersonPose(flip(self.left_wrist), flip(self.right_wrist),
                          flip(self.nose), self.shoulder_width)

    @property
    def wrists(self) -> List[Point]:
        return [w for w in (self.left_wrist, self.right_wrist) if w]


class GestureCaster:
    """Tracks per-person wrist motion and emits magic cast events."""

    def __init__(self, frame_height: int = 720):
        self.scale = frame_height / 720.0
        # (track_id, side) -> (t, x, y) of the previous frame's wrist
        self._wrist_hist: Dict[Tuple[int, str], Tuple[float, float, float]] = {}
        self._cooldown: Dict[str, float] = {}
        self._was_together: Dict[int, bool] = {}
        self._was_arms_up: Dict[int, bool] = {}

    # ------------------------------------------------------------------ public

    def update(self, t: float, people: Dict[int, PersonPose]) -> List[tuple]:
        """Advance one frame. Returns the list of cast events."""
        events: List[tuple] = []
        big_spell_tids = set()

        for tid, p in people.items():
            ev = self._check_shockwave(t, tid, p)
            if ev:
                events.append(ev)
                big_spell_tids.add(tid)
            ev = self._check_rain(t, tid, p)
            if ev:
                events.append(ev)
                big_spell_tids.add(tid)

        for tid, p in people.items():
            # A flailing shockwave/rain pose shouldn't also fire bolts
            if tid in big_spell_tids or self._was_together.get(tid) \
                    or self._was_arms_up.get(tid):
                continue
            events.extend(self._check_bolts(t, tid, p))

        self._store_history(t, people)
        return events

    # ----------------------------------------------------------------- spells

    def _check_shockwave(self, t: float, tid: int, p: PersonPose):
        lw, rw = p.left_wrist, p.right_wrist
        if not (lw and rw):
            self._was_together[tid] = False
            return None
        thresh = (HANDS_TOGETHER_FACTOR * p.shoulder_width
                  if p.shoulder_width
                  else HANDS_TOGETHER_FALLBACK_PX * self.scale)
        together = math.hypot(lw[0] - rw[0], lw[1] - rw[1]) < thresh
        was = self._was_together.get(tid, False)
        self._was_together[tid] = together
        if together and not was and self._ready(t, f"shock:{tid}",
                                                SHOCKWAVE_COOLDOWN_S):
            return ("shockwave", (lw[0] + rw[0]) / 2, (lw[1] + rw[1]) / 2)
        return None

    def _check_rain(self, t: float, tid: int, p: PersonPose):
        lw, rw, nose = p.left_wrist, p.right_wrist, p.nose
        if not (lw and rw and nose):
            self._was_arms_up[tid] = False
            return None
        arms_up = lw[1] < nose[1] and rw[1] < nose[1]
        was = self._was_arms_up.get(tid, False)
        self._was_arms_up[tid] = arms_up
        if arms_up and not was and self._ready(t, f"rain:{tid}",
                                               RAIN_COOLDOWN_S):
            return ("rain",)
        return None

    def _check_bolts(self, t: float, tid: int, p: PersonPose) -> List[tuple]:
        events = []
        for side, wrist in (("L", p.left_wrist), ("R", p.right_wrist)):
            if not wrist:
                continue
            hist = self._wrist_hist.get((tid, side))
            if not hist:
                continue
            t0, x0, y0 = hist
            dt = t - t0
            if dt <= 0 or dt > _MAX_HIST_AGE_S:
                continue
            dx, dy = wrist[0] - x0, wrist[1] - y0
            speed = math.hypot(dx, dy) / dt
            if speed < SWIPE_SPEED_PX_S * self.scale:
                continue
            if not self._ready(t, f"bolt:{tid}:{side}", BOLT_COOLDOWN_S):
                continue
            norm = math.hypot(dx, dy)
            v = BOLT_SPEED_PX_S * self.scale
            events.append(("bolt", wrist[0], wrist[1],
                           v * dx / norm, v * dy / norm))
        return events

    # ---------------------------------------------------------------- helpers

    def _ready(self, t: float, key: str, cooldown: float) -> bool:
        if t < self._cooldown.get(key, 0.0):
            return False
        self._cooldown[key] = t + cooldown
        return True

    def _store_history(self, t: float, people: Dict[int, PersonPose]) -> None:
        for tid, p in people.items():
            for side, wrist in (("L", p.left_wrist), ("R", p.right_wrist)):
                if wrist:
                    self._wrist_hist[(tid, side)] = (t, wrist[0], wrist[1])
        # drop stale entries (people who left the frame)
        self._wrist_hist = {k: v for k, v in self._wrist_hist.items()
                            if t - v[0] < 2.0}
