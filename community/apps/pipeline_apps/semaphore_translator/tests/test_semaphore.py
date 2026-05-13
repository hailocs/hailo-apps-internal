"""Unit tests for semaphore translator pure-Python helpers.

Tests compute_arm_angle, discretize_angle, decode_semaphore without any
GStreamer or Hailo dependencies.
"""

import math
import sys
from unittest.mock import MagicMock

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

from community.apps.pipeline_apps.semaphore_translator.semaphore_translator import (
    ANGLE_TOLERANCE,
    SEMAPHORE_ALPHABET,
    compute_arm_angle,
    decode_semaphore,
    discretize_angle,
)


class TestComputeArmAngle:
    """Returns SIGNALER-perspective angles (mirror of image), per the longer
    comment in semaphore_translator.py:57-63. The per-function docstring at
    L113-117 is misleading — see Findings below.

    Signaler-perspective: 0=down, 90=signaler-right (image-LEFT, wrist_x<0),
    180=up, 270=signaler-left (image-RIGHT, wrist_x>0).
    """

    def test_straight_down(self):
        # wrist directly below shoulder (positive y = down in image coords)
        a = compute_arm_angle(0, 0, 0, 1)
        assert pytest.approx(a, abs=0.1) == 0.0

    def test_image_right_is_signaler_left_270(self):
        a = compute_arm_angle(0, 0, 1, 0)
        assert pytest.approx(a, abs=0.1) == 270.0

    def test_straight_up(self):
        a = compute_arm_angle(0, 0, 0, -1)
        assert pytest.approx(a, abs=0.1) == 180.0

    def test_image_left_is_signaler_right_90(self):
        a = compute_arm_angle(0, 0, -1, 0)
        assert pytest.approx(a, abs=0.1) == 90.0

    def test_diagonal_image_down_right_is_signaler_315(self):
        a = compute_arm_angle(0, 0, 1, 1)
        assert pytest.approx(a, abs=0.1) == 315.0

    def test_diagonal_image_up_left_is_signaler_135(self):
        a = compute_arm_angle(0, 0, -1, -1)
        assert pytest.approx(a, abs=0.1) == 135.0

    def test_result_always_in_0_360(self):
        for theta in range(0, 360, 13):
            rad = math.radians(theta)
            # shoulder origin; wrist at unit distance at angle theta from +x
            wrist_x = math.cos(rad)
            wrist_y = math.sin(rad)
            a = compute_arm_angle(0, 0, wrist_x, wrist_y)
            assert 0.0 <= a < 360.0


class TestDiscretizeAngle:
    @pytest.mark.parametrize(
        "inp,exp",
        [
            (0, 0),
            (22, 0),
            (23, 45),
            (45, 45),
            (67, 45),
            (68, 90),
            (90, 90),
            (180, 180),
            (315, 315),
            (337, 315),
            (338, 0),
            (359, 0),
            (360, 0),
        ],
    )
    def test_buckets(self, inp, exp):
        assert discretize_angle(inp) == exp

    def test_returns_int(self):
        assert isinstance(discretize_angle(42.0), int)


class TestDecodeSemaphore:
    def test_exact_letter_A(self):
        assert decode_semaphore(45, 0) == "A"

    def test_exact_letter_R(self):
        assert decode_semaphore(90, 270) == "R"

    def test_rest(self):
        assert decode_semaphore(0, 0) == "REST"

    def test_no_match_returns_question(self):
        # 200 deg right / 100 deg left: no entry has both arms within 30 deg.
        # Closest right entries are at 180 (V, T, P, D, J) but their left arms
        # are at 0, 180, 270, 315 — all > 30 deg from 100.
        assert decode_semaphore(200, 100) == "?"

    def test_close_match_within_tolerance(self):
        # Right arm 50 deg (exact 45 "A" / closer to 45 than 90), left arm 0 deg.
        # Within 30-deg tolerance of (45, 0) — should still be "A".
        assert decode_semaphore(50, 0) == "A"

    def test_every_letter_decodable(self):
        """Each entry in SEMAPHORE_ALPHABET must round-trip to its letter."""
        for (r, l), expected in SEMAPHORE_ALPHABET.items():
            assert decode_semaphore(r, l) == expected, f"({r},{l}) -> {expected}"

    def test_tolerance_constant_is_reasonable(self):
        # ANGLE_TOLERANCE is half a 45-deg bucket; sanity check.
        assert 10 <= ANGLE_TOLERANCE <= 45
