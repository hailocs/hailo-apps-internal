# region imports
# Standard library imports
import os
import time

os.environ["GST_PLUGIN_FEATURE_RANK"] = "vaapidecodebin:NONE"

# Third-party imports
import gi

gi.require_version("Gst", "1.0")
# Local application-specific imports
import hailo
import numpy as np
from gi.repository import Gst

from community.apps.pipeline_apps.depth_proximity_alert.depth_proximity_alert_pipeline import (
    GStreamerDepthProximityAlertApp,
)

from hailo_apps.python.core.common.hailo_logger import (
    get_logger,
)
from hailo_apps.python.core.gstreamer.gstreamer_app import app_callback_class

hailo_logger = get_logger(__name__)
# endregion imports

# Alert cooldown in seconds to avoid spamming
ALERT_COOLDOWN_SECONDS = 1.0


class ProximityAlertCallback(app_callback_class):
    """Callback class for depth-based proximity alerting.

    Maintains state across frames for alert logic, including:
    - Proximity threshold (configurable via CLI)
    - Region of interest for depth analysis
    - Alert cooldown to avoid excessive warnings
    - Running statistics for depth values
    """

    def __init__(self, proximity_threshold=0.3, alert_region=None):
        super().__init__()
        self.proximity_threshold = proximity_threshold
        # alert_region: (x, y, w, h) normalized [0,1] or None for center 50%
        self.alert_region = alert_region
        self.last_alert_time = 0.0
        self.alert_active = False
        self.min_depth_history = []
        self.history_max_len = 10  # Smoothing window

    def get_region_depth(self, depth_data):
        """Extract depth values from the region of interest.

        Args:
            depth_data: 2D numpy array of depth values from the depth mask.

        Returns:
            numpy array of depth values within the region of interest.
        """
        depth_array = np.array(depth_data)
        if depth_array.ndim < 2:
            return depth_array.flatten()

        h, w = depth_array.shape[:2]

        if self.alert_region is not None:
            rx, ry, rw, rh = self.alert_region
            x1 = int(rx * w)
            y1 = int(ry * h)
            x2 = int((rx + rw) * w)
            y2 = int((ry + rh) * h)
        else:
            # Default: center 50% of the frame
            x1 = w // 4
            y1 = h // 4
            x2 = 3 * w // 4
            y2 = 3 * h // 4

        # Clamp to valid range
        x1 = max(0, min(x1, w - 1))
        y1 = max(0, min(y1, h - 1))
        x2 = max(x1 + 1, min(x2, w))
        y2 = max(y1 + 1, min(y2, h))

        region = depth_array[y1:y2, x1:x2]
        return region.flatten()

    def check_proximity(self, depth_values):
        """Check if any significant portion of the ROI is within the proximity threshold.

        Uses the 5th percentile of depth values (closest objects) and smooths
        over recent frames to reduce noise.

        Args:
            depth_values: 1D numpy array of depth values in the region of interest.

        Returns:
            tuple: (is_alert, min_depth_smoothed, current_min_depth)
        """
        if len(depth_values) == 0:
            return False, 0.0, 0.0

        # Use 5th percentile as the "closest object" depth to reduce noise
        try:
            current_min_depth = float(np.percentile(depth_values, 5))
        except Exception:
            hailo_logger.exception("Percentile computation failed.")
            return False, 0.0, 0.0

        # Smooth over recent frames
        self.min_depth_history.append(current_min_depth)
        if len(self.min_depth_history) > self.history_max_len:
            self.min_depth_history.pop(0)

        smoothed_min_depth = float(np.mean(self.min_depth_history))

        is_alert = smoothed_min_depth <= self.proximity_threshold
        return is_alert, smoothed_min_depth, current_min_depth

    def calculate_average_depth(self, depth_mat):
        """Calculate average depth, dropping top 5% outliers.

        Args:
            depth_mat: Raw depth data from HAILO_DEPTH_MASK.

        Returns:
            float: Average depth value.
        """
        depth_values = np.array(depth_mat).flatten()
        try:
            m_depth_values = depth_values[
                depth_values <= np.percentile(depth_values, 95)
            ]
        except Exception:
            hailo_logger.exception("Percentile computation failed; treating as empty depth set.")
            m_depth_values = np.array([])
        if len(m_depth_values) > 0:
            return float(np.mean(m_depth_values))
        return 0.0


def app_callback(element, buffer, user_data):
    """Callback invoked per frame with depth estimation results.

    Analyzes the depth map, checks for proximity alerts, and prints
    status information including alert state and depth statistics.
    """
    if buffer is None:
        hailo_logger.warning("Received None buffer at frame=%s", user_data.get_count())
        return

    roi = hailo.get_roi_from_buffer(buffer)
    depth_masks = roi.get_objects_typed(hailo.HAILO_DEPTH_MASK)

    if len(depth_masks) == 0:
        return

    depth_data = depth_masks[0].get_data()

    # Get depth values in the region of interest
    region_depth = user_data.get_region_depth(depth_data)

    # Check proximity
    is_alert, smoothed_depth, current_depth = user_data.check_proximity(region_depth)

    # Calculate overall average depth for display
    average_depth = user_data.calculate_average_depth(depth_data)

    # Build status string
    frame_count = user_data.get_count()
    status_lines = [
        f"Frame: {frame_count}",
        f"Avg depth: {average_depth:.3f}",
        f"Closest (smoothed): {smoothed_depth:.3f}",
        f"Threshold: {user_data.proximity_threshold:.3f}",
    ]

    # Alert logic with cooldown
    now = time.monotonic()
    if is_alert:
        if not user_data.alert_active or (now - user_data.last_alert_time) >= ALERT_COOLDOWN_SECONDS:
            status_lines.append("** PROXIMITY ALERT! Object too close! **")
            user_data.last_alert_time = now
            user_data.alert_active = True
            hailo_logger.warning(
                "PROXIMITY ALERT at frame %d: smoothed_depth=%.3f, threshold=%.3f",
                frame_count,
                smoothed_depth,
                user_data.proximity_threshold,
            )
    else:
        if user_data.alert_active:
            status_lines.append("Alert cleared.")
            hailo_logger.info("Proximity alert cleared at frame %d", frame_count)
        user_data.alert_active = False

    if frame_count % 30 == 0:
        print("\n".join(status_lines))
        print()

    return


def main():
    hailo_logger.info("Starting Depth Proximity Alert App.")

    # Create the pipeline app (which parses CLI args)
    # We need to parse args first to get proximity_threshold and alert_region
    from hailo_apps.python.core.common.core import get_pipeline_parser

    parser = get_pipeline_parser()
    parser.add_argument(
        "--proximity-threshold",
        type=float,
        default=0.3,
        help="Depth threshold for proximity alert (0.0-1.0, lower = closer). Default: 0.3",
    )
    parser.add_argument(
        "--alert-region",
        type=float,
        nargs=4,
        default=None,
        metavar=("X", "Y", "W", "H"),
        help="Region of interest for proximity detection as normalized coords (x y w h). "
             "Default: center 50%% of frame.",
    )

    # Pre-parse to get our custom args
    args, _ = parser.parse_known_args()

    user_data = ProximityAlertCallback(
        proximity_threshold=args.proximity_threshold,
        alert_region=args.alert_region,
    )
    app = GStreamerDepthProximityAlertApp(app_callback, user_data, parser=parser)
    app.run()


if __name__ == "__main__":
    main()
