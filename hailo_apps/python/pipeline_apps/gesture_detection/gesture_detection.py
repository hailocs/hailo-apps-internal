# region imports
# Standard library imports
import os

os.environ["GST_PLUGIN_FEATURE_RANK"] = "vaapidecodebin:NONE"

# Third-party imports
import gi

gi.require_version("Gst", "1.0")

# Local application-specific imports
import hailo

from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.gstreamer.gstreamer_app import app_callback_class
from hailo_apps.python.pipeline_apps.gesture_detection.gesture_detection_pipeline import (
    GStreamerGestureDetectionApp,
)
from hailo_apps.python.pipeline_apps.gesture_detection.gesture_recognition import (
    classify_hand_gesture,
    count_fingers,
    detect_t_pose,
)

hailo_logger = get_logger(__name__)
# endregion imports


class user_app_callback_class(app_callback_class):
    def __init__(self):
        super().__init__()


def app_callback(element, buffer, user_data):
    """Per-frame callback that processes detections and recognizes gestures.

    For each person detection:
    - Check body pose landmarks for T-pose
    - For each hand sub-detection: extract hand landmarks, recognize gesture
    - Attach results as HailoClassification objects
    """
    if buffer is None:
        hailo_logger.warning("Received None buffer.")
        return

    roi = hailo.get_roi_from_buffer(buffer)
    detections = roi.get_objects_typed(hailo.HAILO_DETECTION)

    for detection in detections:
        label = detection.get_label()

        if label == "person":
            track_id = 0
            track = detection.get_objects_typed(hailo.HAILO_UNIQUE_ID)
            if len(track) == 1:
                track_id = track[0].get_id()

            # Check body gesture (T-pose) from pose landmarks
            body_landmarks = detection.get_objects_typed(hailo.HAILO_LANDMARKS)
            if body_landmarks:
                body_points = body_landmarks[0].get_points()
                if detect_t_pose(body_points):
                    body_gesture = hailo.HailoClassification(
                        type="body_gesture", label="T_POSE", confidence=1.0
                    )
                    detection.add_object(body_gesture)
                    hailo_logger.debug(
                        "Person ID %d: T-pose detected", track_id
                    )

            # Process hand sub-detections
            sub_detections = detection.get_objects_typed(hailo.HAILO_DETECTION)
            for sub_det in sub_detections:
                if sub_det.get_label() != "hand":
                    continue

                # Get hand side
                hand_side = "unknown"
                classifications = sub_det.get_objects_typed(
                    hailo.HAILO_CLASSIFICATION
                )
                for cls in classifications:
                    if cls.get_classification_type() == "hand_side":
                        hand_side = cls.get_label()
                        break

                # Get hand landmarks
                hand_landmarks = sub_det.get_objects_typed(hailo.HAILO_LANDMARKS)
                if not hand_landmarks:
                    continue

                hand_points = hand_landmarks[0].get_points()
                if len(hand_points) < 21:
                    continue

                # Classify gesture
                gesture = classify_hand_gesture(hand_points)
                finger_count = count_fingers(hand_points)

                if gesture:
                    gesture_cls = hailo.HailoClassification(
                        type="gesture", label=gesture, confidence=1.0
                    )
                    sub_det.add_object(gesture_cls)
                    hailo_logger.debug(
                        "Person ID %d, %s hand: %s (fingers: %d)",
                        track_id,
                        hand_side,
                        gesture,
                        finger_count,
                    )

    return


def main():
    hailo_logger.info("Starting Gesture Detection App.")
    user_data = user_app_callback_class()
    app = GStreamerGestureDetectionApp(app_callback, user_data)
    app.run()


if __name__ == "__main__":
    main()
