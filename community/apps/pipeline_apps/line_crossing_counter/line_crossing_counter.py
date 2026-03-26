# region imports
# Standard library imports
import os
os.environ["GST_PLUGIN_FEATURE_RANK"] = "vaapidecodebin:NONE"

from collections import deque

# Third-party imports
import gi

gi.require_version("Gst", "1.0")
import cv2

# Local application-specific imports
import hailo
from gi.repository import Gst

from community.apps.pipeline_apps.line_crossing_counter.line_crossing_counter_pipeline import (
    GStreamerLineCrossingCounterApp,
)
from hailo_apps.python.core.common.buffer_utils import (
    get_caps_from_pad,
    get_numpy_from_buffer,
)

from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.gstreamer.gstreamer_app import app_callback_class

hailo_logger = get_logger(__name__)
# endregion imports

# Number of recent x_center samples to average for position smoothing
SMOOTHING_WINDOW = 5


# -----------------------------------------------------------------------------------------------
# Per-track state for zone-based line crossing
# -----------------------------------------------------------------------------------------------
class TrackState:
    """State for a single tracked person in the counting zone."""

    def __init__(self):
        self.entry_side = None   # "left" or "right" — which side they entered from
        self.x_history = deque(maxlen=SMOOTHING_WINDOW)  # recent x_center values

    def smoothed_x(self):
        """Return averaged x_center over recent frames to reduce noise."""
        if not self.x_history:
            return None
        return sum(self.x_history) / len(self.x_history)


# -----------------------------------------------------------------------------------------------
# User-defined class to be used in the callback function
# -----------------------------------------------------------------------------------------------
class LineCrossingCallbackData(app_callback_class):
    """
    Maintains state for zone-based line-crossing counting across frames.

    A vertical counting line is placed at line_x, with a zone of width
    zone_width centered on it: [line_x - margin, line_x + margin].

    Logic:
      1. When a person's bbox center enters the zone, record which side
         of the center line they are on (entry_side = "left" or "right").
      2. Each frame while in the zone, update position history for smoothing.
      3. When the person's center exits the zone:
         - Opposite side from entry → count the crossing.
         - Same side as entry → ignore (person turned back).
      4. After exiting the zone, state resets — the person can be counted
         again if they re-enter the zone.
      5. When the tracker loses the person, clean up their state.
    """

    def __init__(self, line_x=0.5, zone_width=0.1):
        super().__init__()
        self.line_x = line_x
        self.zone_width = zone_width
        # Per-track state: {track_id: TrackState}
        self.tracks = {}
        # Crossing counts
        self.count_left_to_right = 0
        self.count_right_to_left = 0

    @property
    def zone_left(self):
        """Left boundary of the counting zone."""
        return max(0.0, self.line_x - self.zone_width / 2.0)

    @property
    def zone_right(self):
        """Right boundary of the counting zone."""
        return min(1.0, self.line_x + self.zone_width / 2.0)


# -----------------------------------------------------------------------------------------------
# User-defined callback function
# -----------------------------------------------------------------------------------------------


def app_callback(element, buffer, user_data):
    """
    Callback invoked on every frame. Uses zone-based line crossing detection.

    A counting zone spans [line_x - margin, line_x + margin]. Tracking starts
    when a person's bbox center enters the zone. Entry side is recorded based
    on which side of the center line they are on. A crossing is counted when
    the person exits the zone from the opposite side. Position is smoothed
    over multiple frames to reduce noisy detections.

    When --use-frame is enabled, the callback draws:
    - The counting zone (semi-transparent band) with the center line
    - Crossing counts overlay text
    - Direction indicators
    """
    if buffer is None:
        hailo_logger.warning("Received None buffer.")
        return

    frame_idx = user_data.get_count()
    zone_left = user_data.zone_left
    zone_right = user_data.zone_right
    line_x = user_data.line_x

    pad = element.get_static_pad("src")
    format, width, height = get_caps_from_pad(pad)

    frame = None
    if user_data.use_frame and format is not None and width is not None and height is not None:
        frame = get_numpy_from_buffer(buffer, format, width, height)

    roi = hailo.get_roi_from_buffer(buffer)
    detections = roi.get_objects_typed(hailo.HAILO_DETECTION)

    # Process each tracked person
    current_ids = set()
    draw_info = []  # Collected per-person drawing data: (bbox, x_center, y_center, track_id, state)
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

        current_ids.add(track_id)

        # Compute the horizontal center of the bounding box (normalized 0-1)
        bbox = detection.get_bbox()
        x_center = bbox.xmin() + bbox.width() / 2.0
        y_center = bbox.ymin() + bbox.height() / 2.0

        # Get or create per-track state
        if track_id not in user_data.tracks:
            user_data.tracks[track_id] = TrackState()
        ts = user_data.tracks[track_id]

        # Add current position to history for smoothing
        ts.x_history.append(x_center)
        smoothed = ts.smoothed_x()

        in_zone = zone_left <= smoothed <= zone_right

        if in_zone:
            # Person is inside the zone
            if ts.entry_side is None:
                # First time entering the zone — record which side of the line
                ts.entry_side = "left" if smoothed < line_x else "right"
                hailo_logger.debug(
                    "ID=%d entered zone from %s (x=%.3f)",
                    track_id, ts.entry_side, smoothed,
                )
        else:
            # Person is outside the zone
            if ts.entry_side is not None:
                # They were in the zone before — check which side they exited
                exited_left = smoothed < zone_left
                exited_right = smoothed > zone_right

                if ts.entry_side == "left" and exited_right:
                    # Entered from left, exited right → L->R crossing
                    user_data.count_left_to_right += 1
                    hailo_logger.info(
                        "L->R crossing: ID=%d (exited right, x=%.3f)",
                        track_id, smoothed,
                    )
                elif ts.entry_side == "right" and exited_left:
                    # Entered from right, exited left → R->L crossing
                    user_data.count_right_to_left += 1
                    hailo_logger.info(
                        "R->L crossing: ID=%d (exited left, x=%.3f)",
                        track_id, smoothed,
                    )

                # Reset state regardless of direction — person left the zone,
                # ready to be counted again if they re-enter
                ts.entry_side = None
                ts.x_history.clear()

        # Collect drawing info for overlay
        draw_info.append((bbox, x_center, y_center, track_id, ts.entry_side))

    # Clean up state for tracks that are no longer visible
    stale_ids = set(user_data.tracks.keys()) - current_ids
    for tid in stale_ids:
        del user_data.tracks[tid]

    # Print status periodically
    if frame_idx % 30 == 0:
        total = user_data.count_left_to_right + user_data.count_right_to_left
        in_zone_count = sum(
            1 for ts in user_data.tracks.values()
            if ts.entry_side is not None
        )
        print(
            f"Frame {frame_idx} | "
            f"L->R: {user_data.count_left_to_right} | "
            f"R->L: {user_data.count_right_to_left} | "
            f"Total: {total} | "
            f"In zone: {in_zone_count} | "
            f"Tracked: {len(current_ids)}"
        )

    # Draw overlay if --use-frame is enabled
    if user_data.use_frame and frame is not None and width is not None and height is not None:
        line_pixel_x = int(line_x * width)
        zone_left_px = int(zone_left * width)
        zone_right_px = int(zone_right * width)

        # Draw semi-transparent zone band
        overlay = frame.copy()
        cv2.rectangle(overlay, (zone_left_px, 0), (zone_right_px, height), (200, 200, 0), -1)
        cv2.addWeighted(overlay, 0.15, frame, 0.85, 0, frame)

        # Draw zone boundaries
        cv2.line(frame, (zone_left_px, 0), (zone_left_px, height), (150, 150, 0), 1)
        cv2.line(frame, (zone_right_px, 0), (zone_right_px, height), (150, 150, 0), 1)

        # Draw center counting line (red, vertical)
        cv2.line(frame, (line_pixel_x, 0), (line_pixel_x, height), (0, 0, 255), 2)

        # Draw crossing counts
        total = user_data.count_left_to_right + user_data.count_right_to_left
        cv2.putText(
            frame, f"L->R: {user_data.count_left_to_right}",
            (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2,
        )
        cv2.putText(
            frame, f"R->L: {user_data.count_right_to_left}",
            (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2,
        )
        cv2.putText(
            frame, f"Total: {total}",
            (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2,
        )

        # Draw direction indicators outside the zone
        cv2.putText(
            frame, "L->R ->",
            (zone_right_px + 10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1,
        )
        cv2.putText(
            frame, "<- R->L",
            (zone_left_px - 120, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1,
        )

        # Draw bboxes and center points for tracked persons
        for bbox, cx, cy, tid, entry_side in draw_info:
            # Convert normalized coords to pixels
            x1 = int(bbox.xmin() * width)
            y1 = int(bbox.ymin() * height)
            x2 = int((bbox.xmin() + bbox.width()) * width)
            y2 = int((bbox.ymin() + bbox.height()) * height)
            cx_px = int(cx * width)
            cy_px = int(cy * height)

            # Color based on state: green=in zone, white=outside, yellow=entering
            if entry_side == "left":
                color = (0, 255, 0)   # green — entered from left
            elif entry_side == "right":
                color = (0, 165, 255)  # orange — entered from right
            else:
                color = (200, 200, 200)  # gray — not in zone

            # Bounding box
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

            # Center point
            cv2.circle(frame, (cx_px, cy_px), 5, color, -1)

            # Track ID label above bbox
            label_text = f"ID:{tid}"
            if entry_side:
                label_text += f" [{entry_side[0].upper()}]"
            cv2.putText(
                frame, label_text,
                (x1, max(15, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1,
            )

        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        user_data.set_frame(frame)

    return


def main():
    hailo_logger.info("Starting Line Crossing Counter App.")
    user_data = LineCrossingCallbackData()
    user_data.window_title = "Line Crossing Counter"
    app = GStreamerLineCrossingCounterApp(app_callback, user_data)
    user_data.line_x = app.options_menu.line_x
    user_data.zone_width = app.options_menu.zone_width
    app.run()


if __name__ == "__main__":
    main()
