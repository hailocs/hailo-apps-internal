# region imports
# Standard library imports

# Third-party imports
import gi

gi.require_version("Gst", "1.0")
# Local application-specific imports
import hailo
import numpy as np
from gi.repository import Gst

from hailo_apps.python.pipeline_apps.depth.depth_pipeline import GStreamerDepthApp

# Logger
from hailo_apps.python.core.common.hailo_logger import (
    get_logger,
)
from hailo_apps.python.core.gstreamer.gstreamer_app import app_callback_class

hailo_logger = get_logger(__name__)
# endregion imports


# User-defined class to be used in the callback function: Inheritance from the app_callback_class
class user_app_callback_class(app_callback_class):
    def __init__(self):
        super().__init__()

    def calculate_average_depth(self, depth_mat):
        depth_values = np.array(
            depth_mat
        ).flatten()  # Flatten the array and filter out outlier pixels
        try:
            m_depth_values = depth_values[
                depth_values <= np.percentile(depth_values, 95)
            ]  # drop 5% of highest values (outliers)
        except Exception:
            hailo_logger.exception("Percentile computation failed; treating as empty depth set.")
            m_depth_values = np.array([])
        if len(m_depth_values) > 0:
            average_depth = np.mean(m_depth_values)  # Calculate the average depth of the pixels
        else:
            average_depth = 0  # Default value if no valid pixels are found
        return average_depth


# User-defined callback function: This is the callback function that will be called when data is available from the pipeline
def app_callback(pad, info, user_data):
    user_data.increment()  # Using the user_data to count the number of frames
    string_to_print = f"Frame count: {user_data.get_count()}\n"
    buffer = info.get_buffer()  # Get the GstBuffer from the probe info
    if buffer is None:  # Check if the buffer is valid
        hailo_logger.warning("Received None buffer at frame=%s", user_data.get_count())
        return Gst.PadProbeReturn.OK

    roi = hailo.get_roi_from_buffer(buffer)
    depth_mat = roi.get_objects_typed(hailo.HAILO_DEPTH_MASK)
    hailo_logger.debug("Frame=%s | depth_masks=%d", user_data.get_count(), len(depth_mat))

    if len(depth_mat) > 0:
        detection_average_depth = user_data.calculate_average_depth(depth_mat[0].get_data())
    else:
        detection_average_depth = 0

    string_to_print += f"average depth: {detection_average_depth:.2f}\n"
    print(string_to_print)
    hailo_logger.info(string_to_print.strip())

    return Gst.PadProbeReturn.OK


def main():
    hailo_logger.info("Starting Depth callback runner...")
    user_data = user_app_callback_class()
    app = GStreamerDepthApp(app_callback, user_data)
    app.run()


if __name__ == "__main__":
    main()
