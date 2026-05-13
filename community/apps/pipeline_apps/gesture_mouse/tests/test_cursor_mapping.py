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
    PALM_ANCHOR_LANDMARKS,
    _palm_center_position,
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


class _MockPoint:
    def __init__(self, x, y):
        self._x = x
        self._y = y

    def x(self):
        return self._x

    def y(self):
        return self._y


class _MockLandmarks:
    def __init__(self, points):
        self._points = points

    def get_points(self):
        return self._points


class _MockBbox:
    def __init__(self, xmin=0.0, ymin=0.0, width=1.0, height=1.0):
        self._xmin = xmin
        self._ymin = ymin
        self._w = width
        self._h = height

    def xmin(self):
        return self._xmin

    def ymin(self):
        return self._ymin

    def width(self):
        return self._w

    def height(self):
        return self._h


class _MockDetection:
    """Mimics enough of a HailoDetection interface for landmark math tests."""

    def __init__(self, landmark_positions, bbox=None):
        self._landmarks = [_MockLandmarks([_MockPoint(x, y) for x, y in landmark_positions])]
        self._bbox = bbox or _MockBbox()

    def get_objects_typed(self, _type):
        # The real impl filters by type id; here we always return landmarks.
        return self._landmarks

    def get_bbox(self):
        return self._bbox


class TestPalmCenterPosition:
    """The palm anchor is the average of WRIST + 4 MCP joints. Moving the
    thumb or finger TIPs should not change the result."""

    def _make_hand(self, mcp_positions, tip_positions=None):
        """Build 21 landmarks. mcp_positions is dict {landmark_idx: (x, y)}."""
        if tip_positions is None:
            tip_positions = {}
        # Default everything to (0.5, 0.5) then overwrite specifics.
        points = [(0.5, 0.5)] * 21
        for idx, pos in mcp_positions.items():
            points[idx] = pos
        for idx, pos in tip_positions.items():
            points[idx] = pos
        return _MockDetection(points, bbox=_MockBbox(0.0, 0.0, 1.0, 1.0))

    def test_palm_anchor_landmarks_count(self):
        assert len(PALM_ANCHOR_LANDMARKS) == 5

    def test_palm_center_is_average_of_anchors(self):
        # Place each of the 5 anchor landmarks at distinct positions.
        positions = {
            0: (0.10, 0.20),   # WRIST
            5: (0.30, 0.40),   # INDEX_MCP
            9: (0.50, 0.60),   # MIDDLE_MCP
            13: (0.70, 0.40),  # RING_MCP
            17: (0.90, 0.20),  # PINKY_MCP
        }
        det = self._make_hand(positions)
        # Frame is 1000x1000 so pixel = normalized * 1000
        px, py = _palm_center_position(det, 1000, 1000)
        expected_x = sum(p[0] for p in positions.values()) / 5 * 1000
        expected_y = sum(p[1] for p in positions.values()) / 5 * 1000
        assert px == pytest.approx(expected_x)
        assert py == pytest.approx(expected_y)

    def test_palm_center_unchanged_when_index_tip_moves(self):
        """The critical property: pinching (moving INDEX_TIP toward THUMB_TIP)
        must NOT shift the cursor anchor."""
        mcp = {0: (0.5, 0.5), 5: (0.5, 0.5), 9: (0.5, 0.5), 13: (0.5, 0.5), 17: (0.5, 0.5)}
        det_open = self._make_hand(mcp, tip_positions={8: (0.5, 0.1), 4: (0.1, 0.5)})
        det_pinched = self._make_hand(mcp, tip_positions={8: (0.3, 0.3), 4: (0.3, 0.3)})

        open_x, open_y = _palm_center_position(det_open, 1000, 1000)
        pinched_x, pinched_y = _palm_center_position(det_pinched, 1000, 1000)
        assert open_x == pytest.approx(pinched_x)
        assert open_y == pytest.approx(pinched_y)


class TestClampOutputRange:
    @pytest.mark.parametrize("norm_x", [-0.5, 0.0, 0.5, 1.0, 1.5])
    @pytest.mark.parametrize("norm_y", [-0.5, 0.0, 0.5, 1.0, 1.5])
    @pytest.mark.parametrize("speed", [1.0, 1.5, 2.0, 3.0])
    def test_output_always_in_screen_bounds(self, norm_x, norm_y, speed):
        px, py = map_index_to_screen(norm_x, norm_y, speed, SCREEN_W, SCREEN_H)
        assert 0.0 <= px <= SCREEN_W
        assert 0.0 <= py <= SCREEN_H
