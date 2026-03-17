# region imports
# Standard library imports
import os
import time
from collections import defaultdict

os.environ["GST_PLUGIN_FEATURE_RANK"] = "vaapidecodebin:NONE"

# Third-party imports
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst

# Local application-specific imports
import hailo
from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.gstreamer.gstreamer_app import app_callback_class
from community.apps.pipeline_apps.multi_camera_store_monitor.multi_camera_store_monitor_pipeline import (
    GStreamerStoreMonitorApp,
    CAMERA_NAMES,
)

hailo_logger = get_logger(__name__)
# endregion imports

# COCO class label for person
PERSON_LABEL = "person"

# Zone alert thresholds: if person count exceeds this for a camera, log a warning
ZONE_ALERT_THRESHOLDS = {
    "src_0": 10,  # Entrance
    "src_1": 5,   # Checkout
    "src_2": 3,   # Stockroom
}

# How often (in seconds) to print summary statistics
SUMMARY_INTERVAL = 10.0


class StoreMonitorCallback(app_callback_class):
    """Callback state for multi-camera store monitoring.

    Tracks per-camera person counts, zone alerts, and summary statistics.
    """

    def __init__(self, person_threshold=0.5):
        super().__init__()
        self.person_threshold = person_threshold
        # Per-camera current frame person count
        self.current_counts = defaultdict(int)
        # Per-camera maximum person count seen
        self.max_counts = defaultdict(int)
        # Per-camera cumulative person count (for averaging)
        self.total_counts = defaultdict(int)
        self.frame_counts_per_camera = defaultdict(int)
        # Zone alert tracking: avoid spamming alerts
        self.alert_active = defaultdict(bool)
        # Summary timing
        self.last_summary_time = time.time()


def app_callback(element, buffer, user_data):
    """Unified callback for all camera streams.

    Processes detections from each camera, filters for persons above
    the confidence threshold, tracks per-camera counts, and triggers
    zone alerts when thresholds are exceeded.
    """
    if buffer is None:
        hailo_logger.warning("Received None buffer.")
        return

    roi = hailo.get_roi_from_buffer(buffer)
    stream_id = roi.get_stream_id()
    camera_name = CAMERA_NAMES.get(stream_id, stream_id)

    detections = roi.get_objects_typed(hailo.HAILO_DETECTION)

    # Count persons in this frame for this camera
    person_count = 0
    for detection in detections:
        label = detection.get_label()
        confidence = detection.get_confidence()

        if label == PERSON_LABEL and confidence >= user_data.person_threshold:
            person_count += 1

            # Log tracked person IDs if available
            ids = detection.get_objects_typed(hailo.HAILO_UNIQUE_ID)
            if ids:
                track_id = ids[0].get_id()
                hailo_logger.debug(
                    "[%s] Person detected: track_id=%d, confidence=%.2f",
                    camera_name, track_id, confidence,
                )

    # Update per-camera statistics
    user_data.current_counts[stream_id] = person_count
    user_data.frame_counts_per_camera[stream_id] += 1
    user_data.total_counts[stream_id] += person_count

    if person_count > user_data.max_counts[stream_id]:
        user_data.max_counts[stream_id] = person_count

    # Zone alert logic
    threshold = ZONE_ALERT_THRESHOLDS.get(stream_id, 10)
    if person_count >= threshold:
        if not user_data.alert_active[stream_id]:
            hailo_logger.warning(
                "ZONE ALERT [%s]: %d persons detected (threshold: %d)",
                camera_name, person_count, threshold,
            )
            user_data.alert_active[stream_id] = True
    else:
        if user_data.alert_active[stream_id]:
            hailo_logger.info(
                "Zone alert cleared [%s]: %d persons (below threshold %d)",
                camera_name, person_count, threshold,
            )
            user_data.alert_active[stream_id] = False

    # Periodic summary
    now = time.time()
    if now - user_data.last_summary_time >= SUMMARY_INTERVAL:
        user_data.last_summary_time = now
        print("\n--- Store Monitor Summary ---")
        for sid in sorted(user_data.current_counts.keys()):
            cam = CAMERA_NAMES.get(sid, sid)
            current = user_data.current_counts[sid]
            maximum = user_data.max_counts[sid]
            frames = user_data.frame_counts_per_camera[sid]
            avg = user_data.total_counts[sid] / frames if frames > 0 else 0.0
            alert_status = " [ALERT]" if user_data.alert_active[sid] else ""
            print(
                f"  {cam:12s}: current={current:3d}, max={maximum:3d}, avg={avg:.1f}{alert_status}"
            )
        print("-----------------------------\n")

    return


def main():
    hailo_logger.info("Starting Multi-Camera Store Monitor.")
    user_data = StoreMonitorCallback(person_threshold=0.5)
    app = GStreamerStoreMonitorApp(app_callback, user_data)
    # Override person_threshold from CLI if provided
    if hasattr(app, 'person_threshold'):
        user_data.person_threshold = app.person_threshold
    app.run()


if __name__ == "__main__":
    main()
