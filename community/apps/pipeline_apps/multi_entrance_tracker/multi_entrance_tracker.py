# region imports
# Standard library imports
import os
import time
os.environ["GST_PLUGIN_FEATURE_RANK"] = "vaapidecodebin:NONE"

# Third-party imports
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst

# Local application-specific imports
import hailo
from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.gstreamer.gstreamer_app import app_callback_class
from community.apps.pipeline_apps.multi_entrance_tracker.multi_entrance_tracker_pipeline import MultiEntranceTrackerApp

hailo_logger = get_logger(__name__)
# endregion imports


class MultiEntranceCallbackClass(app_callback_class):
    """Callback state for multi-entrance tracking.

    Maintains cross-camera identity match counts and per-entrance statistics.
    """

    def __init__(self):
        super().__init__()
        self.cross_camera_matches = 0
        self.per_entrance_counts = {}
        self.last_log_time = time.time()
        self.log_interval = 5.0  # Print summary every 5 seconds


def app_callback(element, buffer, user_data):
    """Unified callback invoked for every frame across all entrance cameras.

    Extracts face detections, prints cross-camera identity matches,
    and periodically logs per-entrance statistics.
    """
    if buffer is None:
        hailo_logger.warning("Received None buffer.")
        return

    roi = hailo.get_roi_from_buffer(buffer)
    stream_id = roi.get_stream_id()
    detections = roi.get_objects_typed(hailo.HAILO_DETECTION)

    for detection in detections:
        ids = detection.get_objects_typed(hailo.HAILO_UNIQUE_ID)
        if not ids:
            continue
        track_id = ids[0].get_id()

        classifications = detection.get_objects_typed(hailo.HAILO_CLASSIFICATION)
        for classification in classifications:
            label = classification.get_label()
            confidence = classification.get_confidence()
            if confidence > 0:
                # This is a cross-camera re-identification match
                user_data.cross_camera_matches += 1
                hailo_logger.info(
                    "Cross-camera match: stream=%s track=%d label=%s confidence=%.2f",
                    stream_id, track_id, label, confidence
                )

        # Track per-entrance counts
        entrance = stream_id.replace("'", "")
        if entrance not in user_data.per_entrance_counts:
            user_data.per_entrance_counts[entrance] = set()
        user_data.per_entrance_counts[entrance].add(track_id)

    # Periodically log summary
    current_time = time.time()
    if current_time - user_data.last_log_time > user_data.log_interval:
        user_data.last_log_time = current_time
        summary_parts = []
        for entrance, tracks in user_data.per_entrance_counts.items():
            summary_parts.append(f"{entrance}: {len(tracks)} unique faces")
        if summary_parts:
            hailo_logger.info(
                "Summary | %s | Cross-camera matches: %d",
                " | ".join(summary_parts),
                user_data.cross_camera_matches
            )


def main():
    hailo_logger.info("Starting Multi-Entrance Tracker App.")
    user_data = MultiEntranceCallbackClass()
    app = MultiEntranceTrackerApp(app_callback, user_data)
    app.run()


if __name__ == "__main__":
    main()
