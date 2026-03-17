"""
Lane departure warning utilities.

Extends UFLDProcessing from lane_detection with departure detection logic.
Analyzes lane positions relative to frame center to determine if the vehicle
is drifting out of its lane.
"""

import sys
from pathlib import Path
from math import hypot
import numpy as np
import cv2

try:
    from hailo_apps.python.core.common.hailo_logger import get_logger
except ImportError:
    core_dir = Path(__file__).resolve().parents[2] / "core"
    sys.path.insert(0, str(core_dir))
    from common.hailo_logger import get_logger

logger = get_logger(__name__)


class UFLDProcessing:
    """UFLD v2 lane detection preprocessing and postprocessing."""

    def __init__(self,
                 num_cell_row,
                 num_cell_col,
                 num_row,
                 num_col,
                 num_lanes,
                 crop_ratio,
                 original_frame_width,
                 original_frame_height,
                 total_frames):
        self.num_cell_row = num_cell_row
        self.num_cell_col = num_cell_col
        self.num_row = num_row
        self.num_col = num_col
        self.num_lanes = num_lanes
        self.crop_ratio = crop_ratio
        self.original_frame_width = original_frame_width
        self.original_frame_height = original_frame_height
        self.total_frames = total_frames

    def resize(self, image, input_height, input_width):
        """Resize and crop an image for UFLD v2 input."""
        new_height = int(input_height / self.crop_ratio)
        image_resized = cv2.resize(image, (input_width, new_height),
                                   interpolation=cv2.INTER_CUBIC)
        image_resized = image_resized[-320:, :, :]
        return image_resized

    def _soft_max(self, z):
        """Compute softmax for a given array."""
        t = np.exp(z)
        a = np.exp(z) / np.sum(t)
        return a

    def _slice_and_reshape(self, output):
        """Slice and reshape the output tensor into row/col localization and existence."""
        dim1 = self.num_cell_row * self.num_row * self.num_lanes
        dim2 = self.num_cell_col * self.num_col * self.num_lanes
        dim3 = 2 * self.num_row * self.num_lanes
        dim4 = 2 * self.num_col * self.num_lanes

        loc_row = np.reshape(output[:, :dim1],
                             (-1, self.num_cell_row, self.num_row, self.num_lanes))
        loc_col = np.reshape(output[:, dim1:dim1 + dim2],
                             (-1, self.num_cell_col, self.num_col, self.num_lanes))
        exist_row = np.reshape(output[:, dim1 + dim2:dim1 + dim2 + dim3],
                               (-1, 2, self.num_row, self.num_lanes))
        exist_col = np.reshape(output[:, -dim4:],
                               (-1, 2, self.num_col, self.num_lanes))
        return loc_row, loc_col, exist_row, exist_col

    def _pred2coords(self, loc_row, loc_col, exist_row, exist_col, local_width=1):
        """Convert prediction data to lane coordinates."""
        row_anchor = np.linspace(160, 710, 56) / 720
        col_anchor = np.linspace(0, 1, 41)
        _, num_grid_row, num_cls_row, _ = loc_row.shape
        _, num_grid_col, num_cls_col, _ = loc_col.shape
        max_indices_row = np.argmax(loc_row, 1)
        valid_row = np.argmax(exist_row, 1)
        max_indices_col = np.argmax(loc_col, 1)
        valid_col = np.argmax(exist_col, 1)
        coords = []
        row_lane_idx = [1, 2]
        col_lane_idx = [0, 3]
        for i in row_lane_idx:
            tmp = []
            valid_row_sum = np.sum(valid_row[0, :, i])
            if valid_row_sum > num_cls_row / 2:
                for k in range(valid_row.shape[1]):
                    if valid_row[0, k, i]:
                        all_ind_min = max(0, max_indices_row[0, k, i] - local_width)
                        all_ind_max = min(num_grid_row - 1,
                                          max_indices_row[0, k, i] + local_width) + 1
                        all_ind = list(range(all_ind_min, all_ind_max))
                        row_softmax = self._soft_max(
                            loc_row[0, all_ind_min:all_ind_max, k, i])
                        out_tmp = np.sum(row_softmax * all_ind) + 0.5
                        out_tmp = out_tmp / (num_grid_row - 1) * self.original_frame_width
                        tmp.append((int(out_tmp),
                                    int(row_anchor[k] * self.original_frame_height)))
                coords.append(tmp)
        for i in col_lane_idx:
            tmp = []
            valid_col_sum = np.sum(valid_col[0, :, i])
            if valid_col_sum > (num_cls_col / 4):
                for k in range(valid_col.shape[1]):
                    if valid_col[0, k, i]:
                        all_ind_min = max(0, max_indices_col[0, k, i] - local_width)
                        all_ind_max = min(num_grid_col - 1,
                                          max_indices_col[0, k, i] + local_width) + 1
                        all_ind = range(all_ind_min, all_ind_max)
                        col_softmax = self._soft_max(
                            loc_col[0, all_ind_min:all_ind_max, k, i])
                        out_tmp = np.sum(col_softmax * all_ind) + 0.5
                        out_tmp = out_tmp / (num_grid_col - 1) * self.original_frame_height
                        tmp.append((int(col_anchor[k] * self.original_frame_width),
                                    int(out_tmp)))
                coords.append(tmp)
        return coords

    def get_coordinates(self, endnodes):
        """Get lane coordinates from inference results."""
        loc_row, loc_col, exist_row, exist_col = self._slice_and_reshape(endnodes)
        return self._pred2coords(loc_row, loc_col, exist_row, exist_col)

    def get_original_frame_size(self):
        """Retrieve the original frame size as (width, height)."""
        return (self.original_frame_width, self.original_frame_height)


class DepartureDetector:
    """
    Analyzes detected lane positions to determine lane departure events.

    The detector looks at the two center lanes (row-based lanes from UFLD)
    and computes the vehicle's lateral position relative to the lane center.
    When the vehicle drifts beyond a configurable threshold, a departure
    warning is triggered.
    """

    # Departure direction constants
    CENTERED = "centered"
    LEFT_DEPARTURE = "left"
    RIGHT_DEPARTURE = "right"
    NO_LANES = "no_lanes"

    def __init__(self, frame_width, frame_height, departure_threshold=0.15,
                 smoothing_window=5):
        """
        Initialize the departure detector.

        Args:
            frame_width (int): Width of the video frame in pixels.
            frame_height (int): Height of the video frame in pixels.
            departure_threshold (float): Fractional offset from lane center
                (0.0 to 0.5) that triggers a departure warning. Default 0.15
                means the vehicle center must be 15% of the lane width away
                from the lane center.
            smoothing_window (int): Number of frames to average over for
                smoothing the lateral offset. Reduces false positives from
                noisy detections.
        """
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.departure_threshold = departure_threshold
        self.smoothing_window = smoothing_window
        self.offset_history = []
        self.departure_events = []
        self.frame_index = 0

    def analyze_lanes(self, lanes):
        """
        Analyze lane positions and determine departure status.

        Expects that the first two entries in `lanes` are the row-based center
        lanes (left and right of the vehicle). The vehicle position is assumed
        to be at the horizontal center of the frame.

        Args:
            lanes (list): List of lane coordinate lists from UFLDProcessing.

        Returns:
            dict: Analysis result with keys:
                - 'status': one of CENTERED, LEFT_DEPARTURE, RIGHT_DEPARTURE, NO_LANES
                - 'offset': normalized lateral offset (-1 to 1, negative=left)
                - 'left_lane_x': average x of left lane (or None)
                - 'right_lane_x': average x of right lane (or None)
                - 'lane_center_x': center between left and right lane (or None)
                - 'vehicle_x': assumed vehicle position (frame center)
                - 'frame_index': current frame number
        """
        self.frame_index += 1
        vehicle_x = self.frame_width / 2.0

        # We need at least 2 row-based lanes (left and right center lanes)
        row_lanes = [lane for lane in lanes if len(lane) >= 3]

        if len(row_lanes) < 2:
            result = {
                'status': self.NO_LANES,
                'offset': 0.0,
                'left_lane_x': None,
                'right_lane_x': None,
                'lane_center_x': None,
                'vehicle_x': vehicle_x,
                'frame_index': self.frame_index,
            }
            return result

        # Use the bottom portion of the frame for lane position estimation
        # (more stable, closer to the vehicle)
        bottom_threshold_y = self.frame_height * 0.7

        def avg_x_bottom(lane_coords):
            bottom_pts = [(x, y) for x, y in lane_coords if y >= bottom_threshold_y]
            if not bottom_pts:
                bottom_pts = lane_coords[-5:]  # fallback: last 5 points
            if not bottom_pts:
                return None
            return np.mean([x for x, y in bottom_pts])

        # Sort row lanes by average x to identify left and right
        lane_xs = []
        for lane in row_lanes:
            avg = avg_x_bottom(lane)
            if avg is not None:
                lane_xs.append((avg, lane))

        if len(lane_xs) < 2:
            return {
                'status': self.NO_LANES,
                'offset': 0.0,
                'left_lane_x': None,
                'right_lane_x': None,
                'lane_center_x': None,
                'vehicle_x': vehicle_x,
                'frame_index': self.frame_index,
            }

        lane_xs.sort(key=lambda t: t[0])
        left_lane_x = lane_xs[0][0]
        right_lane_x = lane_xs[-1][0]

        lane_center_x = (left_lane_x + right_lane_x) / 2.0
        lane_width = right_lane_x - left_lane_x

        if lane_width < 10:  # Too narrow, likely noise
            return {
                'status': self.NO_LANES,
                'offset': 0.0,
                'left_lane_x': left_lane_x,
                'right_lane_x': right_lane_x,
                'lane_center_x': lane_center_x,
                'vehicle_x': vehicle_x,
                'frame_index': self.frame_index,
            }

        # Normalized offset: -1 = at left lane, +1 = at right lane, 0 = centered
        raw_offset = (vehicle_x - lane_center_x) / (lane_width / 2.0)

        # Smooth offset over recent frames
        self.offset_history.append(raw_offset)
        if len(self.offset_history) > self.smoothing_window:
            self.offset_history = self.offset_history[-self.smoothing_window:]
        smoothed_offset = np.mean(self.offset_history)

        # Determine departure status
        if smoothed_offset < -self.departure_threshold:
            status = self.LEFT_DEPARTURE
        elif smoothed_offset > self.departure_threshold:
            status = self.RIGHT_DEPARTURE
        else:
            status = self.CENTERED

        # Log departure events
        if status in (self.LEFT_DEPARTURE, self.RIGHT_DEPARTURE):
            event = {
                'frame': self.frame_index,
                'direction': status,
                'offset': float(smoothed_offset),
            }
            # Only log if this is a new event or direction changed
            if (not self.departure_events or
                    self.departure_events[-1]['direction'] != status):
                self.departure_events.append(event)
                logger.warning(
                    f"Lane departure detected at frame {self.frame_index}: "
                    f"{status} (offset: {smoothed_offset:.3f})")

        return {
            'status': status,
            'offset': float(smoothed_offset),
            'left_lane_x': float(left_lane_x),
            'right_lane_x': float(right_lane_x),
            'lane_center_x': float(lane_center_x),
            'vehicle_x': vehicle_x,
            'frame_index': self.frame_index,
        }

    def get_departure_events(self):
        """Return all departure events logged during processing."""
        return list(self.departure_events)

    def get_summary(self):
        """
        Return a summary of departure statistics.

        Returns:
            dict: Summary with total_frames, total_departures,
                  left_departures, right_departures, and events list.
        """
        left_count = sum(1 for e in self.departure_events
                         if e['direction'] == self.LEFT_DEPARTURE)
        right_count = sum(1 for e in self.departure_events
                          if e['direction'] == self.RIGHT_DEPARTURE)
        return {
            'total_frames': self.frame_index,
            'total_departures': len(self.departure_events),
            'left_departures': left_count,
            'right_departures': right_count,
            'events': self.departure_events,
        }


def compute_scaled_radius(width, height, standard_width=1280,
                           standard_height=720, base_radius=5):
    """Compute a scaled circle radius based on the video resolution."""
    standard_diag = hypot(standard_width, standard_height)
    diag = hypot(width, height)
    scale = diag / standard_diag
    return max(int(base_radius * scale), 1)


def draw_departure_overlay(frame, analysis, lane_coords, radius):
    """
    Draw lane markings and departure warning overlay on a frame.

    Args:
        frame (numpy.ndarray): The video frame to annotate.
        analysis (dict): Analysis result from DepartureDetector.analyze_lanes().
        lane_coords (list): List of lane coordinate lists from UFLDProcessing.
        radius (int): Radius for lane point circles.

    Returns:
        numpy.ndarray: The annotated frame.
    """
    status = analysis['status']

    # Color coding: green = centered, yellow = no lanes, red = departure
    if status == DepartureDetector.CENTERED:
        lane_color = (0, 255, 0)  # Green
        status_text = "CENTERED"
        text_color = (0, 255, 0)
    elif status == DepartureDetector.NO_LANES:
        lane_color = (0, 255, 255)  # Yellow
        status_text = "NO LANES DETECTED"
        text_color = (0, 255, 255)
    elif status == DepartureDetector.LEFT_DEPARTURE:
        lane_color = (0, 0, 255)  # Red
        status_text = "WARNING: LEFT DEPARTURE"
        text_color = (0, 0, 255)
    elif status == DepartureDetector.RIGHT_DEPARTURE:
        lane_color = (0, 0, 255)  # Red
        status_text = "WARNING: RIGHT DEPARTURE"
        text_color = (0, 0, 255)
    else:
        lane_color = (0, 255, 0)
        status_text = ""
        text_color = (255, 255, 255)

    # Draw lane points
    for lane in lane_coords:
        for coord in lane:
            cv2.circle(frame, coord, radius, lane_color, -1)

    # Draw status text
    h, w = frame.shape[:2]
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = max(0.6, w / 1280.0)
    thickness = max(1, int(w / 640))

    # Background rectangle for text
    text_size = cv2.getTextSize(status_text, font, font_scale, thickness)[0]
    text_x = (w - text_size[0]) // 2
    text_y = 40 + text_size[1]
    cv2.rectangle(frame,
                  (text_x - 10, text_y - text_size[1] - 10),
                  (text_x + text_size[0] + 10, text_y + 10),
                  (0, 0, 0), -1)
    cv2.putText(frame, status_text, (text_x, text_y), font,
                font_scale, text_color, thickness, cv2.LINE_AA)

    # Draw offset indicator bar
    if analysis['offset'] is not None and status != DepartureDetector.NO_LANES:
        bar_width = int(w * 0.3)
        bar_height = 20
        bar_x = (w - bar_width) // 2
        bar_y = text_y + 30

        # Bar background
        cv2.rectangle(frame, (bar_x, bar_y),
                      (bar_x + bar_width, bar_y + bar_height),
                      (80, 80, 80), -1)
        # Center line
        center_x = bar_x + bar_width // 2
        cv2.line(frame, (center_x, bar_y),
                 (center_x, bar_y + bar_height), (255, 255, 255), 1)

        # Vehicle position indicator
        offset_clamped = max(-1.0, min(1.0, analysis['offset']))
        indicator_x = int(center_x + offset_clamped * (bar_width // 2))
        cv2.circle(frame, (indicator_x, bar_y + bar_height // 2),
                   bar_height // 2, text_color, -1)

    # Draw lane center and vehicle position lines if available
    if (analysis['left_lane_x'] is not None and
            analysis['right_lane_x'] is not None):
        left_x = int(analysis['left_lane_x'])
        right_x = int(analysis['right_lane_x'])
        center_lane_x = int(analysis['lane_center_x'])
        vehicle_x = int(analysis['vehicle_x'])

        # Lane boundary lines (bottom half of frame)
        line_start_y = h // 2
        cv2.line(frame, (left_x, line_start_y), (left_x, h),
                 (255, 200, 0), 2)
        cv2.line(frame, (right_x, line_start_y), (right_x, h),
                 (255, 200, 0), 2)
        # Lane center (dashed effect with short line)
        cv2.line(frame, (center_lane_x, h - 60), (center_lane_x, h),
                 (255, 255, 255), 1)
        # Vehicle position
        cv2.line(frame, (vehicle_x, h - 80), (vehicle_x, h),
                 text_color, 2)

    return frame
