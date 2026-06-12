# region imports
# Standard library imports
import argparse
import json
import os

os.environ["GST_PLUGIN_FEATURE_RANK"] = "vaapidecodebin:NONE"

# Third-party imports
import gi

gi.require_version("Gst", "1.0")
import cv2
import numpy as np

# Local application-specific imports
import hailo
from gi.repository import Gst

from community.apps.pipeline_apps.parking_lot_occupancy.parking_lot_occupancy_pipeline import (
    GStreamerParkingLotApp,
    VEHICLE_LABELS,
)
from hailo_apps.python.core.common.buffer_utils import (
    get_caps_from_pad,
    get_numpy_from_buffer,
)

from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.gstreamer.gstreamer_app import app_callback_class

hailo_logger = get_logger(__name__)
# endregion imports


# -----------------------------------------------------------------------------------------------
# Parking Zone definition
# -----------------------------------------------------------------------------------------------


class ParkingZone:
    """Represents a single parking zone defined by a polygon in normalized coordinates."""

    def __init__(self, name, polygon, capacity=1):
        """
        Args:
            name: Display name for the zone (e.g., "Zone A").
            polygon: List of [x, y] points in normalized [0,1] coordinates.
            capacity: Number of parking spots in this zone.
        """
        self.name = name
        self.polygon = np.array(polygon, dtype=np.float32)
        self.capacity = capacity
        self.occupied_count = 0
        self.vehicle_ids = set()

    def contains_point(self, x, y):
        """Check if a point (normalized coords) is inside the zone polygon.

        Uses the ray-casting algorithm for point-in-polygon test.
        """
        n = len(self.polygon)
        inside = False
        j = n - 1
        for i in range(n):
            xi, yi = self.polygon[i]
            xj, yj = self.polygon[j]
            if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
                inside = not inside
            j = i
        return inside

    def contains_bbox_center(self, xmin, ymin, width, height):
        """Check if the center of a bounding box falls within this zone."""
        cx = xmin + width / 2.0
        cy = ymin + height / 2.0
        return self.contains_point(cx, cy)


def load_zones_from_json(json_path):
    """Load parking zone definitions from a JSON file.

    Expected format:
    [
        {
            "name": "Zone A",
            "polygon": [[0.1, 0.2], [0.4, 0.2], [0.4, 0.8], [0.1, 0.8]],
            "capacity": 5
        },
        ...
    ]
    """
    with open(json_path, "r") as f:
        data = json.load(f)
    zones = []
    for entry in data:
        zone = ParkingZone(
            name=entry["name"],
            polygon=entry["polygon"],
            capacity=entry.get("capacity", 1),
        )
        zones.append(zone)
    return zones


def get_default_zones():
    """Return default demo zones covering the frame in a 2x2 grid."""
    return [
        ParkingZone("Zone A", [[0.0, 0.0], [0.5, 0.0], [0.5, 0.5], [0.0, 0.5]], capacity=4),
        ParkingZone("Zone B", [[0.5, 0.0], [1.0, 0.0], [1.0, 0.5], [0.5, 0.5]], capacity=4),
        ParkingZone("Zone C", [[0.0, 0.5], [0.5, 0.5], [0.5, 1.0], [0.0, 1.0]], capacity=4),
        ParkingZone("Zone D", [[0.5, 0.5], [1.0, 0.5], [1.0, 1.0], [0.5, 1.0]], capacity=4),
    ]


# -----------------------------------------------------------------------------------------------
# User-defined class to be used in the callback function
# -----------------------------------------------------------------------------------------------


class ParkingLotCallbackData(app_callback_class):
    def __init__(self, zones):
        super().__init__()
        self.zones = zones
        self.total_vehicles = 0

    def get_occupancy_summary(self):
        """Return a summary string of zone occupancy."""
        lines = []
        total_occupied = 0
        total_capacity = 0
        for zone in self.zones:
            status = "FULL" if zone.occupied_count >= zone.capacity else "AVAILABLE"
            lines.append(
                f"{zone.name}: {zone.occupied_count}/{zone.capacity} ({status})"
            )
            total_occupied += zone.occupied_count
            total_capacity += zone.capacity
        lines.append(f"Total: {total_occupied}/{total_capacity}")
        return "\n".join(lines)


# -----------------------------------------------------------------------------------------------
# Callback function — processes each frame
# -----------------------------------------------------------------------------------------------


def app_callback(element, buffer, user_data):
    if buffer is None:
        hailo_logger.warning("Received None buffer.")
        return

    frame_idx = user_data.get_count()
    pad = element.get_static_pad("src")
    format, width, height = get_caps_from_pad(pad)

    frame = None
    if user_data.use_frame and format is not None and width is not None and height is not None:
        frame = get_numpy_from_buffer(buffer, format, width, height)

    roi = hailo.get_roi_from_buffer(buffer)
    detections = roi.get_objects_typed(hailo.HAILO_DETECTION)

    # Reset zone counts for this frame
    for zone in user_data.zones:
        zone.occupied_count = 0
        zone.vehicle_ids.clear()

    vehicle_count = 0
    for detection in detections:
        label = detection.get_label()
        confidence = detection.get_confidence()

        # Filter for vehicle classes only
        if label not in VEHICLE_LABELS:
            continue

        vehicle_count += 1
        bbox = detection.get_bbox()
        xmin = bbox.xmin()
        ymin = bbox.ymin()
        det_width = bbox.width()
        det_height = bbox.height()

        # Get track ID if available
        track_id = 0
        track = detection.get_objects_typed(hailo.HAILO_UNIQUE_ID)
        if len(track) == 1:
            track_id = track[0].get_id()

        # Check which zone contains this vehicle's center
        for zone in user_data.zones:
            if zone.contains_bbox_center(xmin, ymin, det_width, det_height):
                zone.occupied_count += 1
                zone.vehicle_ids.add(track_id)
                break  # A vehicle belongs to at most one zone

    user_data.total_vehicles = vehicle_count

    # Print occupancy summary periodically (every 30 frames)
    if frame_idx % 30 == 0:
        summary = user_data.get_occupancy_summary()
        print(f"\n--- Frame {frame_idx} | Vehicles: {vehicle_count} ---")
        print(summary)

    # Draw zone overlays on the frame if --use-frame is enabled
    if user_data.use_frame and frame is not None and width is not None and height is not None:
        _draw_zones_on_frame(frame, user_data.zones, width, height)

        # Draw occupancy summary text
        y_offset = 30
        cv2.putText(
            frame,
            f"Vehicles: {vehicle_count}",
            (10, y_offset),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2,
        )
        y_offset += 30
        for zone in user_data.zones:
            occupied = zone.occupied_count
            capacity = zone.capacity
            is_full = occupied >= capacity
            color = (0, 0, 255) if is_full else (0, 255, 0)  # Red if full, green if available
            text = f"{zone.name}: {occupied}/{capacity}"
            cv2.putText(
                frame,
                text,
                (10, y_offset),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                color,
                2,
            )
            y_offset += 25

        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        user_data.set_frame(frame)

    return


def _draw_zones_on_frame(frame, zones, frame_width, frame_height):
    """Draw zone polygons on the frame with color-coded occupancy status."""
    for zone in zones:
        occupied = zone.occupied_count
        capacity = zone.capacity
        is_full = occupied >= capacity

        # Scale polygon from normalized [0,1] to pixel coordinates
        pts = zone.polygon.copy()
        pts[:, 0] *= frame_width
        pts[:, 1] *= frame_height
        pts = pts.astype(np.int32)

        # Draw filled polygon with transparency
        overlay = frame.copy()
        color = (0, 0, 255) if is_full else (0, 255, 0)  # Red if full, green if available
        cv2.fillPoly(overlay, [pts], color)
        alpha = 0.15
        cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)

        # Draw polygon border
        border_color = (0, 0, 200) if is_full else (0, 200, 0)
        cv2.polylines(frame, [pts], isClosed=True, color=border_color, thickness=2)

        # Draw zone label at the centroid
        centroid_x = int(pts[:, 0].mean())
        centroid_y = int(pts[:, 1].mean())
        label_text = f"{zone.name}: {occupied}/{capacity}"
        cv2.putText(
            frame,
            label_text,
            (centroid_x - 40, centroid_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (255, 255, 255),
            2,
        )


# -----------------------------------------------------------------------------------------------
# Main entry point
# -----------------------------------------------------------------------------------------------


def main():
    hailo_logger.info("Starting Parking Lot Occupancy App.")

    # Pre-parse zones argument before full pipeline parser takes over
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--zones-json", default=None)
    pre_args, _ = pre_parser.parse_known_args()

    # Load zones
    if pre_args.zones_json is not None:
        hailo_logger.info("Loading zones from: %s", pre_args.zones_json)
        zones = load_zones_from_json(pre_args.zones_json)
    else:
        hailo_logger.info("No --zones-json provided, using default 2x2 grid zones.")
        zones = get_default_zones()

    hailo_logger.info("Configured %d parking zones.", len(zones))

    user_data = ParkingLotCallbackData(zones)
    app = GStreamerParkingLotApp(app_callback, user_data)
    app.run()


if __name__ == "__main__":
    main()
