"""Unit tests for depth_anything_python standalone post-processing."""

import sys
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest

# HailoRT not available on test machine — stub all the submodules the app
# transitively imports.
for mod_name in [
    "hailo_platform",
    "hailo_platform.pyhailort",
    "hailo_platform.pyhailort.pyhailort",
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

from community.apps.standalone_apps.depth_anything_python.depth_anything_standalone import (
    COLORMAP_MAP,
    MODEL_NAMES,
    MODEL_URLS,
    depth_postprocess,
)


class TestDepthPostprocess:
    def test_depth_mode_returns_frame_sized_output(self):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        depth = np.random.rand(192, 256).astype(np.float32)
        out = depth_postprocess(frame, depth, display_mode="depth")
        assert out.shape == frame.shape

    def test_side_by_side_doubles_width_minus_one(self):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        depth = np.random.rand(192, 256).astype(np.float32)
        out = depth_postprocess(frame, depth, display_mode="side-by-side")
        # Left half + right half = ~width; allow 1px rounding tolerance.
        assert out.shape[0] == 480
        assert abs(out.shape[1] - 640) <= 1

    def test_overlay_returns_frame_sized(self):
        frame = np.full((480, 640, 3), 128, dtype=np.uint8)
        depth = np.random.rand(192, 256).astype(np.float32)
        out = depth_postprocess(frame, depth, display_mode="overlay", alpha=0.5)
        assert out.shape == frame.shape

    def test_handles_3d_depth_with_trailing_one_channel(self):
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        depth = np.random.rand(50, 50, 1).astype(np.float32)
        out = depth_postprocess(frame, depth, display_mode="depth")
        assert out.shape == (100, 100, 3)

    def test_constant_depth_does_not_crash(self):
        """All-equal depth values must not divide by zero (epsilon handles it)."""
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        depth = np.full((50, 50), 2.5, dtype=np.float32)
        out = depth_postprocess(frame, depth, display_mode="depth")
        assert out.shape == (100, 100, 3)
        # The output is some valid colormap image (uint8)
        assert out.dtype == np.uint8

    def test_output_dtype_is_uint8(self):
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        depth = np.random.rand(50, 50).astype(np.float32)
        for mode in ("depth", "side-by-side", "overlay"):
            out = depth_postprocess(frame, depth, display_mode=mode)
            assert out.dtype == np.uint8, f"mode={mode}"


class TestColormapRegistry:
    def test_all_named_colormaps_resolve(self):
        for name, code in COLORMAP_MAP.items():
            assert isinstance(code, int)
        # The pipeline version uses the same 4 names — keep them in sync.
        assert set(COLORMAP_MAP.keys()) == {"inferno", "spectral", "magma", "turbo"}


class TestModelUrlRegistry:
    def test_model_names_known(self):
        assert set(MODEL_NAMES.keys()) == {"v1", "v2"}

    def test_each_known_arch_has_a_url(self):
        # We don't enforce all-archs coverage but at least one entry per version.
        v1_archs = {arch for ver, arch in MODEL_URLS if ver == "v1"}
        v2_archs = {arch for ver, arch in MODEL_URLS if ver == "v2"}
        assert v1_archs, "no MODEL_URLS entry for depth_anything v1"
        assert v2_archs, "no MODEL_URLS entry for depth_anything v2"

    def test_urls_are_https(self):
        for url in MODEL_URLS.values():
            assert url.startswith("https://"), f"non-https URL: {url}"
