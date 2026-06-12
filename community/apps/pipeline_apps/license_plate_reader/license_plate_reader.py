# region imports
# Standard library imports
import os
import csv
from datetime import datetime

os.environ["GST_PLUGIN_FEATURE_RANK"] = "vaapidecodebin:NONE"

# Third-party imports
import gi

gi.require_version("Gst", "1.0")
import cv2

# Local application-specific imports
import hailo
from gi.repository import Gst

from community.apps.pipeline_apps.license_plate_reader.license_plate_reader_pipeline import (
    GStreamerLicensePlateReaderApp,
)
from hailo_apps.python.core.common.buffer_utils import (
    get_caps_from_pad,
    get_numpy_from_buffer,
)

from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.gstreamer.gstreamer_app import app_callback_class

hailo_logger = get_logger(__name__)
# endregion imports


# -----------------------------------------------------------------------------------------------
# User-defined class to be used in the callback function
# -----------------------------------------------------------------------------------------------
class PlateReaderCallbackData(app_callback_class):
    """Callback state for the license plate reader.

    Maintains a running log of recognized plates with timestamps and
    a per-frame list of plate readings for optional OpenCV overlay.
    """

    def __init__(self, log_file=None):
        super().__init__()
        self.plate_results = []  # Current frame plate results
        self.plate_log = []  # Running log of all recognized plates
        self.log_file = log_file
        self._csv_writer = None
        self._csv_file = None

        # Initialize CSV log file if requested
        if self.log_file:
            try:
                self._csv_file = open(self.log_file, "w", newline="")
                self._csv_writer = csv.writer(self._csv_file)
                self._csv_writer.writerow(["timestamp", "plate_text", "confidence"])
                hailo_logger.info("Plate log file initialized: %s", self.log_file)
            except OSError as e:
                hailo_logger.error("Failed to open log file %s: %s", self.log_file, e)
                self._csv_file = None
                self._csv_writer = None

    def get_plate_results(self):
        """Return plate results for the current frame."""
        return self.plate_results

    def add_plate_result(self, plate_text, confidence, bbox):
        """Record a plate reading for the current frame and append to the running log."""
        entry = {
            "plate_text": plate_text,
            "confidence": confidence,
            "bbox": bbox,
            "timestamp": datetime.now().isoformat(),
        }
        self.plate_results.append(entry)
        self.plate_log.append(entry)

        # Write to CSV if logging is enabled
        if self._csv_writer is not None:
            self._csv_writer.writerow(
                [entry["timestamp"], plate_text, f"{confidence:.4f}"]
            )
            self._csv_file.flush()

    def clear_plate_results(self):
        """Clear the per-frame plate results (called at the start of each frame)."""
        self.plate_results.clear()

    def get_plate_log(self):
        """Return the full running log of all plates seen."""
        return self.plate_log

    def close(self):
        """Clean up the CSV log file handle."""
        if self._csv_file is not None:
            self._csv_file.close()
            self._csv_file = None
            self._csv_writer = None


# -----------------------------------------------------------------------------------------------
# User-defined callback function
# -----------------------------------------------------------------------------------------------


def app_callback(element, buffer, user_data):
    """Process each frame: extract plate detections, read OCR text, log results."""
    if buffer is None:
        hailo_logger.warning("Received None buffer.")
        return

    # Get video format and dimensions from pad caps
    pad = element.get_static_pad("src")
    format, width, height = get_caps_from_pad(pad)

    # Get current frame index
    frame_idx = user_data.get_count()
    hailo_logger.debug("Frame=%s | caps fmt=%s %sx%s", frame_idx, format, width, height)
    string_to_print = f"Frame count: {user_data.get_count()}\n"

    # Clear previous frame results
    user_data.clear_plate_results()

    # Get detections from the buffer
    roi = hailo.get_roi_from_buffer(buffer)
    text_detections = roi.get_objects_typed(hailo.HAILO_DETECTION)

    # Parse the plate detections
    plate_count = 0
    for detection in text_detections:
        label = detection.get_label()
        bbox = detection.get_bbox()
        confidence = detection.get_confidence()

        # OCR detection uses "text_region" label; filter by confidence
        if label == "text_region" and confidence > 0.12:
            # Get recognized text from the recognition stage
            plate_text = ""
            ocr_objects = detection.get_objects_typed(hailo.HAILO_CLASSIFICATION)
            if len(ocr_objects) > 0:
                for cls in ocr_objects:
                    if cls.get_classification_type() == "text_region":
                        plate_text = cls.get_label()
                        break
                if not plate_text and len(ocr_objects) > 0:
                    plate_text = ocr_objects[0].get_label()

            # Only record non-empty plate readings
            if plate_text and plate_text.strip():
                user_data.add_plate_result(plate_text.strip(), confidence, bbox)
                string_to_print += (
                    f"Plate: '{plate_text.strip()}' (conf={confidence:.2f})\n"
                )
                plate_count += 1

    # Optional: draw results in a separate OpenCV window when use_frame=True
    if user_data.use_frame and format is not None and width is not None and height is not None:
        frame = get_numpy_from_buffer(buffer, format, width, height)

        if frame is not None:
            plate_results = user_data.get_plate_results()

            for result in plate_results:
                bbox = result["bbox"]
                plate_text = result["plate_text"]
                confidence = result["confidence"]

                # Convert normalized bbox to pixel coordinates
                x1 = max(0, min(int(bbox.xmin() * width), width - 1))
                y1 = max(0, min(int(bbox.ymin() * height), height - 1))
                x2 = max(0, min(int((bbox.xmin() + bbox.width()) * width), width - 1))
                y2 = max(0, min(int((bbox.ymin() + bbox.height()) * height), height - 1))

                # Draw bounding box in green
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)

                # Draw plate text above the box
                text_label = f"{plate_text} ({confidence:.2f})"
                text_y = max(15, y1 - 10)
                cv2.putText(
                    frame,
                    text_label,
                    (x1, text_y),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 255, 0),
                    2,
                )

            # Show plate count
            cv2.putText(
                frame,
                f"Plates: {plate_count}",
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (0, 255, 0),
                2,
            )

            # Convert RGB -> BGR for OpenCV display
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            user_data.set_frame(frame)
        else:
            hailo_logger.warning("Failed to extract frame from buffer.")

    # Print immediately when new plates are detected, otherwise throttle to every 30 frames
    if plate_count > 0 or frame_idx % 30 == 0:
        print(string_to_print)
    return


def main():
    import argparse

    hailo_logger.info("Starting License Plate Reader App.")

    # Parse app-specific arguments
    parser = argparse.ArgumentParser(
        description="License Plate Reader - Detect and read license plates in video",
        add_help=False,  # Let the pipeline parser handle --help
    )
    parser.add_argument(
        "--plate-log",
        type=str,
        default=None,
        help="Path to CSV file for logging recognized plates with timestamps",
    )
    args, remaining = parser.parse_known_args()

    user_data = PlateReaderCallbackData(log_file=args.plate_log)
    try:
        app = GStreamerLicensePlateReaderApp(app_callback, user_data)
        app.run()
    finally:
        user_data.close()


if __name__ == "__main__":
    main()
