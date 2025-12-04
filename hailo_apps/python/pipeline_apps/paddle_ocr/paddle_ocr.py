# region imports
# Standard library imports

# Third-party imports
import gi

gi.require_version("Gst", "1.0")
import cv2

# Local application-specific imports
import hailo
from gi.repository import Gst

from hailo_apps.python.pipeline_apps.paddle_ocr.paddle_ocr_pipeline import GStreamerOCRApp
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
# Inheritance from the app_callback_class
class user_app_callback_class(app_callback_class):
    def __init__(self):
        super().__init__()
        self.ocr_results = []  # Store OCR results

    def get_ocr_results(self):
        return self.ocr_results

    def add_ocr_result(self, text, confidence, bbox):
        self.ocr_results.append({
            'text': text,
            'confidence': confidence,
            'bbox': bbox
        })

    def clear_ocr_results(self):
        self.ocr_results.clear()


# -----------------------------------------------------------------------------------------------
# User-defined callback function
# -----------------------------------------------------------------------------------------------


# This is the callback function that will be called when data is available from the pipeline
def app_callback(pad, info, user_data):
    # Get the GstBuffer from the probe info
    buffer = info.get_buffer()
    # Check if the buffer is valid
    if buffer is None:
        hailo_logger.warning("Received None buffer | frame=%s", user_data.get_count())
        return Gst.PadProbeReturn.OK

    # Get video format and dimensions from pad caps
    format, width, height = get_caps_from_pad(pad)
    
    # Using the user_data to count the number of frames
    user_data.increment()
    frame_idx = user_data.get_count()
    hailo_logger.debug("Frame=%s | caps fmt=%s %sx%s", frame_idx, format, width, height)
    string_to_print = f"Frame count: {user_data.get_count()}\n"

    # Clear previous OCR results
    user_data.clear_ocr_results()

    # Get the OCR results from the buffer
    roi = hailo.get_roi_from_buffer(buffer)
    text_detections = roi.get_objects_typed(hailo.HAILO_DETECTION)

    # Parse the OCR detections
    text_count = 0
    for detection in text_detections:
        label = detection.get_label()
        bbox = detection.get_bbox()
        confidence = detection.get_confidence()
        
        # Check for text regions (OCR detection uses "text_region" label)
        # Use confidence threshold 0.12 to match C++ postprocess code (MIN_CONFIDENCE)
        # Note: Classifications should be added in postprocess
        if label == "text_region" and confidence > 0.12:
            # Get OCR text result if available (from recognition stage)
            text_result = ""
            ocr_objects = detection.get_objects_typed(hailo.HAILO_CLASSIFICATION)
            if len(ocr_objects) > 0:
                # Try to find classification with type "text_region", otherwise use first one
                for cls in ocr_objects:
                    if cls.get_classification_type() == "text_region":
                        text_result = cls.get_label()
                        break
                if not text_result and len(ocr_objects) > 0:
                    text_result = ocr_objects[0].get_label()
            
            # Filter out empty text results - only store and display non-empty text
            # Empty text usually indicates recognition failed or detection was false positive
            if text_result and text_result.strip():
                # Store OCR result
                user_data.add_ocr_result(text_result, confidence, bbox)
                
                string_to_print += (
                    f"OCR Detection: Text: '{text_result}' Confidence: {confidence:.2f}\n"
                )
                hailo_logger.debug(
                    "Frame=%s | OCR text='%s' conf=%.2f bbox=(x=%.1f,y=%.1f,w=%.1f,h=%.1f)",
                    frame_idx,
                    text_result,
                    confidence,
                    bbox.xmin(),
                    bbox.ymin(),
                    bbox.width(),
                    bbox.height(),
                )
                text_count += 1
            else:
                # Log skipped detections with empty text for debugging
                hailo_logger.debug(
                    "Frame=%s | Skipped detection with empty text | conf=%.2f bbox=(x=%.1f,y=%.1f,w=%.1f,h=%.1f)",
                    frame_idx,
                    confidence,
                    bbox.xmin(),
                    bbox.ymin(),
                    bbox.width(),
                    bbox.height(),
                )

    # Extract frame from buffer right before drawing to ensure we have the latest frame
    # Note: This drawing is for the separate window when use_frame=True
    # The main GStreamer display uses hailooverlay which draws from detection metadata automatically
    if user_data.use_frame and format is not None and width is not None and height is not None:
        # Get video frame from the current buffer (extract fresh for each frame)
        frame = get_numpy_from_buffer(buffer, format, width, height)
        
        if frame is not None:
            hailo_logger.debug("Frame extracted: shape=%s, dtype=%s", frame.shape, frame.dtype)
            
            # Draw OCR results on frame
            ocr_results = user_data.get_ocr_results()
            hailo_logger.debug("Drawing %d OCR results on frame", len(ocr_results))
            
            for idx, ocr_result in enumerate(ocr_results):
                bbox = ocr_result['bbox']
                text = ocr_result['text']
                confidence = ocr_result['confidence']
                
                # Draw bounding box (use video dimensions from caps)
                x1 = int(bbox.xmin() * width)
                y1 = int(bbox.ymin() * height)
                x2 = int((bbox.xmin() + bbox.width()) * width)
                y2 = int((bbox.ymin() + bbox.height()) * height)
                
                # Ensure coordinates are within frame bounds
                x1 = max(0, min(x1, width - 1))
                y1 = max(0, min(y1, height - 1))
                x2 = max(0, min(x2, width - 1))
                y2 = max(0, min(y2, height - 1))
                
                hailo_logger.debug("Drawing box %d: text='%s' at (%d,%d)-(%d,%d)", 
                                 idx, text, x1, y1, x2, y2)
                
                # Draw bounding box (BGR color: green)
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                
                # Draw text result (ensure text position is within frame)
                text_label = f"{text} ({confidence:.2f})"
                text_y = max(15, y1 - 10)  # Ensure text is visible above box
                cv2.putText(
                    frame,
                    text_label,
                    (x1, text_y),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (0, 255, 0),
                    1,
                )

            # Display total text count
            cv2.putText(
                frame,
                f"Text Regions: {text_count}",
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (0, 255, 0),
                2,
            )
            
            # Convert the frame to BGR for OpenCV display (frame is RGB from buffer)
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            user_data.set_frame(frame)
            hailo_logger.debug("Frame set in user_data with %d OCR results drawn", len(ocr_results))
        else:
            hailo_logger.warning("Failed to extract frame from buffer")

    print(string_to_print)
    hailo_logger.info(string_to_print.strip())
    return Gst.PadProbeReturn.OK


def main():
    # Create an instance of the user app callback class
    hailo_logger.info("Starting Hailo OCR App...")
    user_data = user_app_callback_class()
    app = GStreamerOCRApp(app_callback, user_data)
    app.run()


if __name__ == "__main__":
    main()

