# region imports
# Standard library imports

# Third-party imports
import gi

gi.require_version("Gst", "1.0")
import cv2

# Local application-specific imports
import hailo
import numpy as np  # Added because mask data uses np.array
from gi.repository import Gst

from hailo_apps.python.pipeline_apps.instance_segmentation.instance_segmentation_pipeline import (
    GStreamerInstanceSegmentationApp,
)
from hailo_apps.python.core.common.buffer_utils import (
    get_caps_from_pad,
    get_numpy_from_buffer,
)

# Logger
from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.gstreamer.gstreamer_app import app_callback_class

hailo_logger = get_logger(__name__)
# endregion imports


# -----------------------------------------------------------------------------------------------
# User-defined class to be used in the callback function
# -----------------------------------------------------------------------------------------------
class user_app_callback_class(app_callback_class):
    def __init__(self):
        super().__init__()
        self.frame_skip = 2  # Process every 2nd frame to reduce compute
        hailo_logger.debug(
            "Initialized user_app_callback_class with frame_skip=%d", self.frame_skip
        )


# Predefined colors (BGR format)
COLORS = [
    (255, 0, 0),  # Red
    (0, 255, 0),  # Green
    (0, 0, 255),  # Blue
    (255, 255, 0),  # Cyan
    (255, 0, 255),  # Magenta
    (0, 255, 255),  # Yellow
    (128, 0, 128),  # Purple
    (255, 165, 0),  # Orange
    (0, 128, 128),  # Teal
    (128, 128, 0),  # Olive
]


# -----------------------------------------------------------------------------------------------
# User-defined callback function
# -----------------------------------------------------------------------------------------------
def app_callback(pad, info, user_data):
    hailo_logger.debug("Callback triggered. Current frame count=%d", user_data.get_count())

    buffer = info.get_buffer()
    if buffer is None:
        hailo_logger.warning("Received None buffer in callback.")
        return Gst.PadProbeReturn.OK

    user_data.increment()
    hailo_logger.debug("Incremented frame count to %d", user_data.get_count())
    string_to_print = f"Frame count: {user_data.get_count()}\n"

    if user_data.get_count() % user_data.frame_skip != 0:
        hailo_logger.debug(
            "Skipping frame %d due to frame_skip=%d", user_data.get_count(), user_data.frame_skip
        )
        return Gst.PadProbeReturn.OK

    format, width, height = get_caps_from_pad(pad)
    hailo_logger.debug("Video format=%s width=%d height=%d", format, width, height)

    reduced_width = width // 4
    reduced_height = height // 4
    hailo_logger.debug("Reduced dimensions: width=%d height=%d", reduced_width, reduced_height)

    reduced_frame = None
    if user_data.use_frame and format is not None and width is not None and height is not None:
        hailo_logger.debug("Extracting frame from buffer for processing.")
        frame = get_numpy_from_buffer(buffer, format, width, height)
        reduced_frame = cv2.resize(
            frame, (reduced_width, reduced_height), interpolation=cv2.INTER_AREA
        )

    roi = hailo.get_roi_from_buffer(buffer)
    detections = roi.get_objects_typed(hailo.HAILO_DETECTION)
    hailo_logger.debug("Number of detections in frame: %d", len(detections))

    for detection in detections:
        label = detection.get_label()
        bbox = detection.get_bbox()
        confidence = detection.get_confidence()
        hailo_logger.debug(
            "Detection found: label=%s confidence=%.2f bbox=%s", label, confidence, bbox
        )

        if label == "person":
            track_id = 0
            track = detection.get_objects_typed(hailo.HAILO_UNIQUE_ID)
            if len(track) == 1:
                track_id = track[0].get_id()
            hailo_logger.debug("Person detection with track_id=%d", track_id)

            string_to_print += (
                f"Detection: ID: {track_id} Label: {label} Confidence: {confidence:.2f}\n"
            )

            if user_data.use_frame:
                masks = detection.get_objects_typed(hailo.HAILO_CONF_CLASS_MASK)
                hailo_logger.debug("Number of masks for detection: %d", len(masks))
                if len(masks) != 0:
                    mask = masks[0]
                    mask_height = mask.get_height()
                    mask_width = mask.get_width()
                    hailo_logger.debug("Mask size: width=%d height=%d", mask_width, mask_height)

                    data = np.array(mask.get_data())
                    data = data.reshape((mask_height, mask_width))

                    roi_width = int(bbox.width() * reduced_width)
                    roi_height = int(bbox.height() * reduced_height)
                    resized_mask_data = cv2.resize(
                        data, (roi_width, roi_height), interpolation=cv2.INTER_LINEAR
                    )

                    x_min, y_min = (
                        int(bbox.xmin() * reduced_width),
                        int(bbox.ymin() * reduced_height),
                    )
                    x_max, y_max = x_min + roi_width, y_min + roi_height

                    y_min = max(y_min, 0)
                    x_min = max(x_min, 0)
                    y_max = min(y_max, reduced_frame.shape[0])
                    x_max = min(x_max, reduced_frame.shape[1])

                    if x_max > x_min and y_max > y_min:
                        hailo_logger.debug(
                            "Overlaying mask for track_id=%d at (%d,%d) to (%d,%d)",
                            track_id,
                            x_min,
                            y_min,
                            x_max,
                            y_max,
                        )
                        mask_overlay = np.zeros_like(reduced_frame)
                        color = COLORS[track_id % len(COLORS)]
                        mask_overlay[y_min:y_max, x_min:x_max] = (
                            resized_mask_data[: y_max - y_min, : x_max - x_min, np.newaxis] > 0.5
                        ) * color
                        reduced_frame = cv2.addWeighted(reduced_frame, 1, mask_overlay, 0.5, 0)

    hailo_logger.debug("Frame detections:\n%s", string_to_print)
    print(string_to_print)

    if user_data.use_frame:
        reduced_frame = cv2.cvtColor(reduced_frame, cv2.COLOR_RGB2BGR)
        user_data.set_frame(reduced_frame)
        hailo_logger.debug("Frame set for user_data after processing.")

    return Gst.PadProbeReturn.OK


def main():
    hailo_logger.info("Starting Instance Segmentation App with custom callback.")
    user_data = user_app_callback_class()
    app = GStreamerInstanceSegmentationApp(app_callback, user_data)
    app.run()


if __name__ == "__main__":
    main()
