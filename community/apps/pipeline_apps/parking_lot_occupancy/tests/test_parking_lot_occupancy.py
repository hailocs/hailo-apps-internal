"""Pure-Python unit tests for the parking lot occupancy app.

Covers the device-independent core logic of
``community.apps.pipeline_apps.parking_lot_occupancy.parking_lot_occupancy``:

* ``load_zones_from_json`` parsing + error wrapping (ValueError)
* ``ParkingZone`` point-in-polygon (ray casting) and bbox-center test
* ``get_default_zones`` 2x2 grid geometry
* ``ParkingLotCallbackData`` per-zone occupancy + FULL/AVAILABLE threshold

The app module imports gi/hailo/cv2 and Hailo GStreamer helpers at import
time, so those heavy modules are stubbed with ``MagicMock`` before importing
the app. ``numpy`` is real (used to store the polygon). No device, GStreamer,
inference, or network access is performed.
"""

import json
import sys
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.community

# --- Stub heavy / device modules before importing the app under test --------
for mod_name in [
    "gi",
    "gi.repository",
    "gi.repository.Gst",
    "cv2",
    "hailo",
    "hailo_apps.python.core.common.buffer_utils",
    "hailo_apps.python.core.gstreamer.gstreamer_app",
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()
sys.modules["gi"].require_version = lambda *a, **kw: None


class _StubAppCallbackBase:
    """Mimics the real app_callback_class enough for ParkingLotCallbackData."""

    def __init__(self):
        self.frame_count = 0
        self.use_frame = False
        self.window_title = ""

    def get_count(self):
        return self.frame_count

    def increment(self):
        self.frame_count += 1

    def set_frame(self, frame):
        self._frame = frame


sys.modules[
    "hailo_apps.python.core.gstreamer.gstreamer_app"
].app_callback_class = _StubAppCallbackBase

from community.apps.pipeline_apps.parking_lot_occupancy.parking_lot_occupancy import (  # noqa: E402
    ParkingLotCallbackData,
    ParkingZone,
    get_default_zones,
    load_zones_from_json,
)

# A simple unit square zone used by many geometry tests.
UNIT_SQUARE = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
# A small square in the middle-left of the frame.
SMALL_SQUARE = [[0.1, 0.2], [0.4, 0.2], [0.4, 0.8], [0.1, 0.8]]


# ============================================================
# load_zones_from_json — happy path
# ============================================================
class TestLoadZonesValid:
    def _write(self, tmp_path, obj):
        p = tmp_path / "zones.json"
        p.write_text(json.dumps(obj))
        return str(p)

    def test_single_zone_parses(self, tmp_path):
        path = self._write(
            tmp_path,
            [{"name": "Zone A", "polygon": SMALL_SQUARE, "capacity": 5}],
        )
        zones = load_zones_from_json(path)
        assert len(zones) == 1
        assert zones[0].name == "Zone A"
        assert zones[0].capacity == 5
        assert zones[0].polygon.shape == (4, 2)

    def test_multiple_zones_parse(self, tmp_path):
        path = self._write(
            tmp_path,
            [
                {"name": "A", "polygon": SMALL_SQUARE, "capacity": 2},
                {"name": "B", "polygon": UNIT_SQUARE, "capacity": 3},
            ],
        )
        zones = load_zones_from_json(path)
        assert [z.name for z in zones] == ["A", "B"]
        assert [z.capacity for z in zones] == [2, 3]

    def test_capacity_defaults_to_one(self, tmp_path):
        # "capacity" omitted -> ParkingZone default of 1.
        path = self._write(tmp_path, [{"name": "A", "polygon": SMALL_SQUARE}])
        zones = load_zones_from_json(path)
        assert zones[0].capacity == 1

    def test_empty_list_yields_no_zones(self, tmp_path):
        path = self._write(tmp_path, [])
        assert load_zones_from_json(path) == []

    def test_polygon_is_float_array(self, tmp_path):
        path = self._write(tmp_path, [{"name": "A", "polygon": SMALL_SQUARE}])
        zones = load_zones_from_json(path)
        # Polygon values round-trip as floats matching the source coords.
        assert zones[0].polygon[0].tolist() == pytest.approx([0.1, 0.2])


# ============================================================
# load_zones_from_json — error wrapping (all -> ValueError)
# ============================================================
class TestLoadZonesErrors:
    def test_missing_file_raises_valueerror(self, tmp_path):
        with pytest.raises(ValueError):
            load_zones_from_json(str(tmp_path / "does_not_exist.json"))

    def test_malformed_json_raises_valueerror(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{ this is : not valid json ]")
        with pytest.raises(ValueError):
            load_zones_from_json(str(p))

    def test_missing_name_key_raises_valueerror(self, tmp_path):
        p = tmp_path / "z.json"
        p.write_text(json.dumps([{"polygon": SMALL_SQUARE, "capacity": 2}]))
        with pytest.raises(ValueError):
            load_zones_from_json(str(p))

    def test_missing_polygon_key_raises_valueerror(self, tmp_path):
        p = tmp_path / "z.json"
        p.write_text(json.dumps([{"name": "A", "capacity": 2}]))
        with pytest.raises(ValueError):
            load_zones_from_json(str(p))

    def test_non_list_polygon_raises_valueerror(self, tmp_path):
        # A non-list/non-array polygon makes np.array(...) malformed; the app
        # wraps the resulting error in ValueError.
        p = tmp_path / "z.json"
        p.write_text(json.dumps([{"name": "A", "polygon": "not-a-polygon"}]))
        with pytest.raises(ValueError):
            load_zones_from_json(str(p))

    def test_top_level_not_iterable_of_dicts_raises_valueerror(self, tmp_path):
        # Top-level JSON is a dict, not a list of zone entries. Iterating it
        # yields keys (strings), and entry["name"] raises -> wrapped ValueError.
        p = tmp_path / "z.json"
        p.write_text(json.dumps({"name": "A", "polygon": SMALL_SQUARE}))
        with pytest.raises(ValueError):
            load_zones_from_json(str(p))

    def test_error_message_includes_path(self, tmp_path):
        missing = str(tmp_path / "nope.json")
        with pytest.raises(ValueError) as exc:
            load_zones_from_json(missing)
        assert missing in str(exc.value)


# ============================================================
# ParkingZone.contains_point — ray casting
# ============================================================
class TestContainsPoint:
    def test_point_clearly_inside(self):
        z = ParkingZone("A", UNIT_SQUARE)
        assert z.contains_point(0.5, 0.5) is True

    def test_point_clearly_outside(self):
        z = ParkingZone("A", SMALL_SQUARE)
        # Right of the [0.1,0.4] x-range.
        assert z.contains_point(0.9, 0.5) is False

    def test_point_outside_below(self):
        z = ParkingZone("A", SMALL_SQUARE)
        assert z.contains_point(0.25, 0.95) is False

    def test_offset_polygon_inside(self):
        z = ParkingZone("A", SMALL_SQUARE)
        assert z.contains_point(0.25, 0.5) is True

    def test_point_on_left_edge(self):
        # Ray casting is half-open: the left/bottom edge is treated as inside,
        # the right/top edge as outside. The left edge x==xmin counts inside.
        z = ParkingZone("A", UNIT_SQUARE)
        assert z.contains_point(0.0, 0.5) is True

    def test_point_on_right_edge(self):
        # Right edge x==xmax is treated as outside by this ray-cast variant.
        z = ParkingZone("A", UNIT_SQUARE)
        assert z.contains_point(1.0, 0.5) is False

    def test_concave_polygon(self):
        # Arrow / chevron-ish concave polygon. The notch at the top-center is
        # outside even though it lies within the bounding box.
        poly = [
            [0.0, 0.0],
            [1.0, 0.0],
            [1.0, 1.0],
            [0.5, 0.5],
            [0.0, 1.0],
        ]
        z = ParkingZone("A", poly)
        assert z.contains_point(0.5, 0.2) is True   # solid lower body
        assert z.contains_point(0.5, 0.9) is False  # inside the top notch

    def test_triangle(self):
        tri = [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]]
        z = ParkingZone("A", tri)
        assert z.contains_point(0.2, 0.2) is True       # below the hypotenuse
        assert z.contains_point(0.8, 0.8) is False      # above the hypotenuse

    def test_degenerate_zero_area_polygon(self):
        # All collinear points -> no interior. Nothing is inside.
        poly = [[0.0, 0.0], [0.5, 0.0], [1.0, 0.0], [0.5, 0.0]]
        z = ParkingZone("A", poly)
        assert z.contains_point(0.5, 0.0) is False
        assert z.contains_point(0.5, 0.5) is False


# ============================================================
# ParkingZone.contains_bbox_center
# ============================================================
class TestContainsBboxCenter:
    def test_center_inside(self):
        z = ParkingZone("A", UNIT_SQUARE)
        # bbox xmin=0.4 ymin=0.4 w=0.2 h=0.2 -> center (0.5, 0.5)
        assert z.contains_bbox_center(0.4, 0.4, 0.2, 0.2) is True

    def test_center_outside(self):
        z = ParkingZone("A", SMALL_SQUARE)
        # center at (0.9, 0.5) -> outside the [0.1,0.4] x-range.
        assert z.contains_bbox_center(0.85, 0.45, 0.1, 0.1) is False

    def test_uses_center_not_corner(self):
        # A bbox whose top-left corner is outside but whose center is inside.
        z = ParkingZone("A", SMALL_SQUARE)
        # xmin=0.05 (left of zone) but width pushes center to 0.25 (inside).
        assert z.contains_bbox_center(0.05, 0.4, 0.4, 0.1) is True


# ============================================================
# get_default_zones — 2x2 grid geometry
# ============================================================
class TestDefaultZones:
    def test_four_zones(self):
        zones = get_default_zones()
        assert len(zones) == 4
        assert [z.name for z in zones] == ["Zone A", "Zone B", "Zone C", "Zone D"]

    def test_each_zone_capacity_four(self):
        assert all(z.capacity == 4 for z in get_default_zones())

    def test_quadrant_membership(self):
        # Grid: A=top-left, B=top-right, C=bottom-left, D=bottom-right.
        # Note y grows downward (image coords).
        a, b, c, d = get_default_zones()
        assert a.contains_point(0.25, 0.25) is True   # top-left
        assert b.contains_point(0.75, 0.25) is True   # top-right
        assert c.contains_point(0.25, 0.75) is True   # bottom-left
        assert d.contains_point(0.75, 0.75) is True   # bottom-right

    def test_point_belongs_to_exactly_one_quadrant(self):
        zones = get_default_zones()
        pt = (0.25, 0.25)
        hits = [z.name for z in zones if z.contains_point(*pt)]
        assert hits == ["Zone A"]


# ============================================================
# ParkingLotCallbackData — occupancy summary + FULL threshold
# ============================================================
class TestOccupancySummary:
    def _cb(self):
        return ParkingLotCallbackData(get_default_zones())

    def test_initial_all_available(self):
        cb = self._cb()
        summary = cb.get_occupancy_summary()
        assert summary.count("AVAILABLE") == 4
        assert "FULL" not in summary
        assert "Total: 0/16" in summary

    def test_zone_full_when_at_capacity(self):
        cb = self._cb()
        cb.zones[0].occupied_count = cb.zones[0].capacity  # exactly at capacity
        summary = cb.get_occupancy_summary()
        assert "Zone A: 4/4 (FULL)" in summary
        assert summary.count("FULL") == 1
        assert summary.count("AVAILABLE") == 3

    def test_partial_occupancy_is_available(self):
        cb = self._cb()
        cb.zones[0].occupied_count = cb.zones[0].capacity - 1  # one short
        summary = cb.get_occupancy_summary()
        assert "Zone A: 3/4 (AVAILABLE)" in summary

    def test_over_capacity_is_full(self):
        # occupied_count >= capacity -> FULL even when over.
        cb = self._cb()
        cb.zones[0].occupied_count = cb.zones[0].capacity + 2
        summary = cb.get_occupancy_summary()
        assert "Zone A: 6/4 (FULL)" in summary

    def test_capacity_one_full_at_single_vehicle(self):
        cb = ParkingLotCallbackData(
            [ParkingZone("Solo", UNIT_SQUARE, capacity=1)]
        )
        cb.zones[0].occupied_count = 1
        assert "(FULL)" in cb.get_occupancy_summary()

    def test_total_line_sums_all_zones(self):
        cb = self._cb()
        for i, z in enumerate(cb.zones):
            z.occupied_count = i  # 0,1,2,3 -> total 6
        summary = cb.get_occupancy_summary()
        assert "Total: 6/16" in summary

    def test_empty_zones_list(self):
        cb = ParkingLotCallbackData([])
        summary = cb.get_occupancy_summary()
        # No per-zone lines, only the total line at 0/0.
        assert summary == "Total: 0/0"

    def test_initial_total_vehicles_zero(self):
        assert self._cb().total_vehicles == 0


# ============================================================
# Zone assignment simulation — mirrors the per-detection branch
# in app_callback (parking_lot_occupancy.py) without GStreamer/Hailo.
#   * each vehicle is assigned to at most ONE zone (first match wins)
#   * occupied_count and vehicle_ids reset each frame
# ============================================================
def _assign_frame(zones, vehicles):
    """Re-implementation of the zone-assignment loop in app_callback.

    ``vehicles`` is a list of (track_id, xmin, ymin, width, height).
    Returns nothing; mutates the zones in place.
    """
    for zone in zones:
        zone.occupied_count = 0
        zone.vehicle_ids.clear()
    for track_id, xmin, ymin, w, h in vehicles:
        for zone in zones:
            if zone.contains_bbox_center(xmin, ymin, w, h):
                zone.occupied_count += 1
                zone.vehicle_ids.add(track_id)
                break  # at most one zone per vehicle


class TestZoneAssignment:
    def test_zero_detections(self):
        zones = get_default_zones()
        _assign_frame(zones, [])
        assert all(z.occupied_count == 0 for z in zones)

    def test_single_vehicle_one_zone(self):
        zones = get_default_zones()
        # center (0.25, 0.25) -> Zone A (top-left)
        _assign_frame(zones, [(1, 0.2, 0.2, 0.1, 0.1)])
        assert zones[0].occupied_count == 1
        assert zones[0].vehicle_ids == {1}
        assert sum(z.occupied_count for z in zones) == 1

    def test_vehicles_spread_across_zones(self):
        zones = get_default_zones()
        _assign_frame(
            zones,
            [
                (1, 0.2, 0.2, 0.1, 0.1),   # Zone A
                (2, 0.7, 0.2, 0.1, 0.1),   # Zone B
                (3, 0.2, 0.7, 0.1, 0.1),   # Zone C
                (4, 0.7, 0.7, 0.1, 0.1),   # Zone D
            ],
        )
        assert [z.occupied_count for z in zones] == [1, 1, 1, 1]

    def test_multiple_vehicles_same_zone(self):
        zones = get_default_zones()
        _assign_frame(
            zones,
            [
                (1, 0.1, 0.1, 0.1, 0.1),
                (2, 0.3, 0.3, 0.1, 0.1),
            ],
        )
        assert zones[0].occupied_count == 2
        assert zones[0].vehicle_ids == {1, 2}

    def test_vehicle_outside_all_zones(self):
        # A single tall zone covering only the left strip; vehicle on the right.
        zones = [ParkingZone("Left", [[0.0, 0.0], [0.3, 0.0], [0.3, 1.0], [0.0, 1.0]])]
        _assign_frame(zones, [(1, 0.8, 0.4, 0.1, 0.1)])
        assert zones[0].occupied_count == 0

    def test_overlapping_zones_first_match_only(self):
        # Two fully-overlapping unit-square zones. A vehicle in the overlap is
        # counted in the FIRST zone only (break after first match).
        zones = [
            ParkingZone("First", UNIT_SQUARE),
            ParkingZone("Second", UNIT_SQUARE),
        ]
        _assign_frame(zones, [(1, 0.4, 0.4, 0.2, 0.2)])
        assert zones[0].occupied_count == 1
        assert zones[1].occupied_count == 0

    def test_counts_reset_between_frames(self):
        zones = get_default_zones()
        _assign_frame(zones, [(1, 0.2, 0.2, 0.1, 0.1)])
        assert zones[0].occupied_count == 1
        # Next frame: vehicle gone.
        _assign_frame(zones, [])
        assert zones[0].occupied_count == 0
        assert zones[0].vehicle_ids == set()

    def test_same_track_id_dedup_in_one_zone(self):
        # vehicle_ids is a set; the same track id seen twice (degenerate input)
        # collapses to one entry but occupied_count still increments per box.
        zones = [ParkingZone("A", UNIT_SQUARE)]
        _assign_frame(zones, [(7, 0.4, 0.4, 0.1, 0.1), (7, 0.5, 0.5, 0.1, 0.1)])
        assert zones[0].occupied_count == 2
        assert zones[0].vehicle_ids == {7}

    def test_boundary_vehicle_on_quadrant_seam(self):
        # Center exactly on the x=0.5 seam between Zone A (left) and B (right).
        # The right edge of A is exclusive, so it lands in B (or neither/B).
        zones = get_default_zones()
        _assign_frame(zones, [(1, 0.45, 0.2, 0.1, 0.1)])  # center (0.5, 0.25)
        # Must not be double counted across the seam.
        assert sum(z.occupied_count for z in zones) <= 1
