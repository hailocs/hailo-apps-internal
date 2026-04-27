"""Tests for VelocityCommandAPI (per-axis smoothing)."""

import asyncio
import time

import pytest

from drone_follow.follow_api import (
    ControllerConfig,
    Detection,
    VelocityCommand,
)
from drone_follow.drone_api import VelocityCommandAPI


def _det(cx=0.5, cy=0.5, bh=0.3):
    return Detection(
        label="test", confidence=0.9,
        center_x=cx, center_y=cy, bbox_height=bh,
        timestamp=time.monotonic(),
    )


# ---------------------------------------------------------------------------
# VelocityCommandAPI
# ---------------------------------------------------------------------------

class TestVelocityCommandAPIClamping:
    """send() should clamp each axis to configured maximums."""

    @pytest.fixture
    def api(self):
        cfg = ControllerConfig(
            max_forward=2.0, max_backward=3.0,
            max_down_speed=1.5,
            max_yawspeed=90.0,
            max_orbit_speed=1.0,
            smooth_yaw=False, smooth_forward=False,
            smooth_right=False, smooth_down=False,
            max_forward_accel=0,  # disable slew limiter to isolate clamp behavior
        )
        return VelocityCommandAPI(drone=None, config=cfg)

    def test_forward_clamped_to_max(self, api):
        cmd = VelocityCommand(999.0, 0.0, 0.0, 0.0)
        result = asyncio.run(api.send(cmd))
        assert result.forward_m_s == pytest.approx(2.0)

    def test_backward_clamped_to_max(self, api):
        cmd = VelocityCommand(-999.0, 0.0, 0.0, 0.0)
        result = asyncio.run(api.send(cmd))
        assert result.forward_m_s == pytest.approx(-3.0)

    def test_down_clamped_both_directions(self, api):
        up = asyncio.run(api.send(VelocityCommand(0.0, 0.0, -999.0, 0.0)))
        down = asyncio.run(api.send(VelocityCommand(0.0, 0.0, 999.0, 0.0)))
        assert up.down_m_s == pytest.approx(-1.5)
        assert down.down_m_s == pytest.approx(1.5)

    def test_yaw_clamped(self, api):
        result = asyncio.run(api.send(VelocityCommand(0.0, 0.0, 0.0, 200.0)))
        assert result.yawspeed_deg_s == pytest.approx(90.0)

    def test_right_clamped_to_1(self, api):
        result = asyncio.run(api.send(VelocityCommand(0.0, 5.0, 0.0, 0.0)))
        assert result.right_m_s == pytest.approx(1.0)

    def test_within_limits_passes_through(self, api):
        cmd = VelocityCommand(1.0, 0.5, -0.5, 30.0)
        result = asyncio.run(api.send(cmd))
        assert result.forward_m_s == pytest.approx(1.0)
        assert result.right_m_s == pytest.approx(0.5)
        assert result.down_m_s == pytest.approx(-0.5)
        assert result.yawspeed_deg_s == pytest.approx(30.0)


class TestVelocityCommandAPIYawFilter:
    """Yaw low-pass filter behavior with smooth_yaw enabled."""

    def test_filter_smooths_step_input(self):
        cfg = ControllerConfig(smooth_yaw=True, yaw_alpha=0.3, max_yawspeed=200.0)
        api = VelocityCommandAPI(drone=None, config=cfg)

        step = VelocityCommand(0.0, 0.0, 0.0, 100.0)
        r1 = asyncio.run(api.send(step))
        # First sample: filtered = 0.3 * 100 + 0.7 * 0 = 30
        assert r1.yawspeed_deg_s == pytest.approx(30.0)

        r2 = asyncio.run(api.send(step))
        # Second: filtered = 0.3 * 100 + 0.7 * 30 = 51
        assert r2.yawspeed_deg_s == pytest.approx(51.0)

    def test_filter_converges(self):
        cfg = ControllerConfig(smooth_yaw=True, yaw_alpha=0.5, max_yawspeed=200.0)
        api = VelocityCommandAPI(drone=None, config=cfg)

        step = VelocityCommand(0.0, 0.0, 0.0, 60.0)
        result = None
        for _ in range(50):
            result = asyncio.run(api.send(step))
        assert result.yawspeed_deg_s == pytest.approx(60.0, abs=0.1)

    def test_smooth_yaw_off_passes_through(self):
        cfg = ControllerConfig(smooth_yaw=False, max_yawspeed=200.0)
        api = VelocityCommandAPI(drone=None, config=cfg)

        r = asyncio.run(api.send(VelocityCommand(0.0, 0.0, 0.0, 100.0)))
        assert r.yawspeed_deg_s == pytest.approx(100.0)

    def test_yaw_alpha_from_config(self):
        cfg = ControllerConfig(smooth_yaw=True, yaw_alpha=0.1, max_yawspeed=200.0)
        api = VelocityCommandAPI(drone=None, config=cfg)

        r = asyncio.run(api.send(VelocityCommand(0.0, 0.0, 0.0, 100.0)))
        # alpha=0.1: filtered = 0.1 * 100 = 10
        assert r.yawspeed_deg_s == pytest.approx(10.0)


class TestVelocityCommandAPISendZero:

    def test_send_zero_resets_filter(self):
        cfg = ControllerConfig(smooth_yaw=True, yaw_alpha=0.5, max_yawspeed=200.0)
        api = VelocityCommandAPI(drone=None, config=cfg)

        # Build up filter state
        for _ in range(5):
            asyncio.run(api.send(VelocityCommand(0.0, 0.0, 0.0, 80.0)))
        assert api._filtered_yaw != 0.0

        asyncio.run(api.send_zero())
        assert api._filtered_yaw == 0.0

    def test_reset_filters_zeroes_all_state(self):
        cfg = ControllerConfig(
            smooth_yaw=True, yaw_alpha=0.5, max_yawspeed=200.0,
            smooth_forward=True, forward_alpha=0.5, max_forward=5.0,
        )
        api = VelocityCommandAPI(drone=None, config=cfg)

        asyncio.run(api.send(VelocityCommand(3.0, 0.0, 0.0, 50.0)))
        api.reset_filters()
        assert api._filtered_yaw == 0.0
        assert api._filtered_forward == 0.0
        assert api._filtered_right == 0.0
        assert api._filtered_down == 0.0

        # After reset, first sample should start from 0 again
        r = asyncio.run(api.send(VelocityCommand(0.0, 0.0, 0.0, 100.0)))
        assert r.yawspeed_deg_s == pytest.approx(50.0)  # 0.5 * 100 + 0.5 * 0


# ---------------------------------------------------------------------------
# Per-axis EMA smoothing in VelocityCommandAPI
# ---------------------------------------------------------------------------

class TestForwardSmoothing:
    """Forward-axis EMA smoothing in VelocityCommandAPI."""

    def _make_api(self, **overrides):
        defaults = dict(
            smooth_forward=True, forward_alpha=0.5,
            smooth_yaw=False, smooth_right=False, smooth_down=False,
            max_forward=5.0, max_backward=5.0,
            max_forward_accel=0,  # disable slew limiter to isolate EMA behavior
        )
        defaults.update(overrides)
        return VelocityCommandAPI(drone=None, config=ControllerConfig(**defaults))

    def test_first_call_returns_alpha_times_input(self):
        api = self._make_api()
        r = asyncio.run(api.send(VelocityCommand(2.0, 0.0, 0.0, 0.0)))
        # smoothed = 0.5 * 2.0 + 0.5 * 0.0 = 1.0
        assert r.forward_m_s == pytest.approx(1.0)

    def test_ema_converges_to_constant_input(self):
        api = self._make_api(forward_alpha=0.3)
        for _ in range(100):
            r = asyncio.run(api.send(VelocityCommand(1.5, 0.0, 0.0, 0.0)))
        assert r.forward_m_s == pytest.approx(1.5, abs=0.01)

    def test_high_alpha_responds_faster(self):
        api_fast = self._make_api(forward_alpha=0.9)
        api_slow = self._make_api(forward_alpha=0.1)
        r_fast = asyncio.run(api_fast.send(VelocityCommand(2.0, 0.0, 0.0, 0.0)))
        r_slow = asyncio.run(api_slow.send(VelocityCommand(2.0, 0.0, 0.0, 0.0)))
        assert r_fast.forward_m_s > r_slow.forward_m_s

    def test_disabled_passes_through(self):
        api = self._make_api(smooth_forward=False)
        r = asyncio.run(api.send(VelocityCommand(2.0, 0.0, 0.0, 0.0)))
        assert r.forward_m_s == pytest.approx(2.0)


class TestForwardSlewLimiter:
    """Hard slew-rate cap on forward velocity (tilt-transient safety)."""

    def _make_api(self, **overrides):
        defaults = dict(
            smooth_forward=False, smooth_yaw=False, smooth_right=False, smooth_down=False,
            max_forward=5.0, max_backward=5.0,
            max_forward_accel=1.0, control_loop_hz=10.0,  # → 0.1 m/s per tick
        )
        defaults.update(overrides)
        return VelocityCommandAPI(drone=None, config=ControllerConfig(**defaults))

    def test_step_input_ramps_at_max_step(self):
        api = self._make_api()
        for expected in (0.1, 0.2, 0.3):
            r = asyncio.run(api.send(VelocityCommand(2.0, 0.0, 0.0, 0.0)))
            assert r.forward_m_s == pytest.approx(expected, abs=1e-6)

    def test_disabled_when_zero(self):
        api = self._make_api(max_forward_accel=0)
        r = asyncio.run(api.send(VelocityCommand(2.0, 0.0, 0.0, 0.0)))
        assert r.forward_m_s == pytest.approx(2.0)

    def test_decel_symmetric(self):
        api = self._make_api()
        # Ramp up to 0.5, then issue 0.0 — should step down 0.1 per tick
        for _ in range(5):
            asyncio.run(api.send(VelocityCommand(2.0, 0.0, 0.0, 0.0)))
        for expected in (0.4, 0.3, 0.2, 0.1, 0.0):
            r = asyncio.run(api.send(VelocityCommand(0.0, 0.0, 0.0, 0.0)))
            assert r.forward_m_s == pytest.approx(expected, abs=1e-6)

    def test_send_zero_resets_prev(self):
        api = self._make_api()
        for _ in range(5):
            asyncio.run(api.send(VelocityCommand(2.0, 0.0, 0.0, 0.0)))
        assert api._prev_forward != 0.0
        asyncio.run(api.send_zero())
        assert api._prev_forward == 0.0


class TestRightSmoothing:
    """Right-axis EMA smoothing in VelocityCommandAPI."""

    def test_smoothed_when_enabled(self):
        cfg = ControllerConfig(
            smooth_right=True, right_alpha=0.3,
            smooth_yaw=False, smooth_forward=False, smooth_down=False,
            max_orbit_speed=5.0,
        )
        api = VelocityCommandAPI(drone=None, config=cfg)
        r = asyncio.run(api.send(VelocityCommand(0.0, 2.0, 0.0, 0.0)))
        # First tick: 0.3 * 2.0 + 0.7 * 0.0 = 0.6
        assert r.right_m_s == pytest.approx(0.6)

    def test_disabled_passes_through(self):
        cfg = ControllerConfig(
            smooth_right=False,
            smooth_yaw=False, smooth_forward=False, smooth_down=False,
            max_orbit_speed=5.0,
        )
        api = VelocityCommandAPI(drone=None, config=cfg)
        r = asyncio.run(api.send(VelocityCommand(0.0, 2.0, 0.0, 0.0)))
        assert r.right_m_s == pytest.approx(2.0)


class TestDownSmoothing:
    """Down-axis EMA smoothing in VelocityCommandAPI."""

    def test_smoothed_when_enabled(self):
        cfg = ControllerConfig(
            smooth_down=True, down_alpha=0.2,
            smooth_yaw=False, smooth_forward=False, smooth_right=False,
            max_down_speed=5.0,
        )
        api = VelocityCommandAPI(drone=None, config=cfg)
        r = asyncio.run(api.send(VelocityCommand(0.0, 0.0, 1.0, 0.0)))
        # First tick: 0.2 * 1.0 + 0.8 * 0.0 = 0.2
        assert r.down_m_s == pytest.approx(0.2)

    def test_disabled_passes_through(self):
        cfg = ControllerConfig(
            smooth_down=False,
            smooth_yaw=False, smooth_forward=False, smooth_right=False,
            max_down_speed=5.0,
        )
        api = VelocityCommandAPI(drone=None, config=cfg)
        r = asyncio.run(api.send(VelocityCommand(0.0, 0.0, 1.0, 0.0)))
        assert r.down_m_s == pytest.approx(1.0)
