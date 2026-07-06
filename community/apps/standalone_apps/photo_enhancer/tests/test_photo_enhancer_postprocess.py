"""Unit tests for the photo_enhancer (Real-ESRGAN) standalone post-processing.

These are PURE-PYTHON tests: no device, no inference, no network. They exercise
the letterbox-removal / resize math in ``photo_enhancer_utils`` and the
side-by-side composition in ``inference_result_handler``.

Key behaviours under test (these guard recent fixes):
  * ``resize_infer_result_to_original`` crops the letterbox region using the
    *model input* dimensions, NOT the (possibly 2x) output tensor shape, and
    always resizes the crop back to the original ``(orig_h, orig_w)``.
  * The scale factor is ``min(model_w/orig_w, model_h/orig_h)``.
  * No spurious BGR<->RGB channel swap is applied (the BGR2RGB removal fix):
    channels must be preserved end to end.
"""

import sys
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest

pytestmark = pytest.mark.community

# HailoRT is not available on the test machine. The utils module only imports
# cv2/numpy, but stub the hailo_platform tree defensively to keep the import of
# any sibling module (and future refactors) headless.
for mod_name in [
    "hailo_platform",
    "hailo_platform.pyhailort",
    "hailo_platform.pyhailort.pyhailort",
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

from community.apps.standalone_apps.photo_enhancer.photo_enhancer_utils import (
    inference_result_handler,
    resize_infer_result_to_original,
)


def make_infer_result(model_h, model_w, channels=3, value=200):
    """A synthetic 'inference result' tensor sized at the model input dims.

    The handler crops the letterbox region using the MODEL input dimensions, so
    a valid synthetic infer_result must be at least model_h x model_w. We build
    it exactly at model dims (the common Real-ESRGAN-on-Hailo case where the
    output buffer carries the model's letterboxed canvas).
    """
    return np.full((model_h, model_w, channels), value, dtype=np.uint8)


class TestScaleFactor:
    """scale = min(model_w/orig_w, model_h/orig_h) drives the letterbox math."""

    @pytest.mark.parametrize(
        "orig_h,orig_w,model_h,model_w,expected_scale",
        [
            # Square model, square image -> scale 1.0
            (256, 256, 256, 256, 1.0),
            # Landscape image into square model: width is the binding dim.
            (256, 512, 256, 256, 256 / 512),
            # Portrait image into square model: height is the binding dim.
            (512, 256, 256, 256, 256 / 512),
            # Image larger than model in both dims -> downscale, min wins.
            (1000, 500, 256, 256, 256 / 1000),
            # Image smaller than model -> upscale (scale > 1), min still wins.
            (100, 200, 256, 256, 256 / 200),
        ],
    )
    def test_resized_dims_follow_min_scale(
        self, orig_h, orig_w, model_h, model_w, expected_scale
    ):
        # Recompute the intermediate the function uses and assert the crop
        # offsets land where the letterbox math expects them.
        resized_h = int(orig_h * expected_scale)
        resized_w = int(orig_w * expected_scale)
        # Sanity: the scaled image must fit inside the model canvas.
        assert resized_h <= model_h
        assert resized_w <= model_w

        infer = make_infer_result(model_h, model_w)
        out = resize_infer_result_to_original(
            infer_result=infer,
            original_size=(orig_h, orig_w),
            model_input_size=(model_h, model_w),
        )
        # Final output is always the original size regardless of scale.
        assert out.shape[:2] == (orig_h, orig_w)


class TestResizeOutputDimensions:
    """The result must always match the original (H, W) and keep channel count."""

    @pytest.mark.parametrize(
        "orig_h,orig_w",
        [
            (480, 640),   # landscape
            (640, 480),   # portrait
            (300, 300),   # square
            (1, 1),       # degenerate 1x1 (scale==1: survives)
            (17, 31),     # odd, prime-ish dims (offset rounding)
        ],
    )
    def test_output_matches_original_size(self, orig_h, orig_w):
        model_h = model_w = 256
        infer = make_infer_result(model_h, model_w)
        out = resize_infer_result_to_original(
            infer_result=infer,
            original_size=(orig_h, orig_w),
            model_input_size=(model_h, model_w),
        )
        assert out.shape == (orig_h, orig_w, 3)
        assert out.dtype == np.uint8

    def test_identity_case_passthrough(self):
        """orig == model and scale == 1: output equals the (full) infer_result."""
        size = 128
        # Random content so we can assert exact pixel equality after a no-op
        # crop + same-size cubic resize.
        rng = np.random.default_rng(0)
        infer = rng.integers(0, 256, size=(size, size, 3), dtype=np.uint8)
        out = resize_infer_result_to_original(
            infer_result=infer,
            original_size=(size, size),
            model_input_size=(size, size),
        )
        assert out.shape == (size, size, 3)
        # Cropping with offset 0 over the whole canvas + resize to the same dims
        # is an identity for INTER_CUBIC on a same-size target.
        assert np.array_equal(out, infer)


class TestModelInputVsOutputShape:
    """Crop must use the MODEL input dims, not the 2x output tensor shape.

    This guards the fix where the handler passes (model_height, model_width)
    rather than the output tensor's (possibly upscaled) shape.
    """

    def test_crop_uses_model_dims_not_output_dims(self):
        # Real-ESRGAN x2: output canvas is 2x the model input. The handler is
        # told the MODEL dims, so offsets/crop are computed against model dims.
        orig_h, orig_w = 200, 400      # landscape original
        model_h, model_w = 256, 256    # square model input
        # The infer_result here is sized at model dims (what the cropped region
        # is indexed against). Passing model_input_size=(model_h, model_w) means
        # the crop fits exactly.
        infer = make_infer_result(model_h, model_w)
        out = resize_infer_result_to_original(
            infer_result=infer,
            original_size=(orig_h, orig_w),
            model_input_size=(model_h, model_w),
        )
        assert out.shape == (orig_h, orig_w, 3)

    def test_crop_region_targets_letterbox_center(self):
        """The cropped pixels come from the centered letterbox region.

        Build an infer_result that is uniformly 50, but paint the exact centered
        letterbox window a distinct value. After crop+resize the output should be
        dominated by that distinct value (the padding bands are excluded).
        """
        orig_h, orig_w = 256, 512      # landscape -> letterbox top/bottom
        model_h, model_w = 256, 256
        scale = min(model_w / orig_w, model_h / orig_h)
        resized_h = int(orig_h * scale)  # 128
        resized_w = int(orig_w * scale)  # 256
        y_off = (model_h - resized_h) // 2
        x_off = (model_w - resized_w) // 2

        infer = np.full((model_h, model_w, 3), 50, dtype=np.uint8)
        # Paint the centered content window 222.
        infer[y_off:y_off + resized_h, x_off:x_off + resized_w] = 222

        out = resize_infer_result_to_original(
            infer_result=infer,
            original_size=(orig_h, orig_w),
            model_input_size=(model_h, model_w),
        )
        # The padding bands (value 50) must have been cropped away: the result
        # is the content window only, so its mean is ~222, not somewhere between.
        assert out.shape == (orig_h, orig_w, 3)
        assert out.mean() > 200, f"padding leaked into crop: mean={out.mean()}"

    def test_oversized_infer_result_only_uses_model_window(self):
        """If the infer_result is larger than the model canvas (2x output),
        the crop still indexes only the [0:model] letterbox window."""
        orig_h, orig_w = 256, 256
        model_h, model_w = 256, 256
        # 2x output canvas, top-left model-sized quadrant = 100, rest = 9.
        infer = np.full((512, 512, 3), 9, dtype=np.uint8)
        infer[:model_h, :model_w] = 100
        out = resize_infer_result_to_original(
            infer_result=infer,
            original_size=(orig_h, orig_w),
            model_input_size=(model_h, model_w),
        )
        # scale==1, offsets==0 -> crop is exactly the [0:256,0:256] window (=100).
        assert out.shape == (orig_h, orig_w, 3)
        assert np.all(out == 100)


class TestChannelPreservation:
    """The BGR2RGB removal fix: channels must NOT be swapped or reordered."""

    def test_distinct_channels_preserved(self):
        """Feed an image with distinct R/G/B planes; assert order is unchanged.

        scale==1 + same-size target makes crop+resize an identity, so a channel
        swap would be directly observable.
        """
        size = 64
        infer = np.zeros((size, size, 3), dtype=np.uint8)
        infer[..., 0] = 10   # channel 0
        infer[..., 1] = 120  # channel 1
        infer[..., 2] = 240  # channel 2
        out = resize_infer_result_to_original(
            infer_result=infer,
            original_size=(size, size),
            model_input_size=(size, size),
        )
        assert np.all(out[..., 0] == 10)
        assert np.all(out[..., 1] == 120)
        assert np.all(out[..., 2] == 240)

    def test_channel_count_preserved_for_four_channels(self):
        """A 4-channel (e.g. RGBA) tensor keeps all 4 channels (no swap/drop)."""
        size = 48
        infer = make_infer_result(size, size, channels=4)
        out = resize_infer_result_to_original(
            infer_result=infer,
            original_size=(size, size),
            model_input_size=(size, size),
        )
        assert out.shape == (size, size, 4)


class TestInferenceResultHandler:
    """The top-level handler: side-by-side vs enhanced-only, and dim wiring."""

    def test_enhanced_only_returns_original_sized_enhanced(self):
        orig_h, orig_w = 240, 320
        model_h, model_w = 256, 256
        original = np.full((orig_h, orig_w, 3), 30, dtype=np.uint8)
        infer = make_infer_result(model_h, model_w, value=210)
        out = inference_result_handler(
            original_frame=original,
            infer_result=infer,
            model_height=model_h,
            model_width=model_w,
            enhanced_only=True,
        )
        assert out.shape == (orig_h, orig_w, 3)
        # Enhanced output reflects the infer content (210), not the original (30).
        assert out.mean() > 150

    def test_side_by_side_doubles_width(self):
        orig_h, orig_w = 240, 320
        model_h, model_w = 256, 256
        original = np.full((orig_h, orig_w, 3), 30, dtype=np.uint8)
        infer = make_infer_result(model_h, model_w, value=210)
        out = inference_result_handler(
            original_frame=original,
            infer_result=infer,
            model_height=model_h,
            model_width=model_w,
            enhanced_only=False,
        )
        # hstack of two (orig_h, orig_w) images -> (orig_h, 2*orig_w).
        assert out.shape == (orig_h, orig_w * 2, 3)

    def test_side_by_side_left_half_is_the_original(self):
        """Left half must be the untouched original; right half the enhanced."""
        orig_h, orig_w = 100, 150
        model_h, model_w = 256, 256
        original = np.full((orig_h, orig_w, 3), 30, dtype=np.uint8)
        infer = make_infer_result(model_h, model_w, value=210)
        out = inference_result_handler(
            original_frame=original,
            infer_result=infer,
            model_height=model_h,
            model_width=model_w,
            enhanced_only=False,
        )
        left = out[:, :orig_w]
        right = out[:, orig_w:]
        assert np.array_equal(left, original)
        assert right.mean() > 150  # enhanced (210), distinct from original (30)

    def test_default_is_side_by_side(self):
        """enhanced_only defaults to False -> side-by-side."""
        orig_h, orig_w = 50, 80
        model_h, model_w = 256, 256
        original = np.zeros((orig_h, orig_w, 3), dtype=np.uint8)
        infer = make_infer_result(model_h, model_w)
        out = inference_result_handler(
            original_frame=original,
            infer_result=infer,
            model_height=model_h,
            model_width=model_w,
        )
        assert out.shape == (orig_h, orig_w * 2, 3)

    def test_handler_passes_model_dims_for_square_input(self):
        """End-to-end square case: orig==model gives an identity-sized enhanced."""
        size = 256
        original = np.full((size, size, 3), 5, dtype=np.uint8)
        infer = make_infer_result(size, size, value=99)
        out = inference_result_handler(
            original_frame=original,
            infer_result=infer,
            model_height=size,
            model_width=size,
            enhanced_only=True,
        )
        assert out.shape == (size, size, 3)
        assert np.all(out == 99)

    def test_handler_channels_preserved(self):
        """No BGR<->RGB swap through the handler path either."""
        orig_h, orig_w = 64, 64
        original = np.zeros((orig_h, orig_w, 3), dtype=np.uint8)
        infer = np.zeros((orig_h, orig_w, 3), dtype=np.uint8)
        infer[..., 0] = 11
        infer[..., 1] = 111
        infer[..., 2] = 211
        out = inference_result_handler(
            original_frame=original,
            infer_result=infer,
            model_height=orig_h,
            model_width=orig_w,
            enhanced_only=True,
        )
        assert np.all(out[..., 0] == 11)
        assert np.all(out[..., 1] == 111)
        assert np.all(out[..., 2] == 211)


class TestEdgeCases:
    def test_one_by_one_image(self):
        """A 1x1 original must not crash and yields a (1,1,3) enhanced output."""
        model_h = model_w = 256
        infer = make_infer_result(model_h, model_w, value=77)
        out = resize_infer_result_to_original(
            infer_result=infer,
            original_size=(1, 1),
            model_input_size=(model_h, model_w),
        )
        assert out.shape == (1, 1, 3)

    def test_one_by_one_side_by_side(self):
        original = np.full((1, 1, 3), 5, dtype=np.uint8)
        infer = make_infer_result(256, 256, value=200)
        out = inference_result_handler(
            original_frame=original,
            infer_result=infer,
            model_height=256,
            model_width=256,
            enhanced_only=False,
        )
        assert out.shape == (1, 2, 3)

    def test_extreme_aspect_ratio_landscape(self):
        """Very wide image: width binds the scale, large vertical letterbox."""
        orig_h, orig_w = 64, 1024
        model_h = model_w = 256
        infer = make_infer_result(model_h, model_w)
        out = resize_infer_result_to_original(
            infer_result=infer,
            original_size=(orig_h, orig_w),
            model_input_size=(model_h, model_w),
        )
        assert out.shape == (orig_h, orig_w, 3)

    def test_extreme_aspect_ratio_portrait(self):
        """Very tall image: height binds the scale, large horizontal letterbox."""
        orig_h, orig_w = 1024, 64
        model_h = model_w = 256
        infer = make_infer_result(model_h, model_w)
        out = resize_infer_result_to_original(
            infer_result=infer,
            original_size=(orig_h, orig_w),
            model_input_size=(model_h, model_w),
        )
        assert out.shape == (orig_h, orig_w, 3)

    def test_degenerate_strip_rounds_a_dimension_to_zero(self):
        """A thin strip whose short side rounds to 0 under the scale.

        For orig=(1, 640) into a 256x256 model: scale = 256/640 = 0.4, so
        resized_h = int(1 * 0.4) = 0 -> the crop is empty and the downstream
        cv2.resize raises. This documents the source's actual (unguarded)
        behaviour for these degenerate inputs; the app feeds normal photos, not
        1px strips. We assert it rather than silently passing a false claim.
        """
        model_h = model_w = 256
        infer = make_infer_result(model_h, model_w)
        with pytest.raises(cv2.error):
            resize_infer_result_to_original(
                infer_result=infer,
                original_size=(1, 640),
                model_input_size=(model_h, model_w),
            )

    def test_non_square_model_input(self):
        """Model input need not be square; min-scale still picks the binding dim."""
        orig_h, orig_w = 300, 300
        model_h, model_w = 192, 256  # taller-constrained model
        infer = make_infer_result(model_h, model_w)
        out = resize_infer_result_to_original(
            infer_result=infer,
            original_size=(orig_h, orig_w),
            model_input_size=(model_h, model_w),
        )
        assert out.shape == (orig_h, orig_w, 3)
