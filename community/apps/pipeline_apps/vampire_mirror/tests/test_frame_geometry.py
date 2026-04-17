"""Tests for FrameGeometry — center crop dimensions and mirror overlap detection."""

import numpy as np
import pytest

from community.apps.pipeline_apps.vampire_mirror.frame_geometry import FrameGeometry


# ---------------------------------------------------------------------------
# Crop dimension tests
# ---------------------------------------------------------------------------

class TestFrameGeometryDimensions:
    """Verify crop coordinates are computed correctly for various frame sizes and ratios."""

    def test_standard_hd_9_16(self):
        """1280x720 landscape with default 9:16 portrait ratio."""
        geom = FrameGeometry(1280, 720)
        # mirror_width = 720 * 9 / 16 = 405
        assert geom.mirror_width == 405
        assert geom.mirror_height == 720
        # crop_x1 = (1280 - 405) // 2 = 437
        assert geom.crop_x1 == 437
        assert geom.crop_x2 == 437 + 405  # 842

    def test_square_frame_9_16(self):
        """640x640 square frame with default 9:16 ratio."""
        geom = FrameGeometry(640, 640)
        # mirror_width = 640 * 9 / 16 = 360
        assert geom.mirror_width == 360
        assert geom.mirror_height == 640

    def test_narrow_frame_clamp(self):
        """If computed mirror_width exceeds frame_width, clamp to frame_width."""
        # 200x400: mirror_width = 400 * 9/16 = 225 > 200 → clamp to 200
        geom = FrameGeometry(200, 400)
        assert geom.mirror_width == 200
        assert geom.crop_x1 == 0
        assert geom.crop_x2 == 200

    def test_custom_ratio_3_4(self):
        """Custom 3:4 ratio on a 1280x720 frame."""
        geom = FrameGeometry(1280, 720, mirror_ratio=(3, 4))
        # mirror_width = 720 * 3 / 4 = 540
        assert geom.mirror_width == 540
        # crop_x1 = (1280 - 540) // 2 = 370
        assert geom.crop_x1 == 370
        assert geom.crop_x2 == 370 + 540  # 910

    def test_crop_x1_non_negative(self):
        """crop_x1 must never be negative."""
        geom = FrameGeometry(100, 200)  # very narrow
        assert geom.crop_x1 >= 0


# ---------------------------------------------------------------------------
# center_crop tests
# ---------------------------------------------------------------------------

class TestCenterCrop:
    """Verify center_crop returns the correct slice of a numpy frame."""

    def test_output_shape(self):
        """Cropped frame has expected dimensions."""
        geom = FrameGeometry(1280, 720)
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        cropped = geom.center_crop(frame)
        assert cropped.shape == (720, 405, 3)

    def test_output_content(self):
        """Cropped frame contains pixels from the mirror region, not the buffer zones."""
        geom = FrameGeometry(1280, 720)
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        # Paint the mirror column red
        frame[:, geom.crop_x1:geom.crop_x2, 0] = 255
        cropped = geom.center_crop(frame)
        # All red-channel values in the crop should be 255
        assert np.all(cropped[:, :, 0] == 255)

    def test_output_content_buffer_excluded(self):
        """Buffer zones (left/right of mirror) are not included in the crop."""
        geom = FrameGeometry(1280, 720)
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        # Paint buffer zones blue
        frame[:, :geom.crop_x1, 2] = 200
        frame[:, geom.crop_x2:, 2] = 200
        cropped = geom.center_crop(frame)
        # Crop should have no blue pixels
        assert np.all(cropped[:, :, 2] == 0)

    def test_square_crop_shape(self):
        """Square frame crop has correct dimensions."""
        geom = FrameGeometry(640, 640)
        frame = np.ones((640, 640, 3), dtype=np.uint8)
        cropped = geom.center_crop(frame)
        assert cropped.shape == (640, 360, 3)


# ---------------------------------------------------------------------------
# is_in_mirror tests
# ---------------------------------------------------------------------------

class TestIsInMirror:
    """Verify bounding-box overlap detection with the mirror region."""

    def setup_method(self):
        # 1280x720, mirror at x=[437, 842]
        self.geom = FrameGeometry(1280, 720)

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
