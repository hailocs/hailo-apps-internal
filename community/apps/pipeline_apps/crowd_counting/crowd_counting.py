# region imports
# Standard library imports
import os
os.environ["GST_PLUGIN_FEATURE_RANK"] = "vaapidecodebin:NONE"

# Third-party imports
import gi

gi.require_version("Gst", "1.0")
import cv2

# Local application-specific imports
import hailo
from gi.repository import Gst

from community.apps.pipeline_apps.crowd_counting.crowd_counting_pipeline import (
    GStreamerCrowdCountingApp,
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
class CrowdCountingCallbackData(app_callback_class):
    """
    Maintains state for line-crossing counting across frames.

    Tracks individual persons by their tracker ID and detects when they
    cross a virtual horizontal line. Crossing direction (left-to-right
    vs right-to-left) is determined by comparing the person's vertical
    center position relative to the line across consecutive frames.

    Note: "left-to-right" and "right-to-left" in this context refer to
    crossing the horizontal line from top-to-bottom and bottom-to-top
    respectively, which maps to physical left/right movement when the
    camera views a corridor or entrance from above or at an angle.
    Adjust the line_y parameter to place the virtual line.
    """

    def __init__(self, line_y=0.5):
        super().__init__()
        # Virtual line Y-position (normalized 0.0-1.0)
        self.line_y = line_y
        # Track previous Y-center positions per track ID
        self.prev_positions = {}
        # Crossing counts
        self.count_left_to_right = 0  # crossing line downward (top -> bottom)
        self.count_right_to_left = 0  # crossing line upward (bottom -> top)
        # Set of track IDs that have already been counted (avoid double-counting)
        self.counted_ids = set()


# -----------------------------------------------------------------------------------------------
# User-defined callback function
# -----------------------------------------------------------------------------------------------


def app_callback(element, buffer, user_data):
    """
    Callback invoked on every frame. Extracts person detections, checks
    if any tracked person crosses the virtual line, and updates counts.

    The virtual line is horizontal at y = user_data.line_y (normalized).
    - A person moving from above the line to below it is counted as L->R.
    - A person moving from below the line to above it is counted as R->L.

    When --use-frame is enabled, the callback also draws:
    - The virtual counting line (red horizontal line)
    - Crossing counts overlay text
    - Direction indicators near recent crossings
    """
    if buffer is None:
        hailo_logger.warning("Received None buffer.")
        return

    frame_idx = user_data.get_count()
    line_y = user_data.line_y

    pad = element.get_static_pad("src")
    format, width, height = get_caps_from_pad(pad)

    frame = None
    if user_data.use_frame and format is not None and width is not None and height is not None:
        frame = get_numpy_from_buffer(buffer, format, width, height)

    roi = hailo.get_roi_from_buffer(buffer)
    detections = roi.get_objects_typed(hailo.HAILO_DETECTION)

    # Collect current frame's person positions by track ID
    current_positions = {}
    for detection in detections:
        label = detection.get_label()
        if label != "person":
            continue

        # Get track ID
        track_id = 0
        track = detection.get_objects_typed(hailo.HAILO_UNIQUE_ID)
        if len(track) == 1:
            track_id = track[0].get_id()

        if track_id == 0:
            continue  # Skip untracked detections

        # Compute the vertical center of the bounding box (normalized 0-1)
        bbox = detection.get_bbox()
        y_center = bbox.ymin() + bbox.height() / 2.0
        current_positions[track_id] = y_center

    # Check for line crossings
    for track_id, y_center in current_positions.items():
        if track_id in user_data.counted_ids:
            continue  # Already counted this person

        if track_id in user_data.prev_positions:
            prev_y = user_data.prev_positions[track_id]

            # Check if the person crossed the line between previous and current frame
            if prev_y < line_y <= y_center:
                # Crossed downward (top to bottom) => L->R
                user_data.count_left_to_right += 1
                user_data.counted_ids.add(track_id)
                hailo_logger.info(
                    "L->R crossing detected: ID=%d (y: %.3f -> %.3f)",
                    track_id, prev_y, y_center,
                )
            elif prev_y > line_y >= y_center:
                # Crossed upward (bottom to top) => R->L
                user_data.count_right_to_left += 1
                user_data.counted_ids.add(track_id)
                hailo_logger.info(
                    "R->L crossing detected: ID=%d (y: %.3f -> %.3f)",
                    track_id, prev_y, y_center,
                )

    # Update previous positions for the next frame
    user_data.prev_positions = current_positions

    # Clean up counted IDs for tracks that are no longer visible
    active_ids = set(current_positions.keys())
    user_data.counted_ids = user_data.counted_ids.intersection(active_ids)

    # Print status periodically
    if frame_idx % 30 == 0:
        total = user_data.count_left_to_right + user_data.count_right_to_left
        print(
            f"Frame {frame_idx} | "
            f"L->R: {user_data.count_left_to_right} | "
            f"R->L: {user_data.count_right_to_left} | "
            f"Total: {total} | "
            f"Active tracks: {len(current_positions)}"
        )

    # Draw overlay if --use-frame is enabled
    if user_data.use_frame and frame is not None and width is not None and height is not None:
        # Draw the virtual counting line (red)
        line_pixel_y = int(line_y * height)
        cv2.line(frame, (0, line_pixel_y), (width, line_pixel_y), (255, 0, 0), 2)

        # Draw crossing counts
        total = user_data.count_left_to_right + user_data.count_right_to_left
        cv2.putText(
            frame,
            f"L->R: {user_data.count_left_to_right}",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 255, 0),
            2,
        )
        cv2.putText(
            frame,
            f"R->L: {user_data.count_right_to_left}",
            (10, 60),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 0, 255),
            2,
        )
        cv2.putText(
            frame,
            f"Total: {total}",
            (10, 90),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 255),
            2,
        )

        # Draw direction indicators near the line
        cv2.putText(
            frame,
            "v L->R",
            (width - 150, line_pixel_y - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 255, 0),
            1,
        )
        cv2.putText(
            frame,
            "^ R->L",
            (width - 150, line_pixel_y + 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 0, 255),
            1,
        )

        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        user_data.set_frame(frame)

    return


def main():
    hailo_logger.info("Starting Crowd Counting App.")
    # Create user_data with default line_y; will be updated after arg parsing
    user_data = CrowdCountingCallbackData()
    # GStreamerCrowdCountingApp owns --labels-json and --line-y arg definitions
    app = GStreamerCrowdCountingApp(app_callback, user_data)
    # Update line_y from the parsed arguments
    user_data.line_y = app.options_menu.line_y
    app.run()


if __name__ == "__main__":
    main()
