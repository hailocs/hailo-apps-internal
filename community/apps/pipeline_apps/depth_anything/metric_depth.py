"""Metric depth conversion from relative depth maps.

Converts Depth Anything's relative (unitless) depth output to approximate
metric depth in meters using affine scaling with scene-type priors.
"""

import cv2
import numpy as np

# Scene-type defaults based on Depth Anything V2 metric model training ranges
SCENE_PRESETS = {
    "indoor": {"max_depth": 20.0, "near_clip": 0.1},
    "outdoor": {"max_depth": 80.0, "near_clip": 0.5},
}


class MetricDepthConverter:
    """Converts relative depth to metric depth (meters) via affine scaling.

    The conversion is: metric = near_clip + (normalized_relative) * (max_depth - near_clip)
    where normalized_relative = (relative - rel_min) / (rel_max - rel_min)

    Calibration (Task 2) refines scale and shift using known reference points.
    """

    def __init__(self, scene_type="indoor", max_depth=None, near_clip=None):
        if scene_type not in SCENE_PRESETS:
            raise ValueError(
                f"Invalid scene_type '{scene_type}'. "
                f"Choose from: {list(SCENE_PRESETS.keys())}"
            )

        preset = SCENE_PRESETS[scene_type]
        self.scene_type = scene_type
        self.max_depth = max_depth if max_depth is not None else preset["max_depth"]
        self.near_clip = near_clip if near_clip is not None else preset["near_clip"]

        # Calibration state (set by calibrate_from_reference in Task 2)
        self._calibrated_scale = None
        self._calibrated_shift = None

    @property
    def is_calibrated(self):
        """Whether calibration has been applied."""
        return self._calibrated_scale is not None

    def calibrate_from_reference(self, relative_values, metric_values):
        """Calibrate using known reference points.

        Args:
            relative_values: 1D array of relative depth values at reference pixels.
            metric_values: 1D array of corresponding real depths in meters.

        With 1 point: proportional scaling (shift=0).
        With 2+ points: least-squares affine fit (metric = scale * relative + shift).
        """
        relative_values = np.asarray(relative_values, dtype=np.float64)
        metric_values = np.asarray(metric_values, dtype=np.float64)

        if len(relative_values) == 1:
            # Single point: proportional scale, zero shift
            self._calibrated_scale = metric_values[0] / (relative_values[0] + 1e-10)
            self._calibrated_shift = 0.0
        else:
            # Least-squares affine fit: metric = scale * relative + shift
            A = np.vstack([relative_values, np.ones(len(relative_values))]).T
            result = np.linalg.lstsq(A, metric_values, rcond=None)
            self._calibrated_scale = result[0][0]
            self._calibrated_shift = result[0][1]

    def reset_calibration(self):
        """Reset to uncalibrated (scene-type prior) mode."""
        self._calibrated_scale = None
        self._calibrated_shift = None

    def convert(self, relative_depth):
        """Convert relative depth map to metric depth in meters.

        Args:
            relative_depth: numpy array of raw relative depth values (any range).

        Returns:
            numpy array of same shape with depth in meters.
        """
        if self.is_calibrated:
            metric = self._calibrated_scale * relative_depth + self._calibrated_shift
            return np.clip(metric, 0.0, self.max_depth * 1.5)

        # Default: linear mapping from [min, max] -> [near_clip, max_depth]
        rel_min = relative_depth.min()
        rel_max = relative_depth.max()
        denom = rel_max - rel_min

        if denom < 1e-8:
            # Constant depth -- return midpoint
            return np.full_like(
                relative_depth,
                (self.near_clip + self.max_depth) / 2.0,
                dtype=np.float32,
            )

        normalized = (relative_depth - rel_min) / denom
        metric = self.near_clip + normalized * (self.max_depth - self.near_clip)
        return metric.astype(np.float32)


def render_scale_bar(frame, min_depth_m, max_depth_m, colormap, bar_width=30, margin=10):
    """Draw a vertical color scale bar with meter labels on the right side of the frame.

    Args:
        frame: BGR image (H, W, 3) — modified in-place.
        min_depth_m: minimum depth in meters.
        max_depth_m: maximum depth in meters.
        colormap: OpenCV colormap constant.
        bar_width: width of the scale bar in pixels.
        margin: margin from the right edge.

    Returns:
        frame with scale bar drawn.
    """
    h, w = frame.shape[:2]
    bar_x = w - bar_width - margin
    bar_top = margin
    bar_bottom = h - margin

    # Create gradient
    bar_height = bar_bottom - bar_top
    gradient = np.linspace(0, 255, bar_height).astype(np.uint8)
    gradient = 255 - gradient  # Inverted: top = far (dark), bottom = near (bright)
    gradient_color = cv2.applyColorMap(gradient.reshape(-1, 1), colormap)
    gradient_color = cv2.resize(gradient_color, (bar_width, bar_height))

    # Draw bar
    frame[bar_top:bar_bottom, bar_x:bar_x + bar_width] = gradient_color

    # Draw border
    cv2.rectangle(frame, (bar_x, bar_top), (bar_x + bar_width, bar_bottom), (255, 255, 255), 1)

    # Draw labels (5 ticks)
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.4
    for i in range(5):
        frac = i / 4.0
        y = bar_top + int(frac * (bar_height - 1))
        depth_val = max_depth_m - frac * (max_depth_m - min_depth_m)
        label = f"{depth_val:.1f}m"
        cv2.putText(frame, label, (bar_x - 45, y + 4), font, font_scale, (255, 255, 255), 1)

    return frame
