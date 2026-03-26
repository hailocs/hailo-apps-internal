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

from community.apps.pipeline_apps.semaphore_translator.semaphore_translator_pipeline import (
    GStreamerSemaphoreTranslatorApp,
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

# Semaphore flag alphabet mapping (International Maritime Standard)
# Each letter is defined by the angles of the right and left arms.
# Angles are from the SIGNALER'S perspective, measured clockwise from straight down:
#   0° = down, 45° = down-right, 90° = right (horizontal), 135° = up-right,
#   180° = up, 225° = up-left, 270° = left (horizontal), 315° = down-left
#
# Note: compute_arm_angle() produces signaler-perspective angles directly
# because atan2(-dx, dy) on COCO keypoints (person's own left/right) mirrors
# the image coordinates back to the signaler's frame of reference.
#
# Format: (right_arm_angle, left_arm_angle)
# Angles are discretized to nearest 45-degree increment.
#
# References:
#   https://www.anbg.gov.au/flags/semaphore.html
#   https://en.wikipedia.org/wiki/Flag_semaphore
SEMAPHORE_ALPHABET = {
    # Circle 1 (A-G): one arm at 0° (down)
    (45, 0): "A",      # right low-right, left down
    (90, 0): "B",      # right horizontal-right, left down
    (135, 0): "C",     # right up-right, left down
    (180, 0): "D",     # right up, left down
    (0, 225): "E",     # right down, left up-left
    (0, 270): "F",     # right down, left horizontal-left
    (0, 315): "G",     # right down, left down-left
    # Circle 2 (H-N): one arm at 45°
    (90, 45): "H",     # right horizontal-right, left crosses to low-right
    (135, 45): "I",    # right up-right, left crosses to low-right
    (180, 270): "J",   # right up, left horizontal-left (also "letters follow")
    (45, 180): "K",    # right low-right, left up
    (45, 225): "L",    # right low-right, left up-left
    (45, 270): "M",    # right low-right, left horizontal-left
    (45, 315): "N",    # right low-right, left down-left
    # Circle 3 (O-S): one arm at 90°
    (90, 135): "O",    # right horizontal-right, left crosses to up-right
    (90, 180): "P",    # right horizontal-right, left up
    (90, 225): "Q",    # right horizontal-right, left up-left
    (90, 270): "R",    # right horizontal-right, left horizontal-left
    (90, 315): "S",    # right horizontal-right, left down-left
    # Circle 4 (T-U): one arm at 135°
    (135, 180): "T",   # right up-right, left up
    (135, 225): "U",   # right up-right, left up-left
    # Remaining letters
    (180, 315): "V",   # right up, left down-left
    (225, 270): "W",   # right crosses to up-left, left horizontal-left
    (225, 315): "X",   # right crosses to up-left, left down-left
    (135, 270): "Y",   # right up-right, left horizontal-left
    (315, 270): "Z",   # right crosses to down-left, left horizontal-left
    # Special signals
    (0, 0): "REST",
}

# Tolerance for angle matching (degrees)
ANGLE_TOLERANCE = 30


def compute_arm_angle(shoulder_x, shoulder_y, wrist_x, wrist_y):
    """
    Compute the angle of an arm from shoulder to wrist.
    Returns angle in degrees (0-360), where:
      0 = straight down
      90 = pointing right (in image coordinates)
      180 = straight up
      270 = pointing left (in image coordinates)
    """
    dx = wrist_x - shoulder_x
    dy = wrist_y - shoulder_y  # positive = downward in image coords

    # atan2 gives angle from positive x-axis, counterclockwise
    # We want angle from downward direction, clockwise
    angle_rad = math.atan2(-dx, dy)  # negated dx to get clockwise from down
    angle_deg = math.degrees(angle_rad)

    # Normalize to 0-360
    if angle_deg < 0:
        angle_deg += 360.0

    return angle_deg


def discretize_angle(angle):
    """Discretize angle to nearest 45-degree increment."""
    discrete = round(angle / 45.0) * 45
    if discrete == 360:
        discrete = 0
    return int(discrete)


def decode_semaphore(right_arm_angle, left_arm_angle):
    """
    Given discretized arm angles, look up the semaphore letter.
    Returns the letter or '?' if no match found.
    Uses closest match within ANGLE_TOLERANCE for robustness.
    """
    key = (right_arm_angle, left_arm_angle)
    if key in SEMAPHORE_ALPHABET:
        return SEMAPHORE_ALPHABET[key]

    # Find closest match within tolerance
    best_letter = "?"
    best_distance = float("inf")
    for (r_angle, l_angle), letter in SEMAPHORE_ALPHABET.items():
        r_diff = abs(right_arm_angle - r_angle) % 360
        r_diff = min(r_diff, 360 - r_diff)
        l_diff = abs(left_arm_angle - l_angle) % 360
        l_diff = min(l_diff, 360 - l_diff)
        if r_diff <= ANGLE_TOLERANCE and l_diff <= ANGLE_TOLERANCE:
            distance = r_diff + l_diff
            if distance < best_distance:
                best_distance = distance
                best_letter = letter

    return best_letter


def get_keypoint_pixel_coords(points, keypoint_name, bbox, width, height):
    """Extract pixel coordinates for a named keypoint."""
    idx = KEYPOINTS[keypoint_name]
    point = points[idx]
    x = (point.x() * bbox.width() + bbox.xmin()) * width
    y = (point.y() * bbox.height() + bbox.ymin()) * height
    return x, y


# -----------------------------------------------------------------------------------------------
# User-defined class to be used in the callback function
# -----------------------------------------------------------------------------------------------
class user_app_callback_class(app_callback_class):
    def __init__(self):
        super().__init__()
        self.decoded_word = ""
        self.last_letter = ""
        self.stable_count = 0
        self.stable_threshold = 10  # frames before accepting a letter


# -----------------------------------------------------------------------------------------------
# User-defined callback function
# -----------------------------------------------------------------------------------------------
def app_callback(element, buffer, user_data):
    hailo_logger.debug("Callback triggered. Current frame count=%d", user_data.get_count())

    if buffer is None:
        hailo_logger.warning("Received None buffer.")
        return

    string_to_print = f"Frame count: {user_data.get_count()}\n"

    pad = element.get_static_pad("src")
    format, width, height = get_caps_from_pad(pad)

    frame = None
    if user_data.use_frame and format and width and height:
        frame = get_numpy_from_buffer(buffer, format, width, height)

    roi = hailo.get_roi_from_buffer(buffer)
    detections = roi.get_objects_typed(hailo.HAILO_DETECTION)

    for detection in detections:
        label = detection.get_label()
        bbox = detection.get_bbox()
        confidence = detection.get_confidence()

        if label != "person":
            continue

        track_id = 0
        track = detection.get_objects_typed(hailo.HAILO_UNIQUE_ID)
        if len(track) == 1:
            track_id = track[0].get_id()

        landmarks = detection.get_objects_typed(hailo.HAILO_LANDMARKS)
        if not landmarks:
            continue

        points = landmarks[0].get_points()

        # Get shoulder and wrist coordinates for both arms
        r_shoulder_x, r_shoulder_y = get_keypoint_pixel_coords(
            points, "right_shoulder", bbox, width, height
        )
        r_wrist_x, r_wrist_y = get_keypoint_pixel_coords(
            points, "right_wrist", bbox, width, height
        )
        l_shoulder_x, l_shoulder_y = get_keypoint_pixel_coords(
            points, "left_shoulder", bbox, width, height
        )
        l_wrist_x, l_wrist_y = get_keypoint_pixel_coords(
            points, "left_wrist", bbox, width, height
        )

        # Compute arm angles
        right_arm_angle = compute_arm_angle(r_shoulder_x, r_shoulder_y, r_wrist_x, r_wrist_y)
        left_arm_angle = compute_arm_angle(l_shoulder_x, l_shoulder_y, l_wrist_x, l_wrist_y)

        # Discretize to 45-degree increments
        right_discrete = discretize_angle(right_arm_angle)
        left_discrete = discretize_angle(left_arm_angle)

        # Decode the semaphore letter
        letter = decode_semaphore(right_discrete, left_discrete)

        # Stabilization: require the same letter for several consecutive frames
        if letter == user_data.last_letter:
            user_data.stable_count += 1
        else:
            user_data.last_letter = letter
            user_data.stable_count = 1

        if user_data.stable_count == user_data.stable_threshold:
            if letter != "REST" and letter != "?":
                user_data.decoded_word += letter

        string_to_print += (
            f"Person ID:{track_id} Conf:{confidence:.2f} "
            f"R_arm:{right_discrete}deg L_arm:{left_discrete}deg "
            f"Letter: {letter}\n"
        )
        string_to_print += f"Decoded word: {user_data.decoded_word}\n"

        # Draw overlay on frame if use_frame is enabled
        if user_data.use_frame and frame is not None:
            # Draw arm angle lines
            cv2.line(
                frame,
                (int(r_shoulder_x), int(r_shoulder_y)),
                (int(r_wrist_x), int(r_wrist_y)),
                (0, 0, 255),
                3,
            )
            cv2.line(
                frame,
                (int(l_shoulder_x), int(l_shoulder_y)),
                (int(l_wrist_x), int(l_wrist_y)),
                (255, 0, 0),
                3,
            )

            # Draw detected letter
            text_x = int(bbox.xmin() * width)
            text_y = int(bbox.ymin() * height) - 10
            cv2.putText(
                frame,
                f"Signal: {letter}",
                (text_x, text_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.0,
                (0, 255, 0),
                2,
            )

            # Draw decoded word at the top of the frame
            cv2.putText(
                frame,
                f"Word: {user_data.decoded_word}",
                (20, 50),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.5,
                (255, 255, 0),
                3,
            )

    if user_data.use_frame and frame is not None:
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        user_data.set_frame(frame)

    if user_data.get_count() % 30 == 0:
        print(string_to_print)
    return


def main():
    hailo_logger.info("Starting Semaphore Translator App.")
    user_data = user_app_callback_class()
    app = GStreamerSemaphoreTranslatorApp(app_callback, user_data)
    app.run()


if __name__ == "__main__":
    main()
