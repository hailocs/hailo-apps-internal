# region imports
# Standard library imports
import os
os.environ["GST_PLUGIN_FEATURE_RANK"] = "vaapidecodebin:NONE"

# Third-party imports
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst

# Local application-specific imports
import hailo
from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.gstreamer.gstreamer_app import app_callback_class
from community.apps.pipeline_apps.retail_shelf_analyzer.retail_shelf_analyzer_pipeline import (
    GStreamerRetailShelfAnalyzerApp,
)

hailo_logger = get_logger(__name__)
# endregion imports

# Labels to exclude from product counts (e.g., people walking past the shelf)
EXCLUDED_LABELS = {"person", "cat", "dog", "bird", "horse", "sheep", "cow",
                   "elephant", "bear", "zebra", "giraffe"}


class RetailShelfCallbackData(app_callback_class):
    """Callback data class that maintains state between frames for retail shelf analysis."""

    def __init__(self):
        super().__init__()
        # Per-zone product counts (updated each frame)
        self.zone_counts = {}
        # Running total of empty zone alerts
        self.empty_zone_alerts = 0


def assign_zone(detection, num_zones):
    """
    Assign a detection to a horizontal shelf zone based on its vertical position.

    Zones are numbered top-to-bottom (0 = top shelf, num_zones-1 = bottom shelf).
    The detection's vertical center (ymin + height/2) determines the zone.

    Args:
        detection: A hailo detection object with get_bbox()
        num_zones: Number of horizontal zones to divide the frame into

    Returns:
        int: Zone index (0-based, top to bottom)
    """
    bbox = detection.get_bbox()
    y_center = bbox.ymin() + bbox.height() / 2.0
    zone = int(y_center * num_zones)
    # Clamp to valid range
    return min(zone, num_zones - 1)


def app_callback(element, buffer, user_data):
    """
    Callback function invoked for each frame after tiled detection.

    Processes detections to:
    1. Filter by confidence threshold
    2. Count products per shelf zone
    3. Flag zones with too few products as potentially empty
    4. Print per-frame summary with zone counts and alerts
    """
    frame_count = user_data.get_count()

    if buffer is None:
        hailo_logger.warning("Received None buffer at frame=%s", frame_count)
        return

    # Get app reference to access retail-specific settings
    # These are set on user_data before the pipeline starts
    num_zones = getattr(user_data, 'num_zones', 3)
    empty_threshold = getattr(user_data, 'empty_threshold', 2)
    confidence_threshold = getattr(user_data, 'confidence_threshold', 0.4)

    # Initialize zone counts for this frame
    zone_counts = {i: 0 for i in range(num_zones)}
    total_detections = 0

    roi = hailo.get_roi_from_buffer(buffer)
    detections = roi.get_objects_typed(hailo.HAILO_DETECTION)

    for detection in detections:
        confidence = detection.get_confidence()
        if confidence < confidence_threshold:
            continue

        label = detection.get_label()
        if label in EXCLUDED_LABELS:
            continue

        zone = assign_zone(detection, num_zones)
        zone_counts[zone] += 1
        total_detections += 1

    # Store zone counts in user_data for persistence
    user_data.zone_counts = zone_counts

    # Build output string
    output_lines = [f"Frame {frame_count}: {total_detections} products detected"]

    empty_zones = []
    for zone_id in range(num_zones):
        count = zone_counts[zone_id]
        zone_label = f"Zone {zone_id} (shelf {zone_id + 1})"
        status = ""
        if count < empty_threshold:
            status = " ** EMPTY SHELF ALERT **"
            empty_zones.append(zone_id)
        output_lines.append(f"  {zone_label}: {count} products{status}")

    if empty_zones:
        user_data.empty_zone_alerts += 1
        output_lines.append(f"  -> {len(empty_zones)} zone(s) below threshold "
                            f"(total alerts: {user_data.empty_zone_alerts})")

    # Print every 30 frames to avoid flooding the console
    if frame_count % 30 == 0 or empty_zones:
        print("\n".join(output_lines))

    return


def main():
    """Main function for the retail shelf analyzer."""
    hailo_logger.info("Starting Retail Shelf Analyzer.")
    user_data = RetailShelfCallbackData()
    app = GStreamerRetailShelfAnalyzerApp(app_callback, user_data)

    # Pass retail-specific config to user_data so the callback can access it
    user_data.num_zones = app.num_zones
    user_data.empty_threshold = app.empty_threshold
    user_data.confidence_threshold = app.confidence_threshold

    app.run()


if __name__ == "__main__":
    main()
