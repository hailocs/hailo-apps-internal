import sys
from unittest.mock import MagicMock

import numpy as np
import pytest

# Mock hardware-specific modules before importing anything that depends on them
for mod_name in ["hailo", "gi", "gi.repository", "gi.repository.Gst"]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

# gi.require_version must be a callable that does nothing
sys.modules["gi"].require_version = lambda *a, **kw: None

from community.apps.pipeline_apps.depth_anything.metric_depth import MetricDepthConverter


class TestMetricDepthConverter:
    """Tests for MetricDepthConverter affine scaling."""

    def test_indoor_scene_type_sets_max_depth_20(self):
        converter = MetricDepthConverter(scene_type="indoor")
        assert converter.max_depth == 20.0

    def test_outdoor_scene_type_sets_max_depth_80(self):
        converter = MetricDepthConverter(scene_type="outdoor")
        assert converter.max_depth == 80.0

    def test_custom_max_depth_overrides_scene_type(self):
        converter = MetricDepthConverter(scene_type="indoor", max_depth=50.0)
        assert converter.max_depth == 50.0

    def test_convert_relative_to_metric_basic(self):
        """Relative depth [0, 1] should map to [near_clip, max_depth]."""
        converter = MetricDepthConverter(scene_type="indoor")  # max_depth=20
        relative = np.array([[0.0, 0.5], [1.0, 0.25]])
        metric = converter.convert(relative)
        # min relative (0.0) -> near_clip (0.1m), max relative (1.0) -> 20m
        assert metric.shape == (2, 2)
        assert pytest.approx(metric[0, 0], abs=0.5) == 0.1  # near
        assert pytest.approx(metric[1, 0], abs=1.0) == 20.0  # far
        # Monotonically increasing with relative depth
        assert metric[0, 1] > metric[0, 0]

    def test_convert_handles_constant_depth(self):
        """All-same relative values should not crash (zero range)."""
        converter = MetricDepthConverter(scene_type="indoor")
        relative = np.ones((4, 4)) * 0.5
        metric = converter.convert(relative)
        assert not np.any(np.isnan(metric))
        assert not np.any(np.isinf(metric))

    def test_convert_with_raw_dequantized_range(self):
        """Real model outputs are NOT [0,1] -- they're arbitrary dequantized floats."""
        converter = MetricDepthConverter(scene_type="outdoor")  # max_depth=80
        # Simulate raw dequantized values (e.g., range 2.1 to 47.8)
        relative = np.array([[2.1, 25.0], [47.8, 10.0]])
        metric = converter.convert(relative)
        # Should still map linearly to [near_clip, max_depth]
        assert metric.min() >= 0.0
        assert metric.max() <= 80.0

    def test_is_calibrated_false_by_default(self):
        converter = MetricDepthConverter(scene_type="indoor")
        assert not converter.is_calibrated

    def test_invalid_scene_type_raises(self):
        with pytest.raises(ValueError):
            MetricDepthConverter(scene_type="underwater")


class TestCalibration:
    """Tests for reference-point calibration."""

    def test_calibrate_single_point_sets_scale(self):
        converter = MetricDepthConverter(scene_type="indoor")
        # Simulate: at some pixel, relative depth = 10.0, known real depth = 3.0m
        converter.calibrate_from_reference(
            relative_values=np.array([10.0]),
            metric_values=np.array([3.0]),
        )
        assert converter.is_calibrated

    def test_calibrate_two_points_affine(self):
        converter = MetricDepthConverter(scene_type="indoor")
        # Two reference points define an affine mapping
        converter.calibrate_from_reference(
            relative_values=np.array([5.0, 20.0]),
            metric_values=np.array([1.0, 4.0]),
        )
        # Now convert: relative=5 should give ~1m, relative=20 should give ~4m
        result = converter.convert(np.array([[5.0, 20.0]]))
        assert pytest.approx(result[0, 0], abs=0.01) == 1.0
        assert pytest.approx(result[0, 1], abs=0.01) == 4.0

    def test_calibrate_single_point_uses_proportional_scale(self):
        converter = MetricDepthConverter(scene_type="indoor")
        converter.calibrate_from_reference(
            relative_values=np.array([10.0]),
            metric_values=np.array([2.0]),
        )
        # scale = 2.0 / 10.0 = 0.2, shift = 0
        result = converter.convert(np.array([[10.0, 20.0]]))
        assert pytest.approx(result[0, 0], abs=0.01) == 2.0
        assert pytest.approx(result[0, 1], abs=0.01) == 4.0

    def test_reset_calibration(self):
        converter = MetricDepthConverter(scene_type="indoor")
        converter.calibrate_from_reference(
            relative_values=np.array([10.0]),
            metric_values=np.array([2.0]),
        )
        assert converter.is_calibrated
        converter.reset_calibration()
        assert not converter.is_calibrated


class TestCallbackWiring:
    """Tests for DepthAnythingCallback metric initialization."""

    def test_callback_creates_converter_in_metric_mode(self):
        from community.apps.pipeline_apps.depth_anything.depth_anything import DepthAnythingCallback
        cb = DepthAnythingCallback(depth_mode="metric", scene_type="indoor")
        assert cb.metric_converter is not None
        assert cb.metric_converter.max_depth == 20.0

    def test_callback_no_converter_in_relative_mode(self):
        from community.apps.pipeline_apps.depth_anything.depth_anything import DepthAnythingCallback
        cb = DepthAnythingCallback(depth_mode="relative")
        assert cb.metric_converter is None

    def test_callback_passes_custom_max_depth(self):
        from community.apps.pipeline_apps.depth_anything.depth_anything import DepthAnythingCallback
        cb = DepthAnythingCallback(depth_mode="metric", scene_type="outdoor", max_depth=50.0)
        assert cb.metric_converter.max_depth == 50.0


class TestCLICalibration:
    """Tests for CLI-based calibration via --calibrate-ref."""

    def test_calibrate_ref_parsing(self):
        from community.apps.pipeline_apps.depth_anything.depth_anything import DepthAnythingCallback
        cb = DepthAnythingCallback(
            depth_mode="metric", scene_type="indoor",
            calibrate_ref="15.3:2.5"
        )
        assert cb.metric_converter.is_calibrated
        # relative=15.3 should map to 2.5m
        result = cb.metric_converter.convert(np.array([[15.3]]))
        assert pytest.approx(result[0, 0], abs=0.01) == 2.5

    def test_calibrate_ref_none_means_uncalibrated(self):
        from community.apps.pipeline_apps.depth_anything.depth_anything import DepthAnythingCallback
        cb = DepthAnythingCallback(depth_mode="metric", scene_type="indoor")
        assert not cb.metric_converter.is_calibrated
