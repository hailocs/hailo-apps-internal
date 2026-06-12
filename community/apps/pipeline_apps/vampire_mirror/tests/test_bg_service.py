"""Integration tests for BackgroundService — spawns a real subprocess."""
import time
import numpy as np
import pytest

from community.apps.pipeline_apps.vampire_mirror.bg_service import BackgroundService


@pytest.fixture
def shm_prefix(tmp_path_factory):
    """Unique prefix per test run to avoid clashes with leftover shm."""
    return f"vmtest_{int(time.time() * 1000) % 100000}_"


class TestBackgroundService:
    def test_capture_then_ema(self, shm_prefix):
        """Service captures initial frames, then runs EMA on subsequent frames."""
        svc = BackgroundService(
            width=8, height=8, channels=3,
            capture_frames=2, alpha=0.5,
            shm_prefix=shm_prefix,
        )
        svc.start()
        try:
            f100 = np.full((8, 8, 3), 100, dtype=np.uint8)
            f200 = np.full((8, 8, 3), 200, dtype=np.uint8)
            # Capture phase: 2 frames at 100 → bg = 100
            # Sleep between submits so subprocess can consume each frame
            # (Event semantics: rapid double-set looks like one signal).
            svc.submit_frame(f100, person_mask=None)
            time.sleep(0.05)
            svc.submit_frame(f100, person_mask=None)
            # Wait for service to process — poll up to 1s
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                if svc.is_ready():
                    break
                time.sleep(0.01)
            assert svc.is_ready()
            bg = svc.get_background_copy()
            np.testing.assert_array_equal(bg, 100)

            # One EMA step with 200, alpha=0.5 → 150
            svc.submit_frame(f200, person_mask=None)
            time.sleep(0.2)
            bg = svc.get_background_copy()
            assert 140 <= bg.mean() <= 160
        finally:
            svc.stop()

    def test_person_mask_blocks_update(self, shm_prefix):
        """Pixels under person_mask must not adapt."""
        svc = BackgroundService(
            width=8, height=8, channels=3,
            capture_frames=1, alpha=1.0,
            shm_prefix=shm_prefix,
        )
        svc.start()
        try:
            f0 = np.zeros((8, 8, 3), dtype=np.uint8)
            f255 = np.full((8, 8, 3), 255, dtype=np.uint8)
            mask = np.zeros((8, 8), dtype=bool)
            mask[0:4, 0:4] = True

            svc.submit_frame(f0, person_mask=None)
            time.sleep(0.2)
            assert svc.is_ready()
            svc.submit_frame(f255, person_mask=mask)
            time.sleep(0.2)
            bg = svc.get_background_copy()
            np.testing.assert_array_equal(bg[0:4, 0:4], 0)
            np.testing.assert_array_equal(bg[4:, :], 255)
        finally:
            svc.stop()

    def test_submit_frame_wrong_shape_raises(self, shm_prefix):
        """submit_frame must reject frames of the wrong shape."""
        svc = BackgroundService(
            width=8, height=8, channels=3,
            capture_frames=1, alpha=0.5,
            shm_prefix=shm_prefix,
        )
        svc.start()
        try:
            bad = np.zeros((4, 4, 3), dtype=np.uint8)
            with pytest.raises((AssertionError, ValueError)):
                svc.submit_frame(bad, person_mask=None)
        finally:
            svc.stop()

    def test_submit_frame_before_start_raises(self, shm_prefix):
        """Calling submit_frame before start() raises RuntimeError, not AttributeError."""
        svc = BackgroundService(
            width=8, height=8, channels=3,
            shm_prefix=shm_prefix,
        )
        f = np.zeros((8, 8, 3), dtype=np.uint8)
        with pytest.raises(RuntimeError, match="start"):
            svc.submit_frame(f, person_mask=None)

    def test_stop_is_idempotent(self, shm_prefix):
        """stop() can be called twice without raising."""
        svc = BackgroundService(
            width=8, height=8, channels=3,
            shm_prefix=shm_prefix,
        )
        svc.start()
        svc.stop()
        svc.stop()  # must not raise
