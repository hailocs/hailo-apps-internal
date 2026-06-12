# region imports
# Standard library imports
import os
import time
import threading

os.environ["GST_PLUGIN_FEATURE_RANK"] = "vaapidecodebin:NONE"

# Third-party imports
import gi

gi.require_version("Gst", "1.0")
import cv2
import numpy as np

# Local application-specific imports
import hailo
from gi.repository import Gst

from community.apps.pipeline_apps.baby_sleep_monitor.baby_sleep_monitor_pipeline import (
    GStreamerBabySleepMonitorApp,
)
from hailo_apps.python.core.common.buffer_utils import (
    get_caps_from_pad,
    get_numpy_from_buffer,
)

from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.gstreamer.gstreamer_app import app_callback_class

hailo_logger = get_logger(__name__)
# endregion imports


# COCO keypoint indices
KEYPOINTS = {
    "nose": 0,
    "left_eye": 1,
    "right_eye": 2,
    "left_ear": 3,
    "right_ear": 4,
    "left_shoulder": 5,
    "right_shoulder": 6,
    "left_elbow": 7,
    "right_elbow": 8,
    "left_wrist": 9,
    "right_wrist": 10,
    "left_hip": 11,
    "right_hip": 12,
    "left_knee": 13,
    "right_knee": 14,
    "left_ankle": 15,
    "right_ankle": 16,
}

# Sleep position status levels
STATUS_SAFE = "SAFE"
STATUS_WARNING = "WARNING"
STATUS_DANGER = "DANGER"

# Colors for status display (BGR)
STATUS_COLORS = {
    STATUS_SAFE: (0, 200, 0),       # Green
    STATUS_WARNING: (0, 200, 255),   # Orange/Yellow
    STATUS_DANGER: (0, 0, 255),      # Red
}


def get_keypoint_pixel_coords(point, bbox, frame_width, frame_height):
    """Convert a landmark point (normalized to detection bbox) to pixel coordinates."""
    x = int((point.x() * bbox.width() + bbox.xmin()) * frame_width)
    y = int((point.y() * bbox.height() + bbox.ymin()) * frame_height)
    return x, y


def analyze_sleep_position(landmarks, bbox, frame_width, frame_height):
    """
    Analyze body keypoints to determine if the baby is in a safe sleeping position.

    Safe position: Baby lying on back (supine) - nose and both eyes visible,
                   shoulders roughly at same height (horizontal).
    Warning:       Partial side position or ambiguous pose.
    Danger:        Face-down (prone) position - nose not visible or below shoulders,
                   or body appears significantly twisted.

    Returns:
        tuple: (status, reason) where status is STATUS_SAFE/WARNING/DANGER
    """
    points = landmarks[0].get_points()

    # Extract key body points
    def kp(name):
        idx = KEYPOINTS[name]
        pt = points[idx]
        return get_keypoint_pixel_coords(pt, bbox, frame_width, frame_height)

    nose_x, nose_y = kp("nose")
    left_eye_x, left_eye_y = kp("left_eye")
    right_eye_x, right_eye_y = kp("right_eye")
    left_shoulder_x, left_shoulder_y = kp("left_shoulder")
    right_shoulder_x, right_shoulder_y = kp("right_shoulder")
    left_hip_x, left_hip_y = kp("left_hip")
    right_hip_x, right_hip_y = kp("right_hip")

    # Check if keypoints have valid (non-zero) confidence by checking if they
    # are not at the origin. A point at (0, 0) likely means it was not detected.
    nose_visible = not (nose_x == 0 and nose_y == 0)
    left_eye_visible = not (left_eye_x == 0 and left_eye_y == 0)
    right_eye_visible = not (right_eye_x == 0 and right_eye_y == 0)
    shoulders_visible = not (
        (left_shoulder_x == 0 and left_shoulder_y == 0)
        or (right_shoulder_x == 0 and right_shoulder_y == 0)
    )

    # DANGER: Face-down detection
    # If the nose is not visible but shoulders are, the baby may be face-down
    if not nose_visible and shoulders_visible:
        return STATUS_DANGER, "Face-down: nose not visible"

    # If neither eyes are visible, the baby may be face-down
    if not left_eye_visible and not right_eye_visible:
        return STATUS_DANGER, "Face-down: eyes not visible"

    if shoulders_visible:
        # Check shoulder alignment - if shoulders are roughly horizontal,
        # baby is likely on their back (safe) or stomach (check with nose)
        shoulder_height_diff = abs(left_shoulder_y - right_shoulder_y)
        shoulder_width = abs(left_shoulder_x - right_shoulder_x)

        # WARNING: Twisted body detection
        # If the shoulder height difference is large relative to shoulder width,
        # the body may be twisted
        if shoulder_width > 0:
            twist_ratio = shoulder_height_diff / shoulder_width
            if twist_ratio > 1.0:
                return STATUS_DANGER, "Twisted body position"
            elif twist_ratio > 0.5:
                return STATUS_WARNING, "Partially turned to side"

        # Check if nose is below both shoulders (potential face-down)
        if nose_visible:
            avg_shoulder_y = (left_shoulder_y + right_shoulder_y) / 2
            if nose_y > avg_shoulder_y + 30:  # Nose significantly below shoulders
                return STATUS_WARNING, "Head position low"

    # If only one eye is visible, baby may be on their side
    if (left_eye_visible and not right_eye_visible) or (
        right_eye_visible and not left_eye_visible
    ):
        return STATUS_WARNING, "Side position: one eye hidden"

    # If we get here with nose and both eyes visible, position is likely safe
    if nose_visible and left_eye_visible and right_eye_visible:
        return STATUS_SAFE, "Back position (supine)"

    return STATUS_WARNING, "Ambiguous position"


# -----------------------------------------------------------------------------------------------
# User-defined class to be used in the callback function
# -----------------------------------------------------------------------------------------------
class BabySleepCallbackData(app_callback_class):
    def __init__(self):
        super().__init__()
        self.current_status = STATUS_SAFE
        self.current_reason = "No detection"
        self.danger_start_time = None
        self.alert_active = False
        # Time in seconds before triggering audio alert
        self.danger_threshold_seconds = 3.0
        self._alert_thread = None

    def update_status(self, status, reason):
        """Update the current sleep position status and manage alerts."""
        self.current_status = status
        self.current_reason = reason

        if status == STATUS_DANGER:
            if self.danger_start_time is None:
                self.danger_start_time = time.time()
            elif (
                time.time() - self.danger_start_time > self.danger_threshold_seconds
                and not self.alert_active
            ):
                self.alert_active = True
                self._trigger_audio_alert()
        else:
            self.danger_start_time = None
            self.alert_active = False

    def _trigger_audio_alert(self):
        """Play an audio alert in a separate thread to avoid blocking the callback."""
        if self._alert_thread is not None and self._alert_thread.is_alive():
            return  # Alert already playing

        def _play_alert():
            hailo_logger.warning("ALERT: Unsafe sleeping position detected!")
            # Use system bell as a simple audio alert
            # In production, replace with a proper audio file playback
            print("\a")  # Terminal bell
            for _ in range(3):
                print("\a")
                time.sleep(0.5)

        self._alert_thread = threading.Thread(target=_play_alert, daemon=True)
        self._alert_thread.start()


# -----------------------------------------------------------------------------------------------
# User-defined callback function
# -----------------------------------------------------------------------------------------------
def app_callback(element, buffer, user_data):
    hailo_logger.debug("Callback triggered. Current frame count=%d", user_data.get_count())

    if buffer is None:
        hailo_logger.warning("Received None buffer.")
        return

    pad = element.get_static_pad("src")
    format, width, height = get_caps_from_pad(pad)

    frame = None
    if user_data.use_frame and format and width and height:
        frame = get_numpy_from_buffer(buffer, format, width, height)

    roi = hailo.get_roi_from_buffer(buffer)
    detections = roi.get_objects_typed(hailo.HAILO_DETECTION)

    best_detection = None
    best_confidence = 0.0

    # Find the best person detection (highest confidence)
    for detection in detections:
        label = detection.get_label()
        if label == "person" and detection.get_confidence() > best_confidence:
            best_confidence = detection.get_confidence()
            best_detection = detection

    if best_detection is not None:
        bbox = best_detection.get_bbox()
        landmarks = best_detection.get_objects_typed(hailo.HAILO_LANDMARKS)

        if landmarks and width and height:
            status, reason = analyze_sleep_position(landmarks, bbox, width, height)
            user_data.update_status(status, reason)

            hailo_logger.debug(
                "Sleep position: %s - %s (confidence: %.2f)",
                status,
                reason,
                best_confidence,
            )

            # Draw status overlay on frame if available
            if user_data.use_frame and frame is not None:
                color = STATUS_COLORS[status]

                # Draw status banner at top of frame
                banner_height = 60
                overlay = frame.copy()
                cv2.rectangle(overlay, (0, 0), (width, banner_height), color, -1)
                cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)

                # Status text
                status_text = f"Sleep Position: {status}"
                cv2.putText(
                    frame,
                    status_text,
                    (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (255, 255, 255),
                    2,
                )
                # Reason text
                cv2.putText(
                    frame,
                    reason,
                    (10, 50),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (255, 255, 255),
                    1,
                )

                # Draw alert indicator if active
                if user_data.alert_active:
                    cv2.putText(
                        frame,
                        "ALERT!",
                        (width - 150, 40),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        1.2,
                        (0, 0, 255),
                        3,
                    )

                # Draw keypoints for debugging
                points = landmarks[0].get_points()
                for name, idx in KEYPOINTS.items():
                    pt = points[idx]
                    px, py = get_keypoint_pixel_coords(pt, bbox, width, height)
                    if not (px == 0 and py == 0):
                        cv2.circle(frame, (px, py), 4, (0, 255, 0), -1)
        else:
            user_data.update_status(STATUS_WARNING, "No landmarks detected")
    else:
        user_data.update_status(STATUS_SAFE, "No person detected")

    if user_data.use_frame and frame is not None:
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        user_data.set_frame(frame)

    # Print status periodically (every 30 frames)
    if user_data.get_count() % 30 == 0:
        print(
            f"[Frame {user_data.get_count()}] "
            f"Status: {user_data.current_status} - {user_data.current_reason}"
        )

    return


def main():
    hailo_logger.info("Starting Baby Sleep Monitor App.")
    user_data = BabySleepCallbackData()
    app = GStreamerBabySleepMonitorApp(app_callback, user_data)
    app.run()


if __name__ == "__main__":
    main()
