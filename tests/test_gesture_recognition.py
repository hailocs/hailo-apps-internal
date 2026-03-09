"""
Unit tests for gesture recognition module.

Tests the pure Python gesture recognition algorithms without any hardware
or GStreamer dependencies. Uses mock point objects to simulate Hailo landmarks.
"""

import pytest

from hailo_apps.python.pipeline_apps.gesture_detection.gesture_recognition import (
    GESTURE_FIST,
    GESTURE_FOUR,
    GESTURE_ONE,
    GESTURE_OPEN_HAND,
    GESTURE_PEACE,
    GESTURE_POINTING,
    GESTURE_THREE,
    GESTURE_THUMBS_DOWN,
    GESTURE_THUMBS_UP,
    GESTURE_TWO,
    classify_hand_gesture,
    count_fingers,
    detect_t_pose,
    is_finger_extended,
    is_thumb_extended,
    INDEX_TIP,
    INDEX_PIP,
)


class MockPoint:
    """Mock point simulating HailoPoint interface (.x(), .y(), .confidence())."""

    def __init__(self, x, y, confidence=1.0):
        self._x = x
        self._y = y
        self._confidence = confidence

    def x(self):
        return self._x

    def y(self):
        return self._y

    def confidence(self):
        return self._confidence


def make_hand_points(positions):
    """Create 21 mock hand landmark points from a list of (x, y) tuples."""
    return [MockPoint(x, y) for x, y in positions]


def make_body_points(positions, confidences=None):
    """Create 17 mock body keypoints from a list of (x, y) tuples with optional confidences."""
    if confidences is None:
        confidences = [1.0] * len(positions)
    return [MockPoint(x, y, c) for (x, y), c in zip(positions, confidences)]


# ============================================================
# Hand landmark positions for common gestures
# ============================================================

# Fist: all fingers curled, tips close to wrist
# Thumb curled: tip close to index_mcp (closer than thumb_mcp is to index_mcp)
FIST_POSITIONS = [
    (0.5, 0.8),   # 0: WRIST
    (0.35, 0.72), # 1: THUMB_CMC
    (0.30, 0.65), # 2: THUMB_MCP (far from index_mcp)
    (0.38, 0.63), # 3: THUMB_IP (curling back toward palm)
    (0.44, 0.62), # 4: THUMB_TIP (curled, close to index_mcp)
    (0.45, 0.6),  # 5: INDEX_MCP
    (0.44, 0.55), # 6: INDEX_PIP
    (0.45, 0.62), # 7: INDEX_DIP (curled)
    (0.46, 0.68), # 8: INDEX_TIP (curled, close to wrist)
    (0.50, 0.58), # 9: MIDDLE_MCP
    (0.50, 0.53), # 10: MIDDLE_PIP
    (0.50, 0.60), # 11: MIDDLE_DIP (curled)
    (0.50, 0.66), # 12: MIDDLE_TIP (curled)
    (0.55, 0.60), # 13: RING_MCP
    (0.55, 0.55), # 14: RING_PIP
    (0.55, 0.62), # 15: RING_DIP (curled)
    (0.55, 0.68), # 16: RING_TIP (curled)
    (0.60, 0.65), # 17: PINKY_MCP
    (0.60, 0.60), # 18: PINKY_PIP
    (0.60, 0.65), # 19: PINKY_DIP (curled)
    (0.60, 0.70), # 20: PINKY_TIP (curled)
]

# Open hand: all fingers extended away from wrist
OPEN_HAND_POSITIONS = [
    (0.5, 0.9),   # 0: WRIST
    (0.35, 0.8),  # 1: THUMB_CMC
    (0.25, 0.7),  # 2: THUMB_MCP
    (0.18, 0.6),  # 3: THUMB_IP
    (0.12, 0.5),  # 4: THUMB_TIP (far from index MCP)
    (0.38, 0.55), # 5: INDEX_MCP
    (0.36, 0.45), # 6: INDEX_PIP
    (0.35, 0.35), # 7: INDEX_DIP
    (0.34, 0.25), # 8: INDEX_TIP (extended)
    (0.50, 0.52), # 9: MIDDLE_MCP
    (0.50, 0.42), # 10: MIDDLE_PIP
    (0.50, 0.32), # 11: MIDDLE_DIP
    (0.50, 0.22), # 12: MIDDLE_TIP (extended)
    (0.62, 0.55), # 13: RING_MCP
    (0.64, 0.45), # 14: RING_PIP
    (0.65, 0.35), # 15: RING_DIP
    (0.66, 0.25), # 16: RING_TIP (extended)
    (0.72, 0.60), # 17: PINKY_MCP
    (0.75, 0.50), # 18: PINKY_PIP
    (0.77, 0.40), # 19: PINKY_DIP
    (0.80, 0.30), # 20: PINKY_TIP (extended)
]

# Pointing: only index finger extended, thumb curled
POINTING_POSITIONS = [
    (0.5, 0.8),   # 0: WRIST
    (0.35, 0.72), # 1: THUMB_CMC
    (0.30, 0.65), # 2: THUMB_MCP (far from index_mcp)
    (0.38, 0.63), # 3: THUMB_IP (curling back toward palm)
    (0.44, 0.62), # 4: THUMB_TIP (curled, close to index_mcp)
    (0.45, 0.55), # 5: INDEX_MCP
    (0.44, 0.45), # 6: INDEX_PIP
    (0.43, 0.35), # 7: INDEX_DIP
    (0.42, 0.25), # 8: INDEX_TIP (extended)
    (0.50, 0.58), # 9: MIDDLE_MCP
    (0.50, 0.53), # 10: MIDDLE_PIP
    (0.50, 0.60), # 11: MIDDLE_DIP (curled)
    (0.50, 0.66), # 12: MIDDLE_TIP (curled)
    (0.55, 0.60), # 13: RING_MCP
    (0.55, 0.55), # 14: RING_PIP
    (0.55, 0.62), # 15: RING_DIP (curled)
    (0.55, 0.68), # 16: RING_TIP (curled)
    (0.60, 0.65), # 17: PINKY_MCP
    (0.60, 0.60), # 18: PINKY_PIP
    (0.60, 0.65), # 19: PINKY_DIP (curled)
    (0.60, 0.70), # 20: PINKY_TIP (curled)
]

# Peace sign: index + middle extended, thumb curled
PEACE_POSITIONS = [
    (0.5, 0.8),   # 0: WRIST
    (0.35, 0.72), # 1: THUMB_CMC
    (0.30, 0.65), # 2: THUMB_MCP (far from index_mcp)
    (0.38, 0.60), # 3: THUMB_IP (curling back toward palm)
    (0.43, 0.58), # 4: THUMB_TIP (curled, close to index_mcp)
    (0.42, 0.55), # 5: INDEX_MCP
    (0.41, 0.45), # 6: INDEX_PIP
    (0.40, 0.35), # 7: INDEX_DIP
    (0.39, 0.25), # 8: INDEX_TIP (extended)
    (0.52, 0.53), # 9: MIDDLE_MCP
    (0.52, 0.43), # 10: MIDDLE_PIP
    (0.52, 0.33), # 11: MIDDLE_DIP
    (0.52, 0.23), # 12: MIDDLE_TIP (extended)
    (0.58, 0.60), # 13: RING_MCP
    (0.58, 0.55), # 14: RING_PIP
    (0.58, 0.62), # 15: RING_DIP (curled)
    (0.58, 0.68), # 16: RING_TIP (curled)
    (0.63, 0.65), # 17: PINKY_MCP
    (0.63, 0.60), # 18: PINKY_PIP
    (0.63, 0.65), # 19: PINKY_DIP (curled)
    (0.63, 0.70), # 20: PINKY_TIP (curled)
]

# Thumbs up: only thumb extended, pointing upward
THUMBS_UP_POSITIONS = [
    (0.5, 0.8),   # 0: WRIST
    (0.42, 0.7),  # 1: THUMB_CMC
    (0.35, 0.6),  # 2: THUMB_MCP
    (0.30, 0.5),  # 3: THUMB_IP
    (0.25, 0.4),  # 4: THUMB_TIP (up, y < wrist.y)
    (0.45, 0.6),  # 5: INDEX_MCP
    (0.44, 0.55), # 6: INDEX_PIP
    (0.45, 0.62), # 7: INDEX_DIP (curled)
    (0.46, 0.68), # 8: INDEX_TIP (curled)
    (0.50, 0.58), # 9: MIDDLE_MCP
    (0.50, 0.53), # 10: MIDDLE_PIP
    (0.50, 0.60), # 11: MIDDLE_DIP (curled)
    (0.50, 0.66), # 12: MIDDLE_TIP (curled)
    (0.55, 0.60), # 13: RING_MCP
    (0.55, 0.55), # 14: RING_PIP
    (0.55, 0.62), # 15: RING_DIP (curled)
    (0.55, 0.68), # 16: RING_TIP (curled)
    (0.60, 0.65), # 17: PINKY_MCP
    (0.60, 0.60), # 18: PINKY_PIP
    (0.60, 0.65), # 19: PINKY_DIP (curled)
    (0.60, 0.70), # 20: PINKY_TIP (curled)
]

# Thumbs down: only thumb extended, pointing downward
THUMBS_DOWN_POSITIONS = [
    (0.5, 0.3),   # 0: WRIST
    (0.42, 0.4),  # 1: THUMB_CMC
    (0.35, 0.5),  # 2: THUMB_MCP
    (0.30, 0.6),  # 3: THUMB_IP
    (0.25, 0.7),  # 4: THUMB_TIP (down, y > wrist.y)
    (0.45, 0.45), # 5: INDEX_MCP
    (0.44, 0.40), # 6: INDEX_PIP
    (0.45, 0.43), # 7: INDEX_DIP (curled)
    (0.46, 0.38), # 8: INDEX_TIP (curled, close to wrist)
    (0.50, 0.43), # 9: MIDDLE_MCP
    (0.50, 0.38), # 10: MIDDLE_PIP
    (0.50, 0.41), # 11: MIDDLE_DIP (curled)
    (0.50, 0.37), # 12: MIDDLE_TIP (curled)
    (0.55, 0.43), # 13: RING_MCP
    (0.55, 0.38), # 14: RING_PIP
    (0.55, 0.41), # 15: RING_DIP (curled)
    (0.55, 0.37), # 16: RING_TIP (curled)
    (0.60, 0.38), # 17: PINKY_MCP
    (0.60, 0.35), # 18: PINKY_PIP
    (0.60, 0.37), # 19: PINKY_DIP (curled)
    (0.60, 0.34), # 20: PINKY_TIP (curled)
]


# ============================================================
# Body keypoint positions for T-pose and non-T-pose
# ============================================================

# T-pose: arms horizontal, wrists spread wide
T_POSE_POSITIONS = [
    (0.50, 0.15),  # 0: nose
    (0.47, 0.12),  # 1: left_eye
    (0.53, 0.12),  # 2: right_eye
    (0.44, 0.14),  # 3: left_ear
    (0.56, 0.14),  # 4: right_ear
    (0.40, 0.30),  # 5: left_shoulder
    (0.60, 0.30),  # 6: right_shoulder
    (0.25, 0.30),  # 7: left_elbow (horizontal)
    (0.75, 0.30),  # 8: right_elbow (horizontal)
    (0.10, 0.30),  # 9: left_wrist (spread wide, horizontal)
    (0.90, 0.30),  # 10: right_wrist (spread wide, horizontal)
    (0.42, 0.55),  # 11: left_hip
    (0.58, 0.55),  # 12: right_hip
    (0.42, 0.75),  # 13: left_knee
    (0.58, 0.75),  # 14: right_knee
    (0.42, 0.95),  # 15: left_ankle
    (0.58, 0.95),  # 16: right_ankle
]

# Arms down: normal standing pose
ARMS_DOWN_POSITIONS = [
    (0.50, 0.15),  # 0: nose
    (0.47, 0.12),  # 1: left_eye
    (0.53, 0.12),  # 2: right_eye
    (0.44, 0.14),  # 3: left_ear
    (0.56, 0.14),  # 4: right_ear
    (0.40, 0.30),  # 5: left_shoulder
    (0.60, 0.30),  # 6: right_shoulder
    (0.38, 0.45),  # 7: left_elbow (down)
    (0.62, 0.45),  # 8: right_elbow (down)
    (0.37, 0.60),  # 9: left_wrist (down)
    (0.63, 0.60),  # 10: right_wrist (down)
    (0.42, 0.55),  # 11: left_hip
    (0.58, 0.55),  # 12: right_hip
    (0.42, 0.75),  # 13: left_knee
    (0.58, 0.75),  # 14: right_knee
    (0.42, 0.95),  # 15: left_ankle
    (0.58, 0.95),  # 16: right_ankle
]


# ============================================================
# Tests: Finger Counting
# ============================================================


class TestFingerCounting:
    def test_count_zero_fingers_fist(self):
        points = make_hand_points(FIST_POSITIONS)
        assert count_fingers(points) == 0

    def test_count_five_fingers_open_hand(self):
        points = make_hand_points(OPEN_HAND_POSITIONS)
        assert count_fingers(points) == 5

    def test_count_one_finger_pointing(self):
        points = make_hand_points(POINTING_POSITIONS)
        assert count_fingers(points) == 1

    def test_count_two_fingers_peace(self):
        points = make_hand_points(PEACE_POSITIONS)
        assert count_fingers(points) == 2

    def test_count_one_finger_thumbs_up(self):
        points = make_hand_points(THUMBS_UP_POSITIONS)
        assert count_fingers(points) == 1

    def test_insufficient_keypoints(self):
        points = make_hand_points(FIST_POSITIONS[:10])
        assert count_fingers(points) == -1


# ============================================================
# Tests: Hand Gesture Classification
# ============================================================


class TestHandGestureClassification:
    def test_fist(self):
        points = make_hand_points(FIST_POSITIONS)
        assert classify_hand_gesture(points) == GESTURE_FIST

    def test_open_hand(self):
        points = make_hand_points(OPEN_HAND_POSITIONS)
        assert classify_hand_gesture(points) == GESTURE_OPEN_HAND

    def test_pointing(self):
        points = make_hand_points(POINTING_POSITIONS)
        assert classify_hand_gesture(points) == GESTURE_POINTING

    def test_peace(self):
        points = make_hand_points(PEACE_POSITIONS)
        assert classify_hand_gesture(points) == GESTURE_PEACE

    def test_thumbs_up(self):
        points = make_hand_points(THUMBS_UP_POSITIONS)
        assert classify_hand_gesture(points) == GESTURE_THUMBS_UP

    def test_thumbs_down(self):
        points = make_hand_points(THUMBS_DOWN_POSITIONS)
        assert classify_hand_gesture(points) == GESTURE_THUMBS_DOWN

    def test_insufficient_keypoints_returns_none(self):
        points = make_hand_points(OPEN_HAND_POSITIONS[:15])
        assert classify_hand_gesture(points) is None


# ============================================================
# Tests: T-Pose Detection
# ============================================================


class TestTPoseDetection:
    def test_t_pose_detected(self):
        body_points = make_body_points(T_POSE_POSITIONS)
        assert detect_t_pose(body_points) is True

    def test_arms_down_not_t_pose(self):
        body_points = make_body_points(ARMS_DOWN_POSITIONS)
        assert detect_t_pose(body_points) is False

    def test_insufficient_keypoints(self):
        body_points = make_body_points(T_POSE_POSITIONS[:10])
        assert detect_t_pose(body_points) is False

    def test_low_confidence_keypoints(self):
        """T-pose should not be detected if keypoints have low confidence."""
        confidences = [1.0] * 17
        # Set left wrist confidence to below threshold
        confidences[9] = 0.1
        body_points = make_body_points(T_POSE_POSITIONS, confidences)
        assert detect_t_pose(body_points) is False

    def test_one_arm_up_not_t_pose(self):
        """Only one arm horizontal should not be T-pose."""
        positions = list(ARMS_DOWN_POSITIONS)
        # Make left arm horizontal but keep right arm down
        positions[7] = (0.25, 0.30)   # left_elbow horizontal
        positions[9] = (0.10, 0.30)   # left_wrist horizontal
        body_points = make_body_points(positions)
        assert detect_t_pose(body_points) is False

    def test_wrists_not_spread_enough(self):
        """Arms horizontal but wrists not spread wide enough should not be T-pose."""
        positions = list(T_POSE_POSITIONS)
        # Narrow the wrist spread (shoulder_width=0.20, need wrist_spread < 0.30)
        positions[9] = (0.38, 0.30)   # left_wrist (not spread enough)
        positions[10] = (0.62, 0.30)  # right_wrist (not spread enough)
        body_points = make_body_points(positions)
        assert detect_t_pose(body_points) is False


# ============================================================
# Tests: Individual finger extension
# ============================================================


class TestFingerExtension:
    def test_finger_extended(self):
        """Index finger extended: tip is farther from wrist than PIP."""
        points = make_hand_points(POINTING_POSITIONS)
        assert is_finger_extended(points, INDEX_TIP, INDEX_PIP) is True

    def test_finger_curled(self):
        """Index finger curled: tip is closer to wrist than PIP."""
        points = make_hand_points(FIST_POSITIONS)
        assert is_finger_extended(points, INDEX_TIP, INDEX_PIP) is False

    def test_thumb_extended(self):
        points = make_hand_points(THUMBS_UP_POSITIONS)
        assert is_thumb_extended(points) is True

    def test_thumb_curled(self):
        points = make_hand_points(FIST_POSITIONS)
        assert is_thumb_extended(points) is False
