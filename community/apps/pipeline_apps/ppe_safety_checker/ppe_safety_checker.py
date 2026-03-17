# region imports
import os
os.environ["GST_PLUGIN_FEATURE_RANK"] = "vaapidecodebin:NONE"
# Local application-specific imports
import hailo
from community.apps.pipeline_apps.ppe_safety_checker.ppe_safety_checker_pipeline import (
    GStreamerPPESafetyCheckerApp,
    PPESafetyCallback,
    PPE_STATUS_SAFE,
    PPE_STATUS_VIOLATION,
    PPE_STATUS_UNKNOWN,
)
# endregion


def app_callback(element, buffer, user_data):
    """
    User callback for PPE safety checker.

    Processes each frame's detections and logs PPE compliance status.
    Color-coded bounding boxes are handled by the overlay element based
    on the classification metadata added in the matching callback.
    """
    if buffer is None:
        return

    roi = hailo.get_roi_from_buffer(buffer)
    if roi is None:
        return

    detections = roi.get_objects_typed(hailo.HAILO_DETECTION)

    for detection in detections:
        classifications = detection.get_objects_typed(hailo.HAILO_CLASSIFICATION)
        for classification in classifications:
            label = classification.get_label()
            confidence = classification.get_confidence()

            if PPE_STATUS_SAFE in label:
                user_data.safe_count += 1
            elif PPE_STATUS_VIOLATION in label:
                user_data.violation_count += 1
            user_data.total_checks += 1

    # Periodic status logging
    if user_data.total_checks > 0 and user_data.total_checks % 100 == 0:
        print(
            f"[PPE Status] Total checks: {user_data.total_checks} | "
            f"Safe: {user_data.safe_count} | "
            f"Violations: {user_data.violation_count}"
        )


def main():
    user_data = PPESafetyCallback()
    app = GStreamerPPESafetyCheckerApp(app_callback, user_data)
    app.run()


if __name__ == "__main__":
    main()
