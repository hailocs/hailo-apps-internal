# region imports
# Standard library imports
from datetime import datetime
import os
import csv
import threading
import json
import time
import uuid
os.environ["GST_PLUGIN_FEATURE_RANK"] = "vaapidecodebin:NONE"

# Third-party imports
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst
import numpy as np
from PIL import Image

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
# Maximum number of enrollable face snapshots to keep per track
MAX_ENROLLABLE_PER_TRACK = 5
# endregion


class SecurityCallbackClass(app_callback_class):
    """Callback state for room security monitor.

    Tracks recognized and unknown faces, manages alarm cooldowns,
    logs access events, and supports real-time face enrollment.
    """

    def __init__(self, alarm_cooldown=ALARM_COOLDOWN_SECONDS, log_file=ACCESS_LOG_FILE):
        super().__init__()
        self.seen_track_ids = set()  # Track IDs we've already logged
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

        # --- Real-time enrollment state ---
        # {track_id: {"embedding": np.array, "crop": np.array, "timestamp": float, "label": str}}
        self.enrollable_faces = {}
        self.enrollable_lock = threading.Lock()
        # Set by main() after pipeline creation
        self.db_handler = None
        self.train_images_dir = None
        self.samples_dir = None
        self.pipeline_ref = None  # reference to pipeline for processed_names tracking

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
        """Append an access event to the CSV log file."""
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
        print(f"  >> Type 'e' to enroll this face, or 'e <name>' to enroll with a name")
        print(f"{'='*60}\n")

    def store_enrollable_face(self, track_id, embedding, crop, label="Unknown"):
        """Store a face snapshot for potential enrollment.

        Called from vector_db_callback when processing faces.
        Keeps only the latest snapshot per track_id.
        """
        with self.enrollable_lock:
            self.enrollable_faces[track_id] = {
                "embedding": embedding.copy(),
                "crop": crop.copy(),
                "timestamp": time.time(),
                "label": label,
            }
            # Prune old entries (keep faces seen in last 60 seconds)
            cutoff = time.time() - 60
            stale = [tid for tid, data in self.enrollable_faces.items()
                     if data["timestamp"] < cutoff]
            for tid in stale:
                del self.enrollable_faces[tid]

    def get_enrollable_unknowns(self):
        """Return a list of unknown faces available for enrollment."""
        with self.enrollable_lock:
            return {tid: data for tid, data in self.enrollable_faces.items()
                    if data["label"] == "Unknown"}

    def get_enrollable_recognized(self):
        """Return a list of recognized faces available for adding samples."""
        with self.enrollable_lock:
            return {tid: data for tid, data in self.enrollable_faces.items()
                    if data["label"] != "Unknown"}

    def enroll_face(self, name, track_id=None):
        """Enroll a face into the database and save to train directory.

        Args:
            name: Person name to assign.
            track_id: Specific track_id to enroll. If None, uses the most recent unknown.

        Returns:
            True if enrollment succeeded, False otherwise.
        """
        if not self.db_handler or not self.train_images_dir or not self.samples_dir:
            print("ERROR: Enrollment not configured. Pipeline not fully initialized.")
            return False

        with self.enrollable_lock:
            if track_id is not None:
                face_data = self.enrollable_faces.get(track_id)
            else:
                # Get the most recent unknown face
                unknowns = {tid: d for tid, d in self.enrollable_faces.items()
                            if d["label"] == "Unknown"}
                if not unknowns:
                    print("No unknown faces available for enrollment.")
                    return False
                track_id = max(unknowns, key=lambda t: unknowns[t]["timestamp"])
                face_data = unknowns[track_id]

            if face_data is None:
                print(f"No face data found for track ID {track_id}.")
                return False

            embedding = face_data["embedding"]
            crop = face_data["crop"]

        # Save cropped face to train directory
        person_train_dir = os.path.join(self.train_images_dir, name)
        os.makedirs(person_train_dir, exist_ok=True)
        train_image_path = os.path.join(person_train_dir, f"{uuid.uuid4()}.jpeg")
        _save_image(crop, train_image_path)

        # Save to samples directory
        sample_image_path = os.path.join(self.samples_dir, f"{uuid.uuid4()}.jpeg")
        _save_image(crop, sample_image_path)

        # Check if person already exists in DB
        existing = self.db_handler.get_record_by_label(label=name)
        if existing:
            # Ensure samples_json is parsed (get_record_by_label returns raw string)
            if isinstance(existing.get("samples_json"), str):
                existing["samples_json"] = json.loads(existing["samples_json"])
            # Add as new sample to existing person
            self.db_handler.insert_new_sample(
                record=existing,
                embedding=embedding,
                sample=sample_image_path,
                timestamp=int(time.time()),
            )
            print(f"Added new sample to existing person '{name}' (Track ID: {track_id})")
        else:
            # Create new record
            person = self.db_handler.create_record(
                embedding=embedding,
                sample=sample_image_path,
                timestamp=int(time.time()),
                label=name,
            )
            # Track in pipeline's processed_names for consistency
            if self.pipeline_ref:
                self.pipeline_ref.processed_names.add((name, person['global_id']))
            print(f"New person '{name}' enrolled (Track ID: {track_id}, ID: {person['global_id']})")

        self.log_access_event(track_id, name, 1.0, 'enrolled')

        # Force re-classification so overlay updates immediately
        if self.pipeline_ref:
            self.pipeline_ref.force_reclassify(track_id)
        # Allow this track to be re-logged with the new name
        self.seen_track_ids.discard(track_id)

        # Remove from enrollable faces
        with self.enrollable_lock:
            self.enrollable_faces.pop(track_id, None)

        return True

    def add_sample_for_person(self, name, track_id=None):
        """Add another face sample for an already-recognized person.

        Args:
            name: Person name to add sample to.
            track_id: Specific track_id to use. If None, uses the most recent face for that name.

        Returns:
            True if sample was added, False otherwise.
        """
        if not self.db_handler:
            print("ERROR: Enrollment not configured.")
            return False

        existing = self.db_handler.get_record_by_label(label=name)
        if not existing:
            print(f"Person '{name}' not found in database. Use 'e {name}' to enroll first.")
            return False

        with self.enrollable_lock:
            if track_id is not None:
                face_data = self.enrollable_faces.get(track_id)
            else:
                # Find the most recent face matching this name
                matching = {tid: d for tid, d in self.enrollable_faces.items()
                            if d["label"] == name}
                if not matching:
                    # Fall back to any face (user might want to add unknown as sample)
                    if not self.enrollable_faces:
                        print(f"No faces currently visible to add as sample for '{name}'.")
                        return False
                    track_id = max(self.enrollable_faces,
                                   key=lambda t: self.enrollable_faces[t]["timestamp"])
                    face_data = self.enrollable_faces[track_id]
                else:
                    track_id = max(matching, key=lambda t: matching[t]["timestamp"])
                    face_data = matching[track_id]

            if face_data is None:
                print(f"No face data for track ID {track_id}.")
                return False

            embedding = face_data["embedding"]
            crop = face_data["crop"]

        # Save to train directory
        person_train_dir = os.path.join(self.train_images_dir, name)
        os.makedirs(person_train_dir, exist_ok=True)
        train_image_path = os.path.join(person_train_dir, f"{uuid.uuid4()}.jpeg")
        _save_image(crop, train_image_path)

        # Save to samples directory and add to DB
        sample_image_path = os.path.join(self.samples_dir, f"{uuid.uuid4()}.jpeg")
        _save_image(crop, sample_image_path)

        # Ensure samples_json is parsed (get_record_by_label returns raw string)
        if isinstance(existing.get("samples_json"), str):
            existing["samples_json"] = json.loads(existing["samples_json"])
        self.db_handler.insert_new_sample(
            record=existing,
            embedding=embedding,
            sample=sample_image_path,
            timestamp=int(time.time()),
        )
        num_samples = self.db_handler.get_records_num_samples(existing['global_id'])
        print(f"Added sample for '{name}' (now has {num_samples} samples)")
        return True


def _save_image(frame, path):
    """Save a numpy frame as JPEG."""
    image = Image.fromarray(frame)
    image.save(path, format="JPEG", quality=85)


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

                    # Only process each track ID once to avoid duplicate prints
                    if track_id in user_data.seen_track_ids:
                        continue
                    user_data.seen_track_ids.add(track_id)

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


def enrollment_listener(user_data):
    """Background thread: listen for enrollment commands from terminal.

    Commands:
        e [name]       Enroll the most recent unknown face with the given name.
                       If no name given, prompts for one.
        e <tid> <name> Enroll a specific track ID with the given name.
        s <name>       Add another sample for an existing person.
        l              List currently visible faces available for enrollment.
        db             List all persons in the database.
        h              Show help.
        q              Quit the application.
    """
    print("\n" + "=" * 60)
    print("  REAL-TIME ENROLLMENT ACTIVE")
    print("  Commands (type in terminal):")
    print("    e <name>         Enroll latest unknown face as <name>")
    print("    e <tid> <name>   Enroll specific track ID as <name>")
    print("    s <name>         Add sample for existing person <name>")
    print("    l                List visible faces")
    print("    db               List all persons in database")
    print("    h                Show this help")
    print("    q                Quit")
    print("=" * 60 + "\n")

    while user_data.running:
        try:
            cmd = input(">> ").strip()
        except EOFError:
            break
        except KeyboardInterrupt:
            break

        if not cmd:
            continue

        parts = cmd.split(maxsplit=2)
        action = parts[0].lower()

        if action in ('q', 'quit', 'exit'):
            print("Shutting down...")
            user_data.running = False
            break

        elif action in ('h', 'help'):
            print("Commands:")
            print("  e <name>         Enroll latest unknown face as <name>")
            print("  e <tid> <name>   Enroll specific track ID as <name>")
            print("  s <name>         Add sample for existing person <name>")
            print("  l                List visible faces")
            print("  db               List all persons in database")
            print("  q                Quit")

        elif action in ('e', 'enroll'):
            if len(parts) == 1:
                # No name given, prompt
                unknowns = user_data.get_enrollable_unknowns()
                if not unknowns:
                    print("No unknown faces visible right now. Wait for an unknown face to appear.")
                    continue
                print(f"Unknown faces available: {list(unknowns.keys())}")
                try:
                    name = input("Enter name for enrollment: ").strip()
                except (EOFError, KeyboardInterrupt):
                    continue
                if not name:
                    print("Cancelled.")
                    continue
                user_data.enroll_face(name)
            elif len(parts) == 2:
                # 'e <name>' — enroll latest unknown with this name
                name = parts[1]
                # Check if it's a track ID (numeric)
                try:
                    tid = int(name)
                    # It's a track ID, need a name too
                    print(f"Track ID {tid} selected. Enter name:")
                    try:
                        name = input("Name: ").strip()
                    except (EOFError, KeyboardInterrupt):
                        continue
                    if not name:
                        print("Cancelled.")
                        continue
                    user_data.enroll_face(name, track_id=tid)
                except ValueError:
                    # It's a name, use latest unknown
                    user_data.enroll_face(name)
            elif len(parts) >= 3:
                # 'e <tid> <name>'
                try:
                    tid = int(parts[1])
                    name = parts[2]
                    user_data.enroll_face(name, track_id=tid)
                except ValueError:
                    # Treat whole thing as name
                    name = " ".join(parts[1:])
                    user_data.enroll_face(name)

        elif action in ('s', 'sample'):
            if len(parts) < 2:
                print("Usage: s <name>  — Add another sample for an existing person.")
                recognized = user_data.get_enrollable_recognized()
                if recognized:
                    names = set(d["label"] for d in recognized.values())
                    print(f"Recognized faces visible: {names}")
                continue
            name = " ".join(parts[1:])
            user_data.add_sample_for_person(name)

        elif action in ('l', 'list'):
            unknowns = user_data.get_enrollable_unknowns()
            recognized = user_data.get_enrollable_recognized()
            if unknowns:
                print("Unknown faces (enrollable):")
                for tid, data in unknowns.items():
                    age = time.time() - data["timestamp"]
                    print(f"  Track ID {tid} — seen {age:.0f}s ago")
            else:
                print("No unknown faces visible.")
            if recognized:
                print("Recognized faces (can add samples):")
                for tid, data in recognized.items():
                    age = time.time() - data["timestamp"]
                    print(f"  Track ID {tid} — {data['label']} — seen {age:.0f}s ago")
            else:
                print("No recognized faces visible.")

        elif action == 'db':
            if not user_data.db_handler:
                print("Database not initialized.")
                continue
            records = user_data.db_handler.get_all_records()
            if not records:
                print("Database is empty.")
            else:
                print(f"Database has {len(records)} person(s):")
                for rec in records:
                    num_samples = len(rec.get("samples_json", []))
                    print(f"  {rec['label']} — {num_samples} sample(s) — ID: {rec['global_id'][:8]}...")

        else:
            print(f"Unknown command: '{action}'. Type 'h' for help.")


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
        # Wire up enrollment support
        user_data.db_handler = pipeline.db_handler
        user_data.train_images_dir = str(pipeline.train_images_dir)
        user_data.samples_dir = str(pipeline.samples_dir)
        user_data.pipeline_ref = pipeline

        if pipeline.options_menu.ui:
            # Launch graphical enrollment panel
            from community.apps.pipeline_apps.room_security_monitor.enrollment_ui import EnrollmentUI
            ui = EnrollmentUI(user_data)
            ui.start()
            print("Starting security monitoring with enrollment UI.")
        else:
            # Terminal-based enrollment
            enrollment_thread = threading.Thread(
                target=enrollment_listener, args=(user_data,), daemon=True
            )
            enrollment_thread.start()
            print("Starting security monitoring mode.")
            print("Type 'h' for enrollment commands.\n")

        print("Authorized faces will be logged. Unknown faces trigger an alarm.")
        pipeline.run()


if __name__ == "__main__":
    main()
