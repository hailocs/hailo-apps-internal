"""Unit tests for gesture_mouse cursor mapping math."""

import sys
from unittest.mock import MagicMock

import pytest

for mod_name in [
    "hailo",
    "gi",
    "gi.repository",
    "gi.repository.Gst",
    "pynput",
    "pynput.mouse",
    "screeninfo",
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()
sys.modules["gi"].require_version = lambda *a, **kw: None

from community.apps.pipeline_apps.gesture_mouse.gesture_mouse import (
    map_index_to_screen,
)


SCREEN_W = 1920
SCREEN_H = 1080


class TestMapIndexToScreenSpeed1:
    """With speed=1.0 the full camera frame maps to the full screen (mirrored)."""

    def test_center_maps_to_center(self):
        px, py = map_index_to_screen(0.5, 0.5, 1.0, SCREEN_W, SCREEN_H)
        assert px == pytest.approx(SCREEN_W * 0.5)
        assert py == pytest.approx(SCREEN_H * 0.5)

    def test_camera_left_maps_to_screen_right(self):
        # norm_x=0 (camera left edge) -> mirrored to right of screen
        px, py = map_index_to_screen(0.0, 0.5, 1.0, SCREEN_W, SCREEN_H)
        assert px == pytest.approx(SCREEN_W)

    def test_camera_right_maps_to_screen_left(self):
        px, py = map_index_to_screen(1.0, 0.5, 1.0, SCREEN_W, SCREEN_H)
        assert px == pytest.approx(0.0)

    def test_camera_top_maps_to_screen_top(self):
        px, py = map_index_to_screen(0.5, 0.0, 1.0, SCREEN_W, SCREEN_H)
        assert py == pytest.approx(0.0)

    def test_camera_bottom_maps_to_screen_bottom(self):
        px, py = map_index_to_screen(0.5, 1.0, 1.0, SCREEN_W, SCREEN_H)
        assert py == pytest.approx(SCREEN_H)


class TestMapIndexToScreenSpeed2:
    """With speed=2.0 the inner 50% of the frame maps to the full screen."""

    def test_inside_zone_center_maps_to_center(self):
        # norm_x=0.5 is exact center, irrespective of speed
        px, py = map_index_to_screen(0.5, 0.5, 2.0, SCREEN_W, SCREEN_H)
        assert px == pytest.approx(SCREEN_W * 0.5)
        assert py == pytest.approx(SCREEN_H * 0.5)

    def test_inside_zone_edge_maps_to_screen_edge(self):
        # margin = (1 - 0.5)/2 = 0.25. zone is [0.25, 0.75].
        # norm_x = 0.25 (mirrored to 0.75) -> at the right edge of zone
        # -> after mirror, that's the left of zone, so maps to left of screen.
        # norm_x = 0.75 (mirrored to 0.25) -> right edge of zone -> right of screen.
        px_right, _ = map_index_to_screen(0.25, 0.5, 2.0, SCREEN_W, SCREEN_H)
        assert px_right == pytest.approx(SCREEN_W)
        px_left, _ = map_index_to_screen(0.75, 0.5, 2.0, SCREEN_W, SCREEN_H)
        assert px_left == pytest.approx(0.0)

    def test_outside_zone_clamps_to_screen_edge(self):
        # norm_x=0.1 is left of the 0.25 zone -> mirrored to 0.9 which is right
        # of the 0.75 zone -> clamps to screen right (1920).
        px, _ = map_index_to_screen(0.1, 0.5, 2.0, SCREEN_W, SCREEN_H)
        assert px == pytest.approx(SCREEN_W)

    def test_outside_zone_other_side_clamps_to_zero(self):
        # norm_x=0.9 is right of zone -> mirrored to 0.1 -> left of zone -> 0.
        px, _ = map_index_to_screen(0.9, 0.5, 2.0, SCREEN_W, SCREEN_H)
        assert px == pytest.approx(0.0)


class TestMapIndexToScreenDegenerate:
    def test_speed_less_than_one_does_not_crash(self):
        # speed=0.5 -> margin=max(0, (1 - 2)/2) = max(0, -0.5) = 0
        # zone_size = 1.0, behaves like speed=1.0 (no zoom).
        px, py = map_index_to_screen(0.5, 0.5, 0.5, SCREEN_W, SCREEN_H)
        assert px == pytest.approx(SCREEN_W * 0.5)
        assert py == pytest.approx(SCREEN_H * 0.5)

    def test_speed_zero_fallback(self):
        px, py = map_index_to_screen(0.5, 0.5, 0.0, SCREEN_W, SCREEN_H)
        assert px == pytest.approx(SCREEN_W * 0.5)
        assert py == pytest.approx(SCREEN_H * 0.5)


class TestClampOutputRange:
    @pytest.mark.parametrize("norm_x", [-0.5, 0.0, 0.5, 1.0, 1.5])
    @pytest.mark.parametrize("norm_y", [-0.5, 0.0, 0.5, 1.0, 1.5])
    @pytest.mark.parametrize("speed", [1.0, 1.5, 2.0, 3.0])
    def test_output_always_in_screen_bounds(self, norm_x, norm_y, speed):
        px, py = map_index_to_screen(norm_x, norm_y, speed, SCREEN_W, SCREEN_H)
        assert 0.0 <= px <= SCREEN_W
        assert 0.0 <= py <= SCREEN_H
