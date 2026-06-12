"""Unit tests for gesture detection and magic effects (pure logic)."""

import os
import sys

import numpy as np

_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..")
)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from community.apps.pipeline_apps.bubble_pop.bubble_engine import BubbleGame
from community.apps.pipeline_apps.bubble_pop.gestures import (
    GestureCaster,
    PersonPose,
)

WIDTH, HEIGHT = 1280, 720


def _pose(lw, rw, nose=(640.0, 200.0), shoulder_w=200.0):
    return PersonPose(left_wrist=lw, right_wrist=rw, nose=nose,
                      shoulder_width=shoulder_w)


# ----------------------------------------------------------------- gestures

def test_hands_together_fires_shockwave_once():
    c = GestureCaster(HEIGHT)
    apart = _pose((400.0, 400.0), (800.0, 400.0))
    together = _pose((630.0, 400.0), (650.0, 400.0))
    assert c.update(0.0, {1: apart}) == []
    events = c.update(0.1, {1: together})
    assert events == [("shockwave", 640.0, 400.0)]
    # held together → no retrigger
    assert c.update(0.2, {1: together}) == []


def test_arms_up_fires_rain():
    c = GestureCaster(HEIGHT)
    down = _pose((400.0, 500.0), (800.0, 500.0))
    up = _pose((400.0, 100.0), (800.0, 100.0))  # above nose y=200
    assert c.update(0.0, {1: down}) == []
    assert ("rain",) in c.update(0.1, {1: up})
    # held up → no retrigger
    assert c.update(0.2, {1: up}) == []


def test_fast_swipe_fires_bolt_in_motion_direction():
    c = GestureCaster(HEIGHT)
    p0 = _pose((400.0, 400.0), None)
    p1 = _pose((480.0, 400.0), None)  # 80 px in 1/30 s = 2400 px/s
    c.update(0.0, {1: p0})
    events = c.update(1 / 30, {1: p1})
    assert len(events) == 1
    kind, x, y, vx, vy = events[0]
    assert kind == "bolt"
    assert (x, y) == (480.0, 400.0)
    assert vx > 0 and abs(vy) < 1e-6  # rightward flick → rightward bolt


def test_slow_movement_no_bolt():
    c = GestureCaster(HEIGHT)
    c.update(0.0, {1: _pose((400.0, 400.0), None)})
    events = c.update(1 / 30, {1: _pose((405.0, 400.0), None)})
    assert events == []


# ------------------------------------------------------------- magic effects

def _spawn_hearts(game, t_end=2.0):
    t = 0.0
    while t < t_end:
        game.update(1 / 30, t, [], WIDTH, HEIGHT)
        t += 1 / 30
    assert game.bubbles
    return t


def test_shockwave_pops_hearts():
    game = BubbleGame(seed=3)
    t = _spawn_hearts(game)
    n = len(game.bubbles)
    b = game.bubbles[0]
    game.cast(("shockwave", b.x, b.y), t)
    # let the wave expand across the whole frame
    for _ in range(30):
        game.update(1 / 30, t, [], WIDTH, HEIGHT)
        t += 1 / 30
    assert game.score >= n  # everything on screen got popped


def test_bolt_pops_heart_on_path():
    game = BubbleGame(seed=3)
    t = _spawn_hearts(game)
    b = game.bubbles[0]
    game.cast(("bolt", b.x - 100.0, b.y, 750.0, 0.0), t)  # flying right at it
    popped = 0
    for _ in range(15):
        popped += game.update(1 / 30, t, [], WIDTH, HEIGHT)
        t += 1 / 30
    assert popped >= 1


def test_rain_spawns_drops_and_announces():
    game = BubbleGame(seed=3)
    game.cast(("rain",), 1.0)
    game.update(1 / 30, 1.0, [], WIDTH, HEIGHT)
    assert [p for p in game.particles if p.kind == "rain"]
    assert game._announce_text == "GLITTER RAIN!"


def test_magic_draw_smoke():
    game = BubbleGame(seed=3)
    t = _spawn_hearts(game)
    game.cast(("shockwave", 600.0, 400.0), t)
    game.cast(("rain",), t)
    game.cast(("bolt", 100.0, 100.0, 750.0, 0.0), t)
    game.update(1 / 30, t, [], WIDTH, HEIGHT)
    frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    game.draw(frame, [(200.0, 200.0)])
    assert frame.any()
