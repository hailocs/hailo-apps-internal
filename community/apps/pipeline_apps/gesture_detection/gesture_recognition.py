"""
Pure Python module for gesture recognition from hand and body landmarks.

No Hailo/GStreamer dependencies - designed for testability.

Hand landmarks (21 keypoints from MediaPipe hand_landmark_lite):
    0: WRIST
    1: THUMB_CMC, 2: THUMB_MCP, 3: THUMB_IP, 4: THUMB_TIP
    5: INDEX_MCP, 6: INDEX_PIP, 7: INDEX_DIP, 8: INDEX_TIP
    9: MIDDLE_MCP, 10: MIDDLE_PIP, 11: MIDDLE_DIP, 12: MIDDLE_TIP
    13: RING_MCP, 14: RING_PIP, 15: RING_DIP, 16: RING_TIP
    17: PINKY_MCP, 18: PINKY_PIP, 19: PINKY_DIP, 20: PINKY_TIP

Body keypoints (17 from YOLOv8 pose, COCO format):
    0: nose, 1: left_eye, 2: right_eye, 3: left_ear, 4: right_ear
    5: left_shoulder, 6: right_shoulder, 7: left_elbow, 8: right_elbow
    9: left_wrist, 10: right_wrist, 11: left_hip, 12: right_hip
    13: left_knee, 14: right_knee, 15: left_ankle, 16: right_ankle
"""

import math


# Hand landmark indices
WRIST = 0
THUMB_CMC = 1
THUMB_MCP = 2
THUMB_IP = 3
THUMB_TIP = 4
INDEX_MCP = 5
INDEX_PIP = 6
INDEX_DIP = 7
INDEX_TIP = 8
MIDDLE_MCP = 9
MIDDLE_PIP = 10
MIDDLE_DIP = 11
MIDDLE_TIP = 12
RING_MCP = 13
RING_PIP = 14
RING_DIP = 15
RING_TIP = 16
PINKY_MCP = 17
PINKY_PIP = 18
PINKY_DIP = 19
PINKY_TIP = 20

# Body keypoint indices (COCO)
NOSE = 0
LEFT_SHOULDER = 5
RIGHT_SHOULDER = 6
LEFT_ELBOW = 7
RIGHT_ELBOW = 8
LEFT_WRIST = 9
RIGHT_WRIST = 10

# Finger definitions: (tip_index, pip_index)
FINGERS = [
    (INDEX_TIP, INDEX_PIP),
    (MIDDLE_TIP, MIDDLE_PIP),
    (RING_TIP, RING_PIP),
    (PINKY_TIP, PINKY_PIP),
]

# Gesture labels
GESTURE_FIST = "FIST"
GESTURE_OPEN_HAND = "OPEN_HAND"
GESTURE_POINTING = "POINTING"
GESTURE_PEACE = "PEACE"
GESTURE_THUMBS_UP = "THUMBS_UP"
GESTURE_THUMBS_DOWN = "THUMBS_DOWN"
GESTURE_ONE = "ONE"
GESTURE_TWO = "TWO"
GESTURE_THREE = "THREE"
GESTURE_FOUR = "FOUR"
GESTURE_T_POSE = "T_POSE"

# Confidence thresholds
MIN_BODY_KEYPOINT_CONFIDENCE = 0.3


def _distance(p1, p2):
    """Euclidean distance between two points with .x() and .y() methods."""
    dx = p1.x() - p2.x()
    dy = p1.y() - p2.y()
    return math.sqrt(dx * dx + dy * dy)


def is_finger_extended(points, tip_idx, pip_idx):
    """Check if a finger is extended by comparing tip-to-wrist vs PIP-to-wrist distance.

    A finger is considered extended if the tip is farther from the wrist
    than the PIP joint is from the wrist.
    """
    tip = points[tip_idx]
    pip = points[pip_idx]
    wrist = points[WRIST]

    tip_to_wrist = _distance(tip, wrist)
    pip_to_wrist = _distance(pip, wrist)

    return tip_to_wrist > pip_to_wrist


def is_thumb_extended(points):
    """Check if the thumb is extended.

    Uses distance from thumb tip to index MCP vs thumb MCP to index MCP.
    The thumb is extended if the tip is farther from the index MCP base.
    """
    thumb_tip = points[THUMB_TIP]
    thumb_mcp = points[THUMB_MCP]
    index_mcp = points[INDEX_MCP]

    tip_to_index = _distance(thumb_tip, index_mcp)
    mcp_to_index = _distance(thumb_mcp, index_mcp)

    return tip_to_index > mcp_to_index


def count_fingers(points):
    """Count the number of extended fingers (0-5).

    Args:
        points: List of 21 hand landmark points with .x(), .y() methods.

    Returns:
        int: Number of extended fingers (0-5).
    """
    if len(points) < 21:
        return -1

    count = 0

    # Check thumb
    if is_thumb_extended(points):
        count += 1

    # Check other four fingers
    for tip_idx, pip_idx in FINGERS:
        if is_finger_extended(points, tip_idx, pip_idx):
            count += 1

    return count


def classify_hand_gesture(points):
    """Classify the hand gesture based on finger states.

    Args:
        points: List of 21 hand landmark points with .x(), .y() methods.

    Returns:
        str: Gesture label or None if no gesture is recognized.
    """
    if len(points) < 21:
        return None

    thumb = is_thumb_extended(points)
    index = is_finger_extended(points, INDEX_TIP, INDEX_PIP)
    middle = is_finger_extended(points, MIDDLE_TIP, MIDDLE_PIP)
    ring = is_finger_extended(points, RING_TIP, RING_PIP)
    pinky = is_finger_extended(points, PINKY_TIP, PINKY_PIP)

    extended = [thumb, index, middle, ring, pinky]
    finger_count = sum(extended)

    if finger_count == 0:
        return GESTURE_FIST

    if finger_count == 5:
        return GESTURE_OPEN_HAND

    # Thumb only
    if thumb and not index and not middle and not ring and not pinky:
        # Determine up vs down based on thumb tip y relative to wrist
        # Lower y = higher in image (most coordinate systems)
        thumb_tip = points[THUMB_TIP]
        wrist = points[WRIST]
        if thumb_tip.y() < wrist.y():
            return GESTURE_THUMBS_UP
        else:
            return GESTURE_THUMBS_DOWN

    # Index only = POINTING
    if not thumb and index and not middle and not ring and not pinky:
        return GESTURE_POINTING

    # Index + middle = PEACE
    if not thumb and index and middle and not ring and not pinky:
        return GESTURE_PEACE

    # Generic finger count gestures
    finger_count_gestures = {
        1: GESTURE_ONE,
        2: GESTURE_TWO,
        3: GESTURE_THREE,
        4: GESTURE_FOUR,
    }
    return finger_count_gestures.get(finger_count)


def detect_t_pose(body_points):
    """Detect T-pose from body keypoints.

    T-pose is detected when:
    - Both arms are roughly horizontal (shoulder-elbow-wrist at similar y-level)
    - Wrists are spread wider than 1.5x shoulder width

    Args:
        body_points: List of 17 body keypoints with .x(), .y(), .confidence() methods.

    Returns:
        bool: True if T-pose is detected.
    """
    if len(body_points) < 17:
        return False

    # Check that required keypoints have sufficient confidence
    required_indices = [
        LEFT_SHOULDER,
        RIGHT_SHOULDER,
        LEFT_ELBOW,
        RIGHT_ELBOW,
        LEFT_WRIST,
        RIGHT_WRIST,
    ]
    for idx in required_indices:
        if body_points[idx].confidence() < MIN_BODY_KEYPOINT_CONFIDENCE:
            return False

    l_shoulder = body_points[LEFT_SHOULDER]
    r_shoulder = body_points[RIGHT_SHOULDER]
    l_elbow = body_points[LEFT_ELBOW]
    r_elbow = body_points[RIGHT_ELBOW]
    l_wrist = body_points[LEFT_WRIST]
    r_wrist = body_points[RIGHT_WRIST]

    # Shoulder width
    shoulder_width = abs(r_shoulder.x() - l_shoulder.x())
    if shoulder_width < 0.01:
        return False

    # Check that arms are roughly horizontal:
    # The y-difference between shoulder and wrist should be small relative to shoulder width
    horizontal_threshold = shoulder_width * 0.5

    left_arm_horizontal = (
        abs(l_shoulder.y() - l_elbow.y()) < horizontal_threshold
        and abs(l_shoulder.y() - l_wrist.y()) < horizontal_threshold
    )
    right_arm_horizontal = (
        abs(r_shoulder.y() - r_elbow.y()) < horizontal_threshold
        and abs(r_shoulder.y() - r_wrist.y()) < horizontal_threshold
    )

    if not (left_arm_horizontal and right_arm_horizontal):
        return False

    # Check that wrists are spread wider than 1.5x shoulder width
    wrist_spread = abs(r_wrist.x() - l_wrist.x())
    if wrist_spread < shoulder_width * 1.5:
        return False

    return True
