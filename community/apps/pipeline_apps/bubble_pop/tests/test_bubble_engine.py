"""Unit tests for the Bubble Pop game engine (pure logic, no hardware)."""

import os
import sys

import numpy as np
import pytest

_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..")
)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from community.apps.pipeline_apps.bubble_pop.bubble_engine import (
    Bubble,
    BubbleGame,
    POP_MARGIN_PX,
)

WIDTH, HEIGHT = 1280, 720


@pytest.fixture
def game():
    return BubbleGame(max_bubbles=5, spawn_interval=0.5, seed=42)


def _advance(game, t0, t1, step=1 / 30, wrists=()):
    """Run game.update() in fixed steps from t0 to t1, return total pops."""
    popped = 0
    t = t0
    while t < t1:
        popped += game.update(step, t, list(wrists), WIDTH, HEIGHT)
        t += step
    return popped


def test_bubble_rises():
    b = Bubble(__import__("random").Random(1), WIDTH, HEIGHT)
    y0 = b.y
    b.update(0.5, t=1.0)
    assert b.y < y0


def test_bubble_offscreen_at_top():
    b = Bubble(__import__("random").Random(1), WIDTH, HEIGHT)
    b.y = -b.radius - 1
    assert b.offscreen()


def test_spawn_respects_max_bubbles(game):
    _advance(game, 0.0, 30.0)
    assert 0 < len(game.bubbles) <= game.max_bubbles


def test_pop_at_bubble_center(game):
    _advance(game, 0.0, 1.0)  # let at least one bubble spawn
    assert game.bubbles, "expected a bubble to spawn"
    b = game.bubbles[0]
    # overlapping bubbles may pop together — assert at least the touched one
    popped = game.update(1 / 30, 1.0, [(b.x, b.y)], WIDTH, HEIGHT)
    assert popped >= 1
    assert game.score == popped
    assert b not in game.bubbles
    assert game.particles, "pop should create burst particles"
    assert game.rings, "pop should create an expanding ring"


def test_no_pop_when_far(game):
    _advance(game, 0.0, 1.0)
    assert game.bubbles
    b = game.bubbles[0]
    far = (b.x + b.radius + POP_MARGIN_PX + 50, b.y)
    popped = game.update(1 / 30, 1.0, [far], WIDTH, HEIGHT)
    assert popped == 0
    assert game.score == 0


def test_glitter_emitted_per_wrist(game):
    game.update(1 / 30, 0.0, [(100.0, 100.0), (500.0, 300.0)], WIDTH, HEIGHT)
    sparks = [p for p in game.particles if p.kind == "spark"]
    assert len(sparks) == 2 * game.glitter_per_wrist


def test_particles_expire(game):
    game.update(1 / 30, 0.0, [(100.0, 100.0)], WIDTH, HEIGHT)
    assert game.particles
    # advance well past max particle lifetime with no new wrists
    _advance(game, 1.0, 3.0)
    assert not [p for p in game.particles if p.kind == "spark"]


def test_draw_smoke(game):
    """draw() runs without error and actually modifies the frame."""
    _advance(game, 0.0, 2.0)
    frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    game.draw(frame, [(200.0, 200.0)])
    assert frame.any(), "draw() should render bubbles/HUD onto the frame"


def test_deterministic_with_seed():
    g1 = BubbleGame(seed=7)
    g2 = BubbleGame(seed=7)
    _advance(g1, 0.0, 2.0)
    _advance(g2, 0.0, 2.0)
    assert [(b.x, b.y, b.radius) for b in g1.bubbles] == \
           [(b.x, b.y, b.radius) for b in g2.bubbles]
