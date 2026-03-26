import numpy as np
import pytest
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
