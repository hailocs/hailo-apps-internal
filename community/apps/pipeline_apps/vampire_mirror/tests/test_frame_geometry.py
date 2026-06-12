"""Tests for FrameGeometry — center crop dimensions and mirror overlap detection."""

import numpy as np
import pytest

from community.apps.pipeline_apps.vampire_mirror.frame_geometry import (
    FrameGeometry,
    detect_vertical_padding,
)


# ---------------------------------------------------------------------------
# Crop dimension tests
# ---------------------------------------------------------------------------

class TestFrameGeometryDimensions:
    """Verify crop coordinates are computed correctly for various frame sizes and ratios."""

    def test_standard_hd_9_16_no_pad(self):
        """1280x720 landscape with default 9:16 ratio, no vertical padding."""
        geom = FrameGeometry(1280, 720, vertical_pad=0, vertical_margin=0)
        assert geom.mirror_width == 405  # 720 * 9 / 16
        assert geom.mirror_height == 720
        assert geom.crop_x1 == 437
        assert geom.crop_y1 == 0
        assert geom.crop_y2 == 720

    def test_standard_hd_with_margin(self):
        """Default vertical_margin=5 trims 5 lines from each edge."""
        geom = FrameGeometry(1280, 720, vertical_pad=0)
        # content_height = 720 - 0 - 0 - 5 - 5 = 710
        assert geom.mirror_height == 710
        assert geom.crop_y1 == 5
        assert geom.crop_y2 == 715
        # mirror_width based on 710 content height
        assert geom.mirror_width == int(710 * 9 / 16)

    def test_with_vertical_padding(self):
        """Letterbox padding of 140px + margin of 5 → crop_y1=145."""
        geom = FrameGeometry(640, 640, vertical_pad=140, vertical_margin=5)
        assert geom.crop_y1 == 145
        assert geom.crop_y2 == 495  # 640 - 140 - 5
        assert geom.mirror_height == 350  # 495 - 145

    def test_square_frame_9_16(self):
        """640x640 square frame with default 9:16 ratio, no pad."""
        geom = FrameGeometry(640, 640, vertical_pad=0, vertical_margin=0)
        assert geom.mirror_width == 360  # 640 * 9 / 16
        assert geom.mirror_height == 640

    def test_narrow_frame_clamp(self):
        """If computed mirror_width exceeds frame_width, clamp to frame_width."""
        geom = FrameGeometry(200, 400, vertical_pad=0, vertical_margin=0)
        assert geom.mirror_width == 200
        assert geom.crop_x1 == 0

    def test_custom_ratio_3_4(self):
        """Custom 3:4 ratio on a 1280x720 frame, no padding."""
        geom = FrameGeometry(1280, 720, mirror_ratio=(3, 4),
                             vertical_pad=0, vertical_margin=0)
        assert geom.mirror_width == 540  # 720 * 3 / 4
        assert geom.crop_x1 == 370

    def test_crop_x1_non_negative(self):
        """crop_x1 must never be negative."""
        geom = FrameGeometry(100, 200, vertical_pad=0, vertical_margin=0)
        assert geom.crop_x1 >= 0


# ---------------------------------------------------------------------------
# center_crop tests
# ---------------------------------------------------------------------------

class TestCenterCrop:
    """Verify center_crop returns the correct slice of a numpy frame."""

    def test_output_shape_no_pad(self):
        """Cropped frame has expected dimensions (no padding)."""
        geom = FrameGeometry(1280, 720, vertical_pad=0, vertical_margin=0)
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        cropped = geom.center_crop(frame)
        assert cropped.shape == (720, 405, 3)

    def test_output_shape_with_pad(self):
        """Padding and margin are removed vertically."""
        geom = FrameGeometry(640, 640, vertical_pad=140, vertical_margin=5)
        frame = np.zeros((640, 640, 3), dtype=np.uint8)
        cropped = geom.center_crop(frame)
        assert cropped.shape[0] == geom.mirror_height  # 350
        assert cropped.shape[1] == geom.mirror_width

    def test_output_content(self):
        """Cropped frame contains pixels from the mirror region."""
        geom = FrameGeometry(1280, 720, vertical_pad=0, vertical_margin=0)
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        frame[:, geom.crop_x1:geom.crop_x2, 0] = 255
        cropped = geom.center_crop(frame)
        assert np.all(cropped[:, :, 0] == 255)

    def test_padding_excluded(self):
        """Black padding rows at top/bottom are excluded from crop."""
        geom = FrameGeometry(640, 640, vertical_pad=140, vertical_margin=0)
        frame = np.zeros((640, 640, 3), dtype=np.uint8)
        # Fill actual content area with white
        frame[140:500, :] = 255
        cropped = geom.center_crop(frame)
        # Entire crop should be white (no black padding)
        assert cropped.min() == 255

    def test_buffer_zones_excluded(self):
        """Buffer zones (left/right of mirror) are not in the crop."""
        geom = FrameGeometry(1280, 720, vertical_pad=0, vertical_margin=0)
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        frame[:, :geom.crop_x1, 2] = 200
        frame[:, geom.crop_x2:, 2] = 200
        cropped = geom.center_crop(frame)
        assert np.all(cropped[:, :, 2] == 0)


# ---------------------------------------------------------------------------
# is_in_mirror tests
# ---------------------------------------------------------------------------

class TestIsInMirror:
    """Verify bounding-box overlap detection with the mirror region."""

    def setup_method(self):
        # 1280x720, no vertical crop, mirror at x=[437, 842]
        self.geom = FrameGeometry(1280, 720, vertical_pad=0, vertical_margin=0)

    def test_fully_in_buffer_left(self):
        """Person entirely in left buffer zone → not in mirror."""
        # bbox from x=0 to x=100 (well left of crop_x1=437)
        assert self.geom.is_in_mirror(bbox_xmin=0, bbox_width=100, frame_width=1280) is False

    def test_fully_in_buffer_right(self):
        """Person entirely in right buffer zone → not in mirror."""
        # bbox from x=900 to x=1100 (well right of crop_x2=842)
        assert self.geom.is_in_mirror(bbox_xmin=900, bbox_width=200, frame_width=1280) is False

    def test_fully_in_mirror(self):
        """Person entirely within the mirror region → in mirror."""
        # bbox from x=500 to x=700, inside [437, 842]
        assert self.geom.is_in_mirror(bbox_xmin=500, bbox_width=200, frame_width=1280) is True

    def test_crossing_left_boundary(self):
        """Person straddling the left mirror boundary → in mirror."""
        # bbox from x=400 to x=500 crosses crop_x1=437
        assert self.geom.is_in_mirror(bbox_xmin=400, bbox_width=100, frame_width=1280) is True

    def test_crossing_right_boundary(self):
        """Person straddling the right mirror boundary → in mirror."""
        # bbox from x=800 to x=900 crosses crop_x2=842
        assert self.geom.is_in_mirror(bbox_xmin=800, bbox_width=100, frame_width=1280) is True

    def test_adjacent_left_no_overlap(self):
        """Person whose right edge equals crop_x1 exactly → not in mirror (no actual overlap)."""
        # bbox ends exactly at crop_x1=437 → xmax=437, mirror starts at 437 → no overlap
        assert self.geom.is_in_mirror(bbox_xmin=300, bbox_width=137, frame_width=1280) is False

    def test_adjacent_right_no_overlap(self):
        """Person whose left edge equals crop_x2 exactly → not in mirror."""
        # bbox starts at crop_x2=842 → no overlap
        assert self.geom.is_in_mirror(bbox_xmin=842, bbox_width=100, frame_width=1280) is False


# ---------------------------------------------------------------------------
# detect_vertical_padding tests
# ---------------------------------------------------------------------------

class TestDetectVerticalPadding:
    """Verify auto-detection of letterbox padding."""

    def test_no_padding(self):
        """Frame with no black rows → 0 padding."""
        frame = np.full((480, 640, 3), 128, dtype=np.uint8)
        assert detect_vertical_padding(frame) == 0

    def test_symmetric_padding(self):
        """Frame with 140px black bars top and bottom."""
        frame = np.zeros((640, 640, 3), dtype=np.uint8)
        frame[140:500, :] = 128  # content area
        assert detect_vertical_padding(frame) == 140

    def test_small_padding(self):
        """Frame with 10px padding."""
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        frame[10:90, :] = 200
        assert detect_vertical_padding(frame) == 10

    def test_all_black(self):
        """Entirely black frame → 0 (safe default, don't crop everything)."""
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        assert detect_vertical_padding(frame) == 0
