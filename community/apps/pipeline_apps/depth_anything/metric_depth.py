"""Metric depth conversion from relative depth maps.

Converts Depth Anything's relative (unitless) depth output to approximate
metric depth in meters using affine scaling with scene-type priors.
"""

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
