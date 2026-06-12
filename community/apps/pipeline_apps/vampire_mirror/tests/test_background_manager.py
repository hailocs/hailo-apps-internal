"""Tests for BackgroundManager — TDD first pass."""
import numpy as np
import pytest

from community.apps.pipeline_apps.vampire_mirror.background_manager import (
    BackgroundManager, BackgroundUpdater,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def solid_frame(value: float, shape=(4, 4, 3), dtype=np.uint8) -> np.ndarray:
    """Return a frame filled with a constant value."""
    return np.full(shape, value, dtype=dtype)


def solid_mask(value: bool, shape=(4, 4)) -> np.ndarray:
    """Return a boolean mask filled with a constant value."""
    return np.full(shape, value, dtype=bool)


# ---------------------------------------------------------------------------
# Initial-capture phase
# ---------------------------------------------------------------------------

class TestInitialCapture:
    def test_first_frame_becomes_background(self):
        """capture_frames=1: after the first update, background is ready."""
        mgr = BackgroundManager(capture_frames=1)
        frame = solid_frame(128)
        mgr.update(frame)
        assert mgr.is_ready
        assert mgr.background is not None
        np.testing.assert_array_almost_equal(mgr.background, frame.astype(np.uint8))

    def test_multi_frame_average(self):
        """capture_frames=2: average of frames at 100 and 200 should equal 150."""
        mgr = BackgroundManager(capture_frames=2)
        mgr.update(solid_frame(100))
        mgr.update(solid_frame(200))
        assert mgr.is_ready
        np.testing.assert_array_almost_equal(mgr.background, solid_frame(150, dtype=np.uint8))

    def test_frames_remaining(self):
        """capture_frames=5: after 1 update, 4 frames remaining."""
        mgr = BackgroundManager(capture_frames=5)
        assert mgr.frames_remaining == 5
        mgr.update(solid_frame(0))
        assert mgr.frames_remaining == 4

    def test_is_ready_false_before_complete(self):
        """is_ready is False until all capture frames have been collected."""
        mgr = BackgroundManager(capture_frames=3)
        assert not mgr.is_ready
        mgr.update(solid_frame(50))
        assert not mgr.is_ready
        mgr.update(solid_frame(50))
        assert not mgr.is_ready
        mgr.update(solid_frame(50))
        assert mgr.is_ready

    def test_frames_remaining_zero_when_ready(self):
        """frames_remaining reaches 0 once the background is ready."""
        mgr = BackgroundManager(capture_frames=2)
        mgr.update(solid_frame(0))
        mgr.update(solid_frame(0))
        assert mgr.frames_remaining == 0


# ---------------------------------------------------------------------------
# EMA update phase
# ---------------------------------------------------------------------------

class TestEMAUpdate:
    def test_update_without_vampire_mask(self):
        """alpha=1.0 with no mask: new frame fully replaces the background."""
        mgr = BackgroundManager(capture_frames=1, alpha=1.0)
        mgr.update(solid_frame(100))   # capture phase done
        assert mgr.is_ready

        new_frame = solid_frame(200)
        mgr.update(new_frame)
        np.testing.assert_array_almost_equal(mgr.background, solid_frame(200, dtype=np.uint8))

    def test_vampire_pixels_preserved(self):
        """alpha=1.0, vampire mask=True for entire frame → background unchanged."""
        mgr = BackgroundManager(capture_frames=1, alpha=1.0)
        initial = solid_frame(100)
        mgr.update(initial)            # capture phase done

        vampire_mask = solid_mask(True)   # whole frame is "vampire"
        mgr.update(solid_frame(200), person_mask=vampire_mask)
        # All pixels masked out → background stays at 100
        np.testing.assert_array_almost_equal(mgr.background, solid_frame(100, dtype=np.uint8))

    def test_partial_mask_preserves_only_masked_region(self):
        """Only the masked region is preserved; unmasked region is updated."""
        shape = (4, 4, 3)
        mgr = BackgroundManager(capture_frames=1, alpha=1.0)
        mgr.update(solid_frame(100, shape=shape))   # bg = 100 everywhere

        # Upper-left 2×2 is vampire, rest is not
        mask = np.zeros((4, 4), dtype=bool)
        mask[:2, :2] = True

        mgr.update(solid_frame(200, shape=shape), person_mask=mask)

        bg = mgr.background
        # Unmasked pixels should be 200
        np.testing.assert_array_almost_equal(bg[2:, 2:], np.full((2, 2, 3), 200, dtype=np.uint8))
        # Masked pixels should stay at 100
        np.testing.assert_array_almost_equal(bg[:2, :2], np.full((2, 2, 3), 100, dtype=np.uint8))

    def test_ema_blending(self):
        """alpha=0.5, bg=100, new_frame=200 → result=150."""
        mgr = BackgroundManager(capture_frames=1, alpha=0.5)
        mgr.update(solid_frame(100))   # capture phase: bg = 100
        assert mgr.is_ready

        mgr.update(solid_frame(200))
        # EMA: alpha * new + (1-alpha) * old = 0.5*200 + 0.5*100 = 150
        np.testing.assert_array_almost_equal(mgr.background, solid_frame(150, dtype=np.uint8))

    def test_mask_not_applied_during_capture_phase(self):
        """Vampire mask provided during capture phase is silently ignored."""
        mgr = BackgroundManager(capture_frames=2)
        mask = solid_mask(True)   # whole frame masked
        mgr.update(solid_frame(100), person_mask=mask)
        mgr.update(solid_frame(200), person_mask=mask)
        # Mask should have no effect during capture; result is average
        assert mgr.is_ready
        np.testing.assert_array_almost_equal(mgr.background, solid_frame(150, dtype=np.uint8))


# ---------------------------------------------------------------------------
# BackgroundUpdater — pure EMA logic
# ---------------------------------------------------------------------------

class TestBackgroundUpdater:
    def test_apply_in_place_no_mask(self):
        """Updater blends in-place, uint8, no allocation."""
        bg = np.full((4, 4, 3), 100, dtype=np.uint8)
        frame = np.full((4, 4, 3), 200, dtype=np.uint8)
        upd = BackgroundUpdater(alpha=0.5)
        upd.apply(bg, frame, person_mask=None)
        # 0.5 * 200 + 0.5 * 100 = 150
        np.testing.assert_array_equal(bg, np.full((4, 4, 3), 150, dtype=np.uint8))

    def test_apply_preserves_person_pixels(self):
        """Pixels where person_mask is True must not be updated."""
        bg = np.full((4, 4, 3), 100, dtype=np.uint8)
        frame = np.full((4, 4, 3), 200, dtype=np.uint8)
        mask = np.zeros((4, 4), dtype=bool)
        mask[0:2, 0:2] = True  # top-left quad blocked
        upd = BackgroundUpdater(alpha=0.5)
        upd.apply(bg, frame, person_mask=mask)
        # Blocked region unchanged
        np.testing.assert_array_equal(bg[0:2, 0:2], 100)
        # Open region blended
        np.testing.assert_array_equal(bg[2:, :], 150)

    def test_apply_alpha_one_replaces(self):
        """alpha=1.0 means the background is fully replaced by the frame."""
        bg = np.zeros((2, 2, 3), dtype=np.uint8)
        frame = np.full((2, 2, 3), 255, dtype=np.uint8)
        BackgroundUpdater(alpha=1.0).apply(bg, frame, person_mask=None)
        np.testing.assert_array_equal(bg, 255)

    def test_apply_preserves_person_pixels_top_right(self):
        """Top-right quad (unmasked but not in the 2: slice) should also be 150."""
        bg = np.full((4, 4, 3), 100, dtype=np.uint8)
        frame = np.full((4, 4, 3), 200, dtype=np.uint8)
        mask = np.zeros((4, 4), dtype=bool)
        mask[0:2, 0:2] = True  # top-left quad blocked
        upd = BackgroundUpdater(alpha=0.5)
        upd.apply(bg, frame, person_mask=mask)
        np.testing.assert_array_equal(bg[:2, 2:], 150)

    def test_apply_alpha_zero_freezes_background(self):
        """alpha=0 means the background is never updated."""
        bg = np.full((4, 4, 3), 50, dtype=np.uint8)
        frame = np.full((4, 4, 3), 200, dtype=np.uint8)
        BackgroundUpdater(alpha=0.0).apply(bg, frame, person_mask=None)
        np.testing.assert_array_equal(bg, 50)

    def test_apply_full_mask_freezes_background(self):
        """An all-True mask means nothing is updated."""
        bg = np.full((4, 4, 3), 50, dtype=np.uint8)
        frame = np.full((4, 4, 3), 200, dtype=np.uint8)
        mask = np.ones((4, 4), dtype=bool)
        BackgroundUpdater(alpha=0.5).apply(bg, frame, person_mask=mask)
        np.testing.assert_array_equal(bg, 50)

    def test_apply_empty_mask_blends_everywhere(self):
        """An all-False mask is functionally equivalent to no mask."""
        bg = np.full((4, 4, 3), 100, dtype=np.uint8)
        frame = np.full((4, 4, 3), 200, dtype=np.uint8)
        mask = np.zeros((4, 4), dtype=bool)
        BackgroundUpdater(alpha=0.5).apply(bg, frame, person_mask=mask)
        np.testing.assert_array_equal(bg, 150)

    def test_apply_raises_on_dtype_mismatch(self):
        """Float frame must raise ValueError (not pass silently)."""
        bg = np.zeros((4, 4, 3), dtype=np.uint8)
        frame = np.zeros((4, 4, 3), dtype=np.float32)
        with pytest.raises(ValueError, match="uint8"):
            BackgroundUpdater(alpha=0.5).apply(bg, frame, person_mask=None)

    def test_apply_raises_on_shape_mismatch(self):
        """Mismatched shapes must raise ValueError."""
        bg = np.zeros((4, 4, 3), dtype=np.uint8)
        frame = np.zeros((8, 8, 3), dtype=np.uint8)
        with pytest.raises(ValueError, match="Shape mismatch"):
            BackgroundUpdater(alpha=0.5).apply(bg, frame, person_mask=None)
