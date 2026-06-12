"""Smoke tests for DepthAnythingCallback construction and configuration.

The full app_callback requires GStreamer buffers and Hailo metadata; these
tests only cover the constructor + state initialization across display modes.
"""

import sys
from unittest.mock import MagicMock

import numpy as np
import pytest

for mod_name in [
    "hailo",
    "gi",
    "gi.repository",
    "gi.repository.Gst",
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()
sys.modules["gi"].require_version = lambda *a, **kw: None

from community.apps.pipeline_apps.depth_anything.depth_anything import (
    COLORMAP_MAP,
    DEPTH_WINDOW_NAME,
    DepthAnythingCallback,
)


class TestDepthAnythingCallbackConstruction:
    def test_default_display_mode(self):
        cb = DepthAnythingCallback()
        assert cb.display_mode == "depth"

    def test_colormap_lookup_inferno(self):
        import cv2
        cb = DepthAnythingCallback(colormap_name="inferno")
        assert cb.colormap_cv2 == cv2.COLORMAP_INFERNO

    def test_unknown_colormap_falls_back_to_inferno(self):
        import cv2
        cb = DepthAnythingCallback(colormap_name="banana")
        assert cb.colormap_cv2 == cv2.COLORMAP_INFERNO

    def test_relative_mode_no_metric_converter(self):
        cb = DepthAnythingCallback(depth_mode="relative")
        assert cb.metric_converter is None

    def test_metric_mode_creates_converter_indoor(self):
        cb = DepthAnythingCallback(depth_mode="metric", scene_type="indoor")
        assert cb.metric_converter is not None
        assert cb.metric_converter.max_depth == 20.0

    def test_metric_mode_creates_converter_outdoor(self):
        cb = DepthAnythingCallback(depth_mode="metric", scene_type="outdoor")
        assert cb.metric_converter is not None
        assert cb.metric_converter.max_depth == 80.0

    def test_temporal_alpha_stored(self):
        cb = DepthAnythingCallback(temporal_alpha=0.7)
        assert cb.temporal_alpha == 0.7
        # Smoothing state starts empty
        assert cb._prev_depth is None
        assert cb._smooth_min is None
        assert cb._smooth_max is None

    def test_max_clip_zero_disables(self):
        cb = DepthAnythingCallback(max_clip=0)
        assert cb.max_clip is None

    def test_max_clip_negative_disables(self):
        cb = DepthAnythingCallback(max_clip=-1.0)
        assert cb.max_clip is None

    def test_max_clip_positive_stored(self):
        cb = DepthAnythingCallback(max_clip=15.0)
        assert cb.max_clip == 15.0

    def test_export_depth_creates_directory(self, tmp_path):
        out = tmp_path / "depth_export"
        assert not out.exists()
        cb = DepthAnythingCallback(export_depth=str(out))
        assert out.exists()


class TestModuleConstants:
    def test_colormap_map_has_expected_names(self):
        assert set(COLORMAP_MAP.keys()) == {"inferno", "spectral", "magma", "turbo"}

    def test_depth_window_name(self):
        assert DEPTH_WINDOW_NAME == "Depth Anything"
