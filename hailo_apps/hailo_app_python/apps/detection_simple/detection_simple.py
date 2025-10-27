# region imports
# Standard library imports

# Third-party imports
import gi

gi.require_version("Gst", "1.0")
# Local application-specific imports
import hailo
from gi.repository import Gst

from hailo_apps.hailo_app_python.apps.detection_simple.detection_pipeline_simple import (
    GStreamerDetectionApp,
)

# Logger
from hailo_apps.hailo_app_python.core.common.hailo_logger import get_logger
from hailo_apps.hailo_app_python.core.gstreamer.gstreamer_app import app_callback_class

hailo_logger = get_logger(__name__)

# endregion imports


# User-defined class to be used in the callback function: Inheritance from the app_callback_class
class user_app_callback_class(app_callback_class):
    def __init__(self):
        super().__init__()


# User-defined callback function: This is the callback function that will be called when data is available from the pipeline
def app_callback(pad, info, user_data):
    user_data.increment()  # Using the user_data to count the number of frames
    frame_idx = user_data.get_count()
    hailo_logger.debug("Processing frame %s", frame_idx)  # Log the frame index being processed
    string_to_print = f"Frame count: {user_data.get_count()}\n"
    buffer = info.get_buffer()  # Get the GstBuffer from the probe info
    if buffer is None:  # Check if the buffer is valid
        hailo_logger.warning("Received None buffer | frame=%s", frame_idx)
        return Gst.PadProbeReturn.OK
    for detection in hailo.get_roi_from_buffer(buffer).get_objects_typed(
        hailo.HAILO_DETECTION
    ):  # Get the detections from the buffer & Parse the detections
        string_to_print += (
            f"Detection: {detection.get_label()} Confidence: {detection.get_confidence():.2f}\n"
        )
        hailo_logger.info(string_to_print)  # Log the detections
    print(string_to_print)
    return Gst.PadProbeReturn.OK


def main():
    hailo_logger.info("Starting GStreamer Detection Simple App...")
    user_data = user_app_callback_class()  # Create an instance of the user app callback class
    app = GStreamerDetectionApp(app_callback, user_data)
    app.run()


if __name__ == "__main__":
    main()
