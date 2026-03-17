# region imports
# Standard library imports
import math
import os

os.environ["GST_PLUGIN_FEATURE_RANK"] = "vaapidecodebin:NONE"

# Third-party imports
import gi

gi.require_version("Gst", "1.0")
import cv2

# Local application-specific imports
import hailo
from gi.repository import Gst

from community.apps.pipeline_apps.workout_rep_counter.workout_rep_counter_pipeline import (
    GStreamerWorkoutRepCounterApp,
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

# Exercise definitions: each exercise specifies three keypoints that form an angle,
# and threshold angles to distinguish the "up" and "down" phases.
EXERCISES = {
    "squat": {
        "joint_triplet": ("left_hip", "left_knee", "left_ankle"),
        "down_angle": 90,   # knee angle when in squat position
        "up_angle": 160,    # knee angle when standing
    },
    "pushup": {
        "joint_triplet": ("left_shoulder", "left_elbow", "left_wrist"),
        "down_angle": 90,   # elbow angle at bottom of pushup
        "up_angle": 160,    # elbow angle at top of pushup
    },
    "bicep_curl": {
        "joint_triplet": ("left_shoulder", "left_elbow", "left_wrist"),
        "down_angle": 160,  # arm extended
        "up_angle": 40,     # arm curled
    },
}


def calculate_angle(p1, p2, p3):
    """
    Calculate the angle at p2 formed by the line segments p1-p2 and p2-p3.

    Args:
        p1: tuple (x, y) for the first point
        p2: tuple (x, y) for the vertex point
        p3: tuple (x, y) for the third point

    Returns:
        Angle in degrees (0-180).
    """
    v1 = (p1[0] - p2[0], p1[1] - p2[1])
    v2 = (p3[0] - p2[0], p3[1] - p2[1])

    dot = v1[0] * v2[0] + v1[1] * v2[1]
    mag1 = math.sqrt(v1[0] ** 2 + v1[1] ** 2)
    mag2 = math.sqrt(v2[0] ** 2 + v2[1] ** 2)

    if mag1 == 0 or mag2 == 0:
        return 0.0

    cos_angle = max(-1.0, min(1.0, dot / (mag1 * mag2)))
    return math.degrees(math.acos(cos_angle))


class RepState:
    """Tracks the rep counting state for a single tracked person."""

    def __init__(self):
        self.phase = "up"  # current phase: "up" or "down"
        self.rep_count = 0
        self.current_angle = 0.0


# -----------------------------------------------------------------------------------------------
# User-defined class to be used in the callback function
# -----------------------------------------------------------------------------------------------
class user_app_callback_class(app_callback_class):
    def __init__(self):
        super().__init__()
        self.exercise = "squat"  # default exercise
        # Per-track-ID state: {track_id: RepState}
        self.track_states = {}


def get_keypoint_pixel_coords(points, keypoint_name, bbox, width, height):
    """
    Extract pixel coordinates for a named keypoint.

    Args:
        points: list of landmark points from hailo
        keypoint_name: string name of the keypoint
        bbox: HailoBBox for the detection
        width: frame width in pixels
        height: frame height in pixels

    Returns:
        (x, y) tuple in pixel coordinates, or None if not available.
    """
    idx = KEYPOINTS.get(keypoint_name)
    if idx is None or idx >= len(points):
        return None
    point = points[idx]
    x = (point.x() * bbox.width() + bbox.xmin()) * width
    y = (point.y() * bbox.height() + bbox.ymin()) * height
    return (x, y)


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

    exercise_config = EXERCISES.get(user_data.exercise, EXERCISES["squat"])
    joint_a, joint_b, joint_c = exercise_config["joint_triplet"]
    down_angle = exercise_config["down_angle"]
    up_angle = exercise_config["up_angle"]
    # Determine if "down" means smaller angle (like bicep curl) or larger
    down_is_smaller = down_angle < up_angle

    for detection in detections:
        label = detection.get_label()
        if label != "person":
            continue

        bbox = detection.get_bbox()
        confidence = detection.get_confidence()

        # Get track ID
        track_id = 0
        track = detection.get_objects_typed(hailo.HAILO_UNIQUE_ID)
        if len(track) == 1:
            track_id = track[0].get_id()

        # Get or create rep state for this tracked person
        if track_id not in user_data.track_states:
            user_data.track_states[track_id] = RepState()
        state = user_data.track_states[track_id]

        # Extract landmarks
        landmarks = detection.get_objects_typed(hailo.HAILO_LANDMARKS)
        if not landmarks:
            continue

        points = landmarks[0].get_points()

        # Get the three keypoints for the exercise angle
        p_a = get_keypoint_pixel_coords(points, joint_a, bbox, width, height)
        p_b = get_keypoint_pixel_coords(points, joint_b, bbox, width, height)
        p_c = get_keypoint_pixel_coords(points, joint_c, bbox, width, height)

        if p_a is None or p_b is None or p_c is None:
            continue

        angle = calculate_angle(p_a, p_b, p_c)
        state.current_angle = angle

        # Phase detection and rep counting
        if down_is_smaller:
            # For exercises like bicep curl: down phase = small angle
            if state.phase == "up" and angle <= down_angle:
                state.phase = "down"
            elif state.phase == "down" and angle >= up_angle:
                state.phase = "up"
                state.rep_count += 1
        else:
            # For exercises like squat/pushup: down phase = small angle
            if state.phase == "up" and angle <= down_angle:
                state.phase = "down"
            elif state.phase == "down" and angle >= up_angle:
                state.phase = "up"
                state.rep_count += 1

        # Draw overlay on frame if use_frame is enabled
        if user_data.use_frame and frame is not None:
            # Draw the angle arc at the joint
            p_b_int = (int(p_b[0]), int(p_b[1]))
            cv2.circle(frame, p_b_int, 6, (0, 255, 255), -1)

            # Draw lines from joint to adjacent keypoints
            p_a_int = (int(p_a[0]), int(p_a[1]))
            p_c_int = (int(p_c[0]), int(p_c[1]))
            cv2.line(frame, p_a_int, p_b_int, (0, 255, 0), 2)
            cv2.line(frame, p_b_int, p_c_int, (0, 255, 0), 2)

            # Display angle value near the joint
            cv2.putText(
                frame,
                f"{angle:.0f} deg",
                (p_b_int[0] + 10, p_b_int[1] - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (255, 255, 0),
                1,
            )

            # Display rep count and phase near the person's bounding box
            text_x = int(bbox.xmin() * width)
            text_y = max(20, int(bbox.ymin() * height) - 10)
            cv2.putText(
                frame,
                f"{user_data.exercise.upper()} Reps: {state.rep_count} ({state.phase})",
                (text_x, text_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0),
                2,
            )

        hailo_logger.debug(
            "Track %d: %s angle=%.1f phase=%s reps=%d",
            track_id,
            user_data.exercise,
            angle,
            state.phase,
            state.rep_count,
        )

    if user_data.use_frame and frame is not None:
        # Global exercise info overlay
        cv2.putText(
            frame,
            f"Exercise: {user_data.exercise.upper()}",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 255),
            2,
        )
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        user_data.set_frame(frame)

    # Periodic console output (every 30 frames)
    frame_count = user_data.get_count()
    if frame_count % 30 == 0:
        status = f"Frame {frame_count} | Exercise: {user_data.exercise.upper()} | Tracked people: {len(user_data.track_states)}"
        for tid, st in user_data.track_states.items():
            status += f"\n  Person {tid}: {st.rep_count} reps ({st.phase}, angle={st.current_angle:.0f})"
        print(status)

    return


def main():
    hailo_logger.info("Starting Workout Rep Counter App.")
    user_data = user_app_callback_class()
    app = GStreamerWorkoutRepCounterApp(app_callback, user_data)
    # Read exercise type from CLI args (parsed by the pipeline app)
    user_data.exercise = app.options_menu.exercise
    app.run()


if __name__ == "__main__":
    main()
