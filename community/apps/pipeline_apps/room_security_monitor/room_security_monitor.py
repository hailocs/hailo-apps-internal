# region imports
# Standard library imports
import datetime
from datetime import datetime
import os
import csv
import threading
os.environ["GST_PLUGIN_FEATURE_RANK"] = "vaapidecodebin:NONE"

# Third-party imports
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst

# Local application-specific imports
import hailo
from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.gstreamer.gstreamer_app import app_callback_class
from community.apps.pipeline_apps.room_security_monitor.room_security_monitor_pipeline import GStreamerRoomSecurityMonitorApp

hailo_logger = get_logger(__name__)
# endregion imports

# region Constants
# Alarm cooldown in seconds to avoid repeated alarms for the same unknown person
ALARM_COOLDOWN_SECONDS = 30
ACCESS_LOG_FILE = "access_log.csv"
# endregion


class SecurityCallbackClass(app_callback_class):
    """Callback state for room security monitor.

    Tracks recognized and unknown faces, manages alarm cooldowns,
    and logs access events.
    """

    def __init__(self, alarm_cooldown=ALARM_COOLDOWN_SECONDS, log_file=ACCESS_LOG_FILE):
        super().__init__()
        self.latest_track_id = -1
        self.alarm_cooldown = alarm_cooldown
        self.log_file = log_file

        # Track alarm state per track_id to avoid repeated alarms
        self.alarm_timestamps = {}  # track_id -> last alarm datetime
        self.lock = threading.Lock()

        # Initialize access log file with header if it doesn't exist
        if not os.path.exists(self.log_file):
            with open(self.log_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['timestamp', 'track_id', 'name', 'confidence', 'event_type'])

    def should_trigger_alarm(self, track_id):
        """Check whether an alarm should be triggered for this track_id.

        Returns True if no alarm has been triggered for this track within
        the cooldown period.
        """
        now = datetime.now()
        with self.lock:
            last_alarm = self.alarm_timestamps.get(track_id)
            if last_alarm is None or (now - last_alarm).total_seconds() > self.alarm_cooldown:
                self.alarm_timestamps[track_id] = now
                return True
            return False

    def log_access_event(self, track_id, name, confidence, event_type):
        """Append an access event to the CSV log file.

        Args:
            track_id: The tracker-assigned face ID.
            name: Recognized person name or 'Unknown'.
            confidence: Recognition confidence score.
            event_type: One of 'authorized', 'unknown_alarm', or 'recognized'.
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.lock:
            with open(self.log_file, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([timestamp, track_id, name, f"{confidence:.2f}", event_type])

    def trigger_alarm(self, track_id):
        """Trigger an alarm for an unknown face.

        Override this method to integrate with external alarm systems
        (e.g., GPIO buzzer, HTTP webhook, MQTT message).
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n{'='*60}")
        print(f"  ALARM: Unknown person detected!")
        print(f"  Track ID: {track_id}")
        print(f"  Time: {timestamp}")
        print(f"{'='*60}\n")


def app_callback(element, buffer, user_data):
    """Process each frame's face recognition results.

    For each detected face:
    - If recognized as authorized: log the access event.
    - If unknown: trigger alarm (with cooldown) and log.
    """
    if buffer is None:
        hailo_logger.warning("Received None buffer.")
        return

    roi = hailo.get_roi_from_buffer(buffer)
    detections = roi.get_objects_typed(hailo.HAILO_DETECTION)

    for detection in detections:
        label = detection.get_label()
        detection_confidence = detection.get_confidence()

        if label == "face":
            track_id = 0
            track = detection.get_objects_typed(hailo.HAILO_UNIQUE_ID)
            if len(track) > 0:
                track_id = track[0].get_id()

            classifications = detection.get_objects_typed(hailo.HAILO_CLASSIFICATION)
            if len(classifications) > 0:
                for classification in classifications:
                    person_name = classification.get_label()
                    person_confidence = classification.get_confidence()

                    # Only process new track IDs to avoid duplicate prints
                    if track_id <= user_data.latest_track_id:
                        continue
                    user_data.latest_track_id = track_id

                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    if person_name == 'Unknown':
                        # Unknown person -- trigger alarm with cooldown
                        if user_data.should_trigger_alarm(track_id):
                            user_data.trigger_alarm(track_id)
                            user_data.log_access_event(track_id, 'Unknown', person_confidence, 'unknown_alarm')
                        print(f"[{timestamp}] UNKNOWN face detected (Track ID: {track_id}, Confidence: {detection_confidence:.1f})")
                    else:
                        # Authorized person recognized
                        user_data.log_access_event(track_id, person_name, person_confidence, 'authorized')
                        print(f"[{timestamp}] Authorized: {person_name} (Track ID: {track_id}, Confidence: {person_confidence:.1f})")
    return


def main():
    hailo_logger.info("Starting Room Security Monitor App.")
    user_data = SecurityCallbackClass()
    pipeline = GStreamerRoomSecurityMonitorApp(app_callback, user_data)

    if pipeline.options_menu.mode == 'delete':
        pipeline.db_handler.clear_table()
        print("Database cleared.")
        exit(0)
    elif pipeline.options_menu.mode == 'train':
        print("Entering training mode -- enrolling authorized personnel.")
        pipeline.run()
        exit(0)
    else:  # 'run' mode
        print("Starting security monitoring mode.")
        print("Authorized faces will be logged. Unknown faces trigger an alarm.")
        pipeline.run()


if __name__ == "__main__":
    main()
