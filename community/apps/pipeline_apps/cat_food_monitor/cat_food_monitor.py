# region imports
# Standard library imports
import csv
import os
from datetime import datetime
os.environ["GST_PLUGIN_FEATURE_RANK"] = "vaapidecodebin:NONE"

# Third-party imports
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst

# Local application-specific imports
import hailo
from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.gstreamer.gstreamer_app import app_callback_class
from community.apps.pipeline_apps.cat_food_monitor.cat_food_monitor_pipeline import (
    GStreamerCatFoodMonitorApp,
)

hailo_logger = get_logger(__name__)
# endregion imports

# region Constants
FEEDING_LOG_FILENAME = "feeding_log.csv"
# Minimum seconds between log entries for the same cat
FEEDING_LOG_COOLDOWN_SECONDS = 60
# endregion


class CatFoodMonitorCallbackClass(app_callback_class):
    """Callback state for the cat food monitor application.

    Tracks per-cat feeding sessions and writes a CSV log with timestamps,
    cat identity, duration, and recognition confidence.
    """

    def __init__(self):
        super().__init__()
        self.latest_track_id = -1
        # Track active feeding sessions: {cat_name: {"start": datetime, "track_id": int}}
        self.active_sessions = {}
        # Last log time per cat to avoid spamming
        self.last_log_time = {}
        # Feeding log file path (next to the script)
        self.log_file = os.path.join(os.path.dirname(__file__), FEEDING_LOG_FILENAME)
        self._init_log_file()

    def _init_log_file(self):
        """Create the CSV log file with headers if it does not exist."""
        if not os.path.exists(self.log_file):
            with open(self.log_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    "timestamp", "cat_name", "event", "track_id",
                    "confidence", "duration_seconds",
                ])

    def log_feeding_event(self, cat_name, event, track_id, confidence, duration=None):
        """Append a feeding event to the CSV log."""
        now = datetime.now()
        # Apply cooldown per cat
        last = self.last_log_time.get(cat_name)
        if last and (now - last).total_seconds() < FEEDING_LOG_COOLDOWN_SECONDS:
            return
        self.last_log_time[cat_name] = now
        with open(self.log_file, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                now.strftime("%Y-%m-%d %H:%M:%S"),
                cat_name,
                event,
                track_id,
                f"{confidence:.2f}" if confidence else "",
                f"{duration:.1f}" if duration else "",
            ])

    def start_session(self, cat_name, track_id, confidence):
        """Record the start of a feeding session for a cat."""
        if cat_name not in self.active_sessions:
            self.active_sessions[cat_name] = {
                "start": datetime.now(),
                "track_id": track_id,
            }
            self.log_feeding_event(cat_name, "arrived", track_id, confidence)

    def end_session(self, cat_name):
        """End a feeding session and log the duration."""
        session = self.active_sessions.pop(cat_name, None)
        if session:
            duration = (datetime.now() - session["start"]).total_seconds()
            self.log_feeding_event(
                cat_name, "departed", session["track_id"],
                confidence=None, duration=duration,
            )


def app_callback(element, buffer, user_data):
    """Process each frame: identify cats and log feeding activity."""
    if buffer is None:
        hailo_logger.warning("Received None buffer.")
        return
    roi = hailo.get_roi_from_buffer(buffer)
    detections = roi.get_objects_typed(hailo.HAILO_DETECTION)

    recognized_cats_this_frame = set()

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
                    cat_name = classification.get_label()
                    cat_confidence = classification.get_confidence()

                    if cat_name == 'Unknown':
                        string_to_print = (
                            f'[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}]: '
                            f'Unknown cat detected (Track ID: {track_id}, '
                            f'Detection confidence: {detection_confidence:.2f})'
                        )
                    else:
                        string_to_print = (
                            f'[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}]: '
                            f'Cat recognized: {cat_name} '
                            f'(Track ID: {track_id}, '
                            f'Confidence: {cat_confidence:.2f})'
                        )
                        recognized_cats_this_frame.add(cat_name)
                        # Start or continue a feeding session
                        user_data.start_session(cat_name, track_id, cat_confidence)

                    if track_id > user_data.latest_track_id:
                        user_data.latest_track_id = track_id
                        print(string_to_print)

    # Check for cats that left the frame (session ended)
    ended_cats = [
        name for name in list(user_data.active_sessions.keys())
        if name not in recognized_cats_this_frame
    ]
    # Only end session if cat has been absent for multiple consecutive frames
    # (simple approach: end immediately; for production, add a grace period)
    for cat_name in ended_cats:
        session = user_data.active_sessions.get(cat_name)
        if session:
            elapsed = (datetime.now() - session["start"]).total_seconds()
            # Only end if the session has been active for at least 5 seconds
            # to avoid flickering
            if elapsed > 5:
                user_data.end_session(cat_name)

    return


def main():
    hailo_logger.info("Starting Cat Food Monitor App.")
    user_data = CatFoodMonitorCallbackClass()
    pipeline = GStreamerCatFoodMonitorApp(app_callback, user_data)
    if pipeline.options_menu.mode == 'delete':
        pipeline.db_handler.clear_table()
        print("Cat database cleared.")
        exit(0)
    elif pipeline.options_menu.mode == 'train':
        pipeline.run()
        exit(0)
    else:  # 'run' mode
        pipeline.run()


if __name__ == "__main__":
    main()
