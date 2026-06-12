"""Bubble Pop game engine — bubbles, pop bursts, wrist glitter, score HUD.

Pure OpenCV / numpy / stdlib: no GStreamer or Hailo imports, so the whole
game logic is unit-testable without hardware.

All colors are RGB — frames arrive in RGB from the GStreamer callback and
are converted to BGR only right before ``set_frame()``.
"""
from __future__ import annotations

import math
import random
from typing import List, Sequence, Tuple

import cv2
import numpy as np

Point = Tuple[float, float]

# Heart palette — pinks, reds and purples (RGB)
BUBBLE_COLORS_RGB = [
    (255, 90, 120),   # red-pink
    (255, 150, 200),  # pink
    (255, 110, 180),  # hot pink
    (200, 130, 255),  # purple
    (255, 180, 160),  # coral
    (255, 130, 130),  # light red
]

GLITTER_COLORS_RGB = [
    (255, 255, 255),  # white
    (255, 230, 120),  # gold
    (255, 170, 230),  # pink
    (160, 230, 255),  # ice blue
    (200, 255, 180),  # pale green
]

POP_MARGIN_PX = 12      # extra reach around a bubble so pops feel generous
BUBBLE_ALPHA = 0.32     # translucency of bubble bodies and wrist glow

# Magic effects
RAIN_DURATION_S = 3.0       # glitter rain lasts this long per cast
RAIN_DROPS_PER_FRAME = 8
BOLT_RADIUS_PX = 30         # pop reach of a magic bolt
SHOCKWAVE_SPEED_PX_S = 1100.0
ANNOUNCE_DURATION_S = 1.0


def _heart_polygon(cx: float, cy: float, r: float, n: int = 28) -> np.ndarray:
    """Heart-shaped polygon centered on (cx, cy), sized to roughly match a
    circle of radius ``r``. Classic parametric heart curve."""
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n
        x = 16 * math.sin(t) ** 3
        y = (13 * math.cos(t) - 5 * math.cos(2 * t)
             - 2 * math.cos(3 * t) - math.cos(4 * t))
        pts.append((cx + x * r / 14.0, cy - y * r / 14.0))
    return np.array(pts, dtype=np.int32)


class Bubble:
    """A single bubble heart drifting upward with a gentle side-to-side wobble."""

    def __init__(self, rng: random.Random, width: int, height: int):
        scale = height / 720.0
        self.radius = max(14, int(rng.uniform(26, 60) * scale))
        self.base_x = rng.uniform(0.08, 0.92) * width
        self.x = self.base_x
        self.y = float(height + self.radius)
        self.speed = rng.uniform(90, 170) * scale          # px/s upward
        self.wobble_amp = rng.uniform(8, 30) * scale
        self.wobble_freq = rng.uniform(0.6, 1.8)           # Hz
        self.wobble_phase = rng.uniform(0, 2 * math.pi)
        self.color = rng.choice(BUBBLE_COLORS_RGB)

    def update(self, dt: float, t: float) -> None:
        self.y -= self.speed * dt
        self.x = self.base_x + self.wobble_amp * math.sin(
            2 * math.pi * self.wobble_freq * t + self.wobble_phase
        )

    def offscreen(self) -> bool:
        return self.y < -self.radius

    def hit(self, px: float, py: float) -> bool:
        return math.hypot(px - self.x, py - self.y) <= self.radius + POP_MARGIN_PX

    def polygon(self) -> np.ndarray:
        """Current heart outline as an int32 polygon."""
        return _heart_polygon(self.x, self.y, self.radius)


class _Particle:
    """Burst fragment ("dot") or glitter sparkle ("spark")."""

    __slots__ = ("x", "y", "vx", "vy", "color", "life", "age",
                 "size", "gravity", "kind")

    def __init__(self, x, y, vx, vy, color, life, size, gravity, kind):
        self.x, self.y = x, y
        self.vx, self.vy = vx, vy
        self.color = color
        self.life = life
        self.age = 0.0
        self.size = size
        self.gravity = gravity
        self.kind = kind  # "dot" | "spark"

    def update(self, dt: float) -> None:
        self.age += dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.vy += self.gravity * dt

    @property
    def alive(self) -> bool:
        return self.age < self.life

    @property
    def fade(self) -> float:
        """1.0 at birth → 0.0 at end of life."""
        return max(0.0, 1.0 - self.age / self.life)


class _Ring:
    """Expanding ring shown for a moment where a bubble popped."""

    __slots__ = ("x", "y", "r0", "age", "life", "color")

    def __init__(self, x, y, r0, color, life=0.35):
        self.x, self.y = x, y
        self.r0 = r0
        self.age = 0.0
        self.life = life
        self.color = color

    def update(self, dt: float) -> None:
        self.age += dt

    @property
    def alive(self) -> bool:
        return self.age < self.life

    @property
    def radius(self) -> int:
        frac = self.age / self.life
        return int(self.r0 * (1.0 + 1.4 * frac))

    @property
    def fade(self) -> float:
        return max(0.0, 1.0 - self.age / self.life)


class _Bolt:
    """Magic bolt projectile — pops hearts along its path."""

    __slots__ = ("x", "y", "vx", "vy", "age", "life")

    def __init__(self, x, y, vx, vy, life=1.3):
        self.x, self.y = x, y
        self.vx, self.vy = vx, vy
        self.age = 0.0
        self.life = life

    def update(self, dt: float) -> None:
        self.age += dt
        self.x += self.vx * dt
        self.y += self.vy * dt

    @property
    def alive(self) -> bool:
        return self.age < self.life


class _Shockwave:
    """Expanding magic ring — pops every heart it reaches."""

    __slots__ = ("x", "y", "age", "life")

    def __init__(self, x, y, life=0.9):
        self.x, self.y = x, y
        self.age = 0.0
        self.life = life

    def update(self, dt: float) -> None:
        self.age += dt

    @property
    def alive(self) -> bool:
        return self.age < self.life

    @property
    def radius(self) -> float:
        return SHOCKWAVE_SPEED_PX_S * self.age

    @property
    def fade(self) -> float:
        return max(0.0, 1.0 - self.age / self.life)


class BubbleGame:
    """Holds all game state. ``update()`` advances physics, ``draw()`` renders."""

    def __init__(self, max_bubbles: int = 40, spawn_interval: float = 0.08,
                 glitter_per_wrist: int = 3, seed: int | None = None):
        self.rng = random.Random(seed)
        self.max_bubbles = max_bubbles
        self.spawn_interval = spawn_interval
        self.glitter_per_wrist = glitter_per_wrist
        self.bubbles: List[Bubble] = []
        self.particles: List[_Particle] = []
        self.rings: List[_Ring] = []
        self.bolts: List[_Bolt] = []
        self.shockwaves: List[_Shockwave] = []
        self.rain_until = 0.0
        self.score = 0
        self._next_spawn_t = 0.0
        self._announce_text = ""
        self._announce_until = 0.0
        self._t = 0.0

    # ------------------------------------------------------------------ update

    def cast(self, event: tuple, t: float) -> None:
        """Apply a magic cast event from the GestureCaster."""
        kind = event[0]
        if kind == "shockwave":
            _, x, y = event
            self.shockwaves.append(_Shockwave(x, y))
            self._say("SHOCKWAVE!", t)
        elif kind == "rain":
            self.rain_until = max(self.rain_until, t + RAIN_DURATION_S)
            self._say("GLITTER RAIN!", t)
        elif kind == "bolt":
            _, x, y, vx, vy = event
            self.bolts.append(_Bolt(x, y, vx, vy))

    def _say(self, text: str, t: float) -> None:
        self._announce_text = text
        self._announce_until = t + ANNOUNCE_DURATION_S

    def update(self, dt: float, t: float, wrists: Sequence[Point],
               width: int, height: int) -> int:
        """Advance one frame. Returns the number of bubbles popped this frame."""
        self._t = t

        # Spawn new bubbles from the bottom
        if t >= self._next_spawn_t and len(self.bubbles) < self.max_bubbles:
            self.bubbles.append(Bubble(self.rng, width, height))
            self._next_spawn_t = t + self.spawn_interval * self.rng.uniform(0.6, 1.4)

        # Move bubbles, drop the ones that floated off the top
        for b in self.bubbles:
            b.update(dt, t)
        self.bubbles = [b for b in self.bubbles if not b.offscreen()]

        # Magic pops first (shockwave / bolts / glitter rain)
        popped = self._update_magic(dt, t, width, height)

        # Pop detection — any wrist inside a heart bursts it
        survivors: List[Bubble] = []
        for b in self.bubbles:
            if any(b.hit(x, y) for (x, y) in wrists):
                popped += 1
                self.score += 1
                self._burst(b)
            else:
                survivors.append(b)
        self.bubbles = survivors

        # Glitter trail on every tracked wrist
        for (x, y) in wrists:
            self._emit_glitter(x, y)

        # Advance particles / rings
        for p in self.particles:
            p.update(dt)
        self.particles = [p for p in self.particles if p.alive]
        for r in self.rings:
            r.update(dt)
        self.rings = [r for r in self.rings if r.alive]

        return popped

    def _update_magic(self, dt: float, t: float,
                      width: int, height: int) -> int:
        """Advance magic effects and pop the hearts they reach."""
        popped = 0

        # Shockwaves — pop everything inside the expanding radius
        for w in self.shockwaves:
            w.update(dt)
        if self.shockwaves:
            survivors = []
            for b in self.bubbles:
                if any(math.hypot(b.x - w.x, b.y - w.y) <= w.radius
                       for w in self.shockwaves):
                    popped += 1
                    self.score += 1
                    self._burst(b)
                else:
                    survivors.append(b)
            self.bubbles = survivors
            self.shockwaves = [w for w in self.shockwaves if w.alive]

        # Bolts — pop hearts along the flight path, leave a sparkle trail
        if self.bolts:
            for bolt in self.bolts:
                bolt.update(dt)
                self._emit_glitter(bolt.x, bolt.y)
            survivors = []
            for b in self.bubbles:
                if any(math.hypot(b.x - bolt.x, b.y - bolt.y)
                       <= b.radius + BOLT_RADIUS_PX for bolt in self.bolts):
                    popped += 1
                    self.score += 1
                    self._burst(b)
                else:
                    survivors.append(b)
            self.bubbles = survivors
            self.bolts = [bolt for bolt in self.bolts if bolt.alive
                          and -100 < bolt.x < width + 100
                          and -100 < bolt.y < height + 100]

        # Glitter rain — falling drops that pop hearts they land on
        if t < self.rain_until:
            for _ in range(RAIN_DROPS_PER_FRAME):
                self.particles.append(_Particle(
                    x=self.rng.uniform(0, width), y=-5.0,
                    vx=self.rng.uniform(-40, 40),
                    vy=self.rng.uniform(450, 750) * (height / 720.0),
                    color=self.rng.choice(GLITTER_COLORS_RGB),
                    life=3.0, size=self.rng.randint(3, 6),
                    gravity=200.0, kind="rain",
                ))
        drops = [p for p in self.particles if p.kind == "rain" and p.alive]
        if drops:
            survivors = []
            for b in self.bubbles:
                hit = next((p for p in drops
                            if math.hypot(b.x - p.x, b.y - p.y) <= b.radius),
                           None)
                if hit is not None:
                    hit.age = hit.life  # the drop is consumed by the pop
                    popped += 1
                    self.score += 1
                    self._burst(b)
                else:
                    survivors.append(b)
            self.bubbles = survivors

        return popped

    def _burst(self, bubble: Bubble) -> None:
        """Spawn the pop effect: radial droplets + an expanding ring."""
        n = self.rng.randint(14, 20)
        for _ in range(n):
            angle = self.rng.uniform(0, 2 * math.pi)
            speed = self.rng.uniform(120, 320)
            self.particles.append(_Particle(
                x=bubble.x, y=bubble.y,
                vx=speed * math.cos(angle), vy=speed * math.sin(angle),
                color=bubble.color,
                life=self.rng.uniform(0.45, 0.8),
                size=self.rng.randint(2, 5),
                gravity=300.0, kind="dot",
            ))
        self.rings.append(_Ring(bubble.x, bubble.y, bubble.radius, bubble.color))

    def _emit_glitter(self, x: float, y: float) -> None:
        for _ in range(self.glitter_per_wrist):
            self.particles.append(_Particle(
                x=x + self.rng.gauss(0, 12), y=y + self.rng.gauss(0, 12),
                vx=self.rng.uniform(-20, 20), vy=self.rng.uniform(-50, -10),
                color=self.rng.choice(GLITTER_COLORS_RGB),
                life=self.rng.uniform(0.25, 0.5),
                size=self.rng.randint(3, 8),
                gravity=-30.0, kind="spark",
            ))

    # -------------------------------------------------------------------- draw

    def draw(self, frame: np.ndarray, wrists: Sequence[Point]) -> None:
        """Render the game onto ``frame`` (RGB, modified in place)."""
        self._draw_translucent_layer(frame, wrists)
        self._draw_bubble_rims(frame)
        self._draw_rings(frame)
        self._draw_shockwaves(frame)
        self._draw_particles(frame)
        self._draw_bolts(frame)
        self._draw_wrist_cores(frame, wrists)
        self._draw_score(frame)
        self._draw_announce(frame)

    def _draw_translucent_layer(self, frame: np.ndarray,
                                wrists: Sequence[Point]) -> None:
        """Bubble bodies + wrist glow blended in a single pass."""
        if not self.bubbles and not wrists:
            return
        overlay = frame.copy()
        for b in self.bubbles:
            cv2.fillPoly(overlay, [b.polygon()], b.color, cv2.LINE_AA)
        for (x, y) in wrists:
            cv2.circle(overlay, (int(x), int(y)), 22, (255, 230, 120), -1,
                       cv2.LINE_AA)
        cv2.addWeighted(overlay, BUBBLE_ALPHA, frame,
                        1.0 - BUBBLE_ALPHA, 0, dst=frame)

    def _draw_bubble_rims(self, frame: np.ndarray) -> None:
        for b in self.bubbles:
            cx, cy = int(b.x), int(b.y)
            cv2.polylines(frame, [b.polygon()], True, b.color, 2, cv2.LINE_AA)
            # Shine highlight on the upper-left lobe
            hx = cx - int(b.radius * 0.38)
            hy = cy - int(b.radius * 0.42)
            cv2.ellipse(frame, (hx, hy),
                        (max(2, b.radius // 4), max(1, b.radius // 7)),
                        -45, 0, 360, (255, 255, 255), -1, cv2.LINE_AA)

    def _draw_rings(self, frame: np.ndarray) -> None:
        for r in self.rings:
            color = tuple(int(c * r.fade) for c in r.color)
            thickness = max(1, int(3 * r.fade))
            cv2.circle(frame, (int(r.x), int(r.y)), r.radius, color,
                       thickness, cv2.LINE_AA)

    def _draw_particles(self, frame: np.ndarray) -> None:
        for p in self.particles:
            color = tuple(int(c * p.fade) for c in p.color)
            x, y = int(p.x), int(p.y)
            if p.kind == "dot":
                cv2.circle(frame, (x, y), p.size, color, -1, cv2.LINE_AA)
            elif p.kind == "rain":  # falling glitter streak
                cv2.line(frame, (x, y - 2 * p.size), (x, y), color, 2,
                         cv2.LINE_AA)
                cv2.circle(frame, (x, y), 2, (255, 255, 255), -1, cv2.LINE_AA)
            else:  # spark — little 4-pointed star
                arm = p.size
                cv2.line(frame, (x - arm, y), (x + arm, y), color, 1, cv2.LINE_AA)
                cv2.line(frame, (x, y - arm), (x, y + arm), color, 1, cv2.LINE_AA)
                cv2.circle(frame, (x, y), 1, (255, 255, 255), -1, cv2.LINE_AA)

    def _draw_shockwaves(self, frame: np.ndarray) -> None:
        for w in self.shockwaves:
            center = (int(w.x), int(w.y))
            r = int(w.radius)
            cv2.circle(frame, center, r, (255, 255, 255),
                       max(1, int(6 * w.fade)), cv2.LINE_AA)
            cv2.circle(frame, center, max(1, r - 10), (255, 230, 120),
                       max(1, int(3 * w.fade)), cv2.LINE_AA)
            cv2.circle(frame, center, r + 8, (255, 150, 200),
                       1, cv2.LINE_AA)
            # sparkles riding the ring edge
            for i in range(12):
                a = 2 * math.pi * i / 12 + w.age * 3
                sx = int(w.x + r * math.cos(a))
                sy = int(w.y + r * math.sin(a))
                cv2.circle(frame, (sx, sy), 3, (255, 255, 255), -1,
                           cv2.LINE_AA)

    def _draw_bolts(self, frame: np.ndarray) -> None:
        for bolt in self.bolts:
            x, y = int(bolt.x), int(bolt.y)
            cv2.circle(frame, (x, y), 12, (255, 230, 120), -1, cv2.LINE_AA)
            cv2.circle(frame, (x, y), 5, (255, 255, 255), -1, cv2.LINE_AA)
            for arm in (16, 10):
                cv2.line(frame, (x - arm, y), (x + arm, y), (255, 255, 255),
                         1, cv2.LINE_AA)
                cv2.line(frame, (x, y - arm), (x, y + arm), (255, 255, 255),
                         1, cv2.LINE_AA)

    def _draw_announce(self, frame: np.ndarray) -> None:
        if self._t >= self._announce_until or not self._announce_text:
            return
        text = self._announce_text
        (tw, _), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_DUPLEX, 2.2, 3)
        x = max(10, (frame.shape[1] - tw) // 2)
        y = frame.shape[0] // 3
        cv2.putText(frame, text, (x, y), cv2.FONT_HERSHEY_DUPLEX, 2.2,
                    (20, 20, 20), 8, cv2.LINE_AA)
        cv2.putText(frame, text, (x, y), cv2.FONT_HERSHEY_DUPLEX, 2.2,
                    (255, 230, 120), 3, cv2.LINE_AA)

    def _draw_wrist_cores(self, frame: np.ndarray,
                          wrists: Sequence[Point]) -> None:
        for (x, y) in wrists:
            cv2.circle(frame, (int(x), int(y)), 6, (255, 255, 255), -1,
                       cv2.LINE_AA)
            cv2.circle(frame, (int(x), int(y)), 10, (255, 230, 120), 2,
                       cv2.LINE_AA)

    def _draw_score(self, frame: np.ndarray) -> None:
        text = f"Score: {self.score}"
        cv2.putText(frame, text, (24, 60), cv2.FONT_HERSHEY_DUPLEX, 1.6,
                    (20, 20, 20), 6, cv2.LINE_AA)
        cv2.putText(frame, text, (24, 60), cv2.FONT_HERSHEY_DUPLEX, 1.6,
                    (255, 255, 255), 2, cv2.LINE_AA)
