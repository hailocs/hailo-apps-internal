"""Tests for the FOV-aware proportional controller."""

import time
from types import SimpleNamespace

import pytest

from drone_follow.follow_api import (
    Detection,
    ControllerConfig,
    compute_velocity_command,
)
from drone_follow.drone_api import VelocityCommandAPI


def _det(cx=0.5, cy=0.5, bh=0.3):
    """Helper to create a Detection at given normalized coords."""
    return Detection(
        label="test", confidence=0.9,
        center_x=cx, center_y=cy, bbox_height=bh,
        timestamp=time.monotonic(),
    )


@pytest.fixture
def config():
    """Default config with yaw_only=False for tests that need full movement."""
    return ControllerConfig(yaw_only=False)


# ---- No detection (search mode) ----

class TestSearchMode:
    def test_no_detection_returns_search_yaw(self, config):
        cmd = compute_velocity_command(None, config)
        assert cmd.yawspeed_deg_s == config.search_yawspeed_slow

    def test_no_detection_zero_velocity(self, config):
        cmd = compute_velocity_command(None, config)
        assert cmd.forward_m_s == 0.0
        assert cmd.right_m_s == 0.0
        assert cmd.down_m_s == 0.0


# ---- Yaw (horizontal centering) ----

class TestYaw:
    def test_centered_within_dead_zone(self, config):
        """Detection near center -> zero yaw (dead zone)."""
        cmd = compute_velocity_command(_det(cx=0.51), config)
        assert cmd.yawspeed_deg_s == 0.0

    def test_target_right_positive_yaw(self, config):
        """Detection right of center -> positive yaw (clockwise)."""
        cmd = compute_velocity_command(_det(cx=0.75), config)
        assert cmd.yawspeed_deg_s > 0.0

    def test_target_left_negative_yaw(self, config):
        """Detection left of center -> negative yaw (counter-clockwise)."""
        cmd = compute_velocity_command(_det(cx=0.25), config)
        assert cmd.yawspeed_deg_s < 0.0

    def test_symmetry(self, config):
        """Equal offsets left and right should produce equal magnitude."""
        cmd_right = compute_velocity_command(_det(cx=0.7), config)
        cmd_left = compute_velocity_command(_det(cx=0.3), config)
        assert abs(cmd_right.yawspeed_deg_s + cmd_left.yawspeed_deg_s) < 0.01

    def test_yaw_saturation(self, config):
        """Extreme offset should be clamped to max_yawspeed."""
        cmd = compute_velocity_command(_det(cx=1.0), config)
        assert abs(cmd.yawspeed_deg_s) <= config.max_yawspeed + 0.01

    def test_fov_scaling(self):
        """Wider FOV with same pixel offset -> larger angular error -> larger yaw rate."""
        narrow = ControllerConfig(hfov=60.0)
        wide = ControllerConfig(hfov=120.0)
        det = _det(cx=0.7)
        cmd_narrow = compute_velocity_command(det, narrow)
        cmd_wide = compute_velocity_command(det, wide)
        assert abs(cmd_wide.yawspeed_deg_s) > abs(cmd_narrow.yawspeed_deg_s)

    def test_fov_proportional(self):
        """Double the FOV should double the angular error and thus the yaw rate
        (when not saturated)."""
        cfg_a = ControllerConfig(hfov=40.0, max_yawspeed=9999.0)
        cfg_b = ControllerConfig(hfov=80.0, max_yawspeed=9999.0)
        det = _det(cx=0.6)  # small offset to stay in linear region
        cmd_a = compute_velocity_command(det, cfg_a)
        cmd_b = compute_velocity_command(det, cfg_b)
        ratio = cmd_b.yawspeed_deg_s / cmd_a.yawspeed_deg_s
        # Yaw controller uses sqrt(|error_x_deg|), so doubling FOV scales by sqrt(2).
        assert abs(ratio - (2.0 ** 0.5)) < 0.01


# ---- Altitude (bbox_height → down_m_s) ----

class TestAltitudeFromBbox:
    def test_at_target_bbox_zero_altitude(self, config):
        """Bbox at target height -> down_m_s == 0.0."""
        cmd = compute_velocity_command(
            _det(bh=config.target_bbox_height), config
        )
        assert cmd.down_m_s == 0.0

    def test_small_bbox_descend(self, config):
        """Small bbox (person far / too high) -> descend (positive down_m_s)."""
        cmd = compute_velocity_command(_det(bh=0.1), config)
        assert cmd.down_m_s > 0.0

    def test_large_bbox_climb(self, config):
        """Large bbox (person close / too low) -> climb (negative down_m_s)."""
        cmd = compute_velocity_command(_det(bh=0.6), config)
        assert cmd.down_m_s < 0.0

    def test_emergency_bbox_climb_and_reverse(self, config):
        """Bbox > max_bbox_height_safety -> emergency max climb + max backward."""
        cmd = compute_velocity_command(_det(bh=0.9), config)
        assert cmd.down_m_s == -config.max_climb_speed
        assert cmd.forward_m_s == -config.max_backward

    def test_yaw_only_zero_altitude(self):
        """Yaw-only mode -> down_m_s is always 0."""
        cfg = ControllerConfig(yaw_only=True)
        for bh in (0.1, 0.3, 0.6):
            cmd = compute_velocity_command(_det(bh=bh), cfg)
            assert cmd.down_m_s == 0.0, (
                f"yaw_only should produce zero altitude (bh={bh})"
            )


# ---- Forward/backward (center_y → forward_m_s) ----

class TestForward:
    def test_centered_zero_forward(self, config):
        """Person vertically centered (cy=0.5) -> no forward movement."""
        cmd = compute_velocity_command(
            _det(cy=config.target_center_y), config
        )
        assert cmd.forward_m_s == 0.0

    def test_above_center_approach(self, config):
        """Person above center (cy=0.2) -> approach (positive forward)."""
        cmd = compute_velocity_command(_det(cy=0.2), config)
        assert cmd.forward_m_s > 0.0

    def test_below_center_retreat(self, config):
        """Person below center (cy=0.8) -> retreat (negative forward)."""
        cmd = compute_velocity_command(_det(cy=0.8), config)
        assert cmd.forward_m_s < 0.0

    def test_forward_saturation(self, config):
        """Very far above center (cy=0.01) -> clamped to max_forward."""
        cmd = compute_velocity_command(_det(cy=0.01), config)
        assert cmd.forward_m_s <= config.max_forward + 0.01

    def test_backward_saturation(self, config):
        """Very far below center (cy=0.99) -> clamped to -max_backward."""
        cmd = compute_velocity_command(_det(cy=0.99), config)
        assert cmd.forward_m_s >= -config.max_backward - 0.01

    def test_dead_zone(self, config):
        """Small vertical offset within dead_zone_y_deg -> zero forward."""
        # dead_zone_y_deg=2.0 on vfov=41.0 means normalized offset < 2/41 ≈ 0.049
        small_offset = 0.01  # 0.01 * 41.0 = 0.41 deg < 2.0 deg dead zone
        cmd = compute_velocity_command(
            _det(cy=config.target_center_y + small_offset), config
        )
        assert cmd.forward_m_s == 0.0

    def test_right_always_zero_in_follow_mode(self, config):
        """right_m_s should always be zero in follow mode (no lateral movement)."""
        config.follow_mode = "follow"
        for cx in [0.1, 0.5, 0.9]:
            for cy in [0.1, 0.5, 0.9]:
                for bh in [0.1, 0.3, 0.6]:
                    cmd = compute_velocity_command(_det(cx=cx, cy=cy, bh=bh), config)
                    assert cmd.right_m_s == 0.0


# ---- Combined scenarios ----

class TestCombined:
    def test_perfectly_centered_at_target(self, config):
        """Target perfectly centered (cy=0.5) and at desired bbox height -> all zeros."""
        cmd = compute_velocity_command(
            _det(cx=0.5, cy=0.5, bh=config.target_bbox_height), config
        )
        assert cmd.forward_m_s == 0.0
        assert cmd.right_m_s == 0.0
        assert cmd.down_m_s == 0.0
        assert cmd.yawspeed_deg_s == 0.0

    def test_yaw_and_forward_active_together(self):
        """Target off-center horizontally and vertically -> both yaw and forward active."""
        config = ControllerConfig(dead_zone_deg=0.0, dead_zone_y_deg=0.0,
                                  yaw_only=False)
        cmd = compute_velocity_command(
            _det(cx=0.7, cy=0.2, bh=0.3), config
        )
        assert cmd.yawspeed_deg_s > 0.0    # right -> positive yaw
        assert cmd.forward_m_s > 0.0       # above center -> approach

    def test_custom_gains(self):
        """Custom gain values should scale the output proportionally."""
        cfg_low = ControllerConfig(
            kp_yaw=1.0, kp_forward=1.5,
            dead_zone_deg=0.0, dead_zone_y_deg=0.0,
            yaw_only=False,
            max_yawspeed=9999.0,
            max_forward=9999.0, max_backward=9999.0,
        )
        cfg_high = ControllerConfig(
            kp_yaw=2.0, kp_forward=3.0,
            dead_zone_deg=0.0, dead_zone_y_deg=0.0,
            yaw_only=False,
            max_yawspeed=9999.0,
            max_forward=9999.0, max_backward=9999.0,
        )
        # cy=0.3 -> above center -> positive forward (approach)
        det = _det(cx=0.65, cy=0.3, bh=0.3)
        cmd_low = compute_velocity_command(det, cfg_low)
        cmd_high = compute_velocity_command(det, cfg_high)

        assert abs(cmd_high.yawspeed_deg_s / cmd_low.yawspeed_deg_s - 2.0) < 0.01
        assert abs(cmd_high.forward_m_s / cmd_low.forward_m_s - 2.0) < 0.01


class TestSafetyAndFollowing:
    def test_yaw_only_keeps_yaw_and_disables_forward_and_down(self):
        """Yaw-only mode still tracks yaw but zeroes forward and down commands."""
        cfg = ControllerConfig(yaw_only=True, dead_zone_deg=0.0)
        cmd = compute_velocity_command(_det(cx=0.8, cy=0.2, bh=0.1), cfg)
        assert cmd.yawspeed_deg_s > 0.0
        assert cmd.forward_m_s == 0.0
        assert cmd.down_m_s == 0.0

    def test_search_spins_toward_last_seen_side(self):
        """When target is lost, search yaw direction should follow last known side.
        Forward should be zero during search."""
        cfg = ControllerConfig()
        last_right = _det(cx=0.8, bh=0.2)
        last_left = _det(cx=0.2, bh=0.2)
        cmd_right = compute_velocity_command(None, cfg, last_detection=last_right)
        cmd_left = compute_velocity_command(None, cfg, last_detection=last_left)
        assert cmd_right.yawspeed_deg_s > 0.0
        assert cmd_left.yawspeed_deg_s < 0.0
        # Search mode: no forward correction
        assert cmd_right.forward_m_s == 0.0
        assert cmd_left.forward_m_s == 0.0

    def test_search_wait_holds_previous_velocity(self):
        """Before active search, controller should hold last velocity."""
        cfg = ControllerConfig(yaw_only=False)
        hold = compute_velocity_command(_det(cx=0.7, cy=0.3, bh=0.3), cfg)
        cmd = compute_velocity_command(
            None,
            cfg,
            search_active=False,
            hold_velocity=hold,
        )
        assert cmd.forward_m_s == hold.forward_m_s
        assert cmd.down_m_s == hold.down_m_s
        assert cmd.yawspeed_deg_s == hold.yawspeed_deg_s


class TestConfigArgs:
    def test_log_verbosity_defaults_to_normal(self):
        cfg = ControllerConfig.from_args(SimpleNamespace())
        assert cfg.log_verbosity == "normal"

    def test_log_verbosity_is_read_from_args(self):
        cfg = ControllerConfig.from_args(SimpleNamespace(log_verbosity="debug"))
        assert cfg.log_verbosity == "debug"


# ---- Config validation ----

class TestConfigValidation:
    def test_default_config_is_valid(self):
        """Default config should pass validation."""
        ControllerConfig().validate()

    def test_min_altitude_must_be_less_than_max(self):
        """min_altitude >= max_altitude should raise ValueError."""
        with pytest.raises(ValueError, match="min_altitude"):
            ControllerConfig(min_altitude=25.0, max_altitude=20.0)

    def test_min_altitude_equals_max_is_invalid(self):
        with pytest.raises(ValueError, match="min_altitude"):
            ControllerConfig(min_altitude=10.0, max_altitude=10.0)

    def test_valid_altitude_range(self):
        """A valid altitude range should not raise."""
        ControllerConfig(min_altitude=1.0, max_altitude=50.0).validate()

    def test_target_center_y_must_be_in_0_1(self):
        """target_center_y outside (0, 1) should raise ValueError."""
        with pytest.raises(ValueError, match="target_center_y"):
            ControllerConfig(target_center_y=0.0)
        with pytest.raises(ValueError, match="target_center_y"):
            ControllerConfig(target_center_y=1.0)
        with pytest.raises(ValueError, match="target_center_y"):
            ControllerConfig(target_center_y=-0.1)

    def test_target_center_y_valid(self):
        ControllerConfig(target_center_y=0.5).validate()
        ControllerConfig(target_center_y=0.3).validate()


class TestForwardLowPass:
    """Tests for the center_y-based forward controller and the first-order
    low-pass (EMA) that attenuates pitch-induced oscillation."""

    def test_dead_zone_holds_zero(self):
        """Error smaller than dead_zone_y_deg keeps forward at 0."""
        cfg = ControllerConfig(
            yaw_only=False, dead_zone_y_deg=5.0, target_center_y=0.5,
        )
        # Small offset: 0.02 * 41.0 = 0.82 deg < 5.0 deg dead zone
        cmd = compute_velocity_command(_det(cy=0.52), cfg)
        assert cmd.forward_m_s == 0.0

    def test_breaks_out_of_dead_zone(self):
        """Error larger than dead zone produces signed P command."""
        cfg = ControllerConfig(
            yaw_only=False, dead_zone_y_deg=2.0, target_center_y=0.5,
        )
        # Person above center (cy=0.2) → approach (positive forward)
        cmd_far = compute_velocity_command(_det(cy=0.2), cfg)
        assert cmd_far.forward_m_s > 0.0

        # Person below center (cy=0.8) → retreat (negative forward)
        cmd_close = compute_velocity_command(_det(cy=0.8), cfg)
        assert cmd_close.forward_m_s < 0.0

    def test_p_command_clamped_to_max(self):
        """Large errors saturate at max_forward / max_backward."""
        cfg = ControllerConfig(
            yaw_only=False, dead_zone_y_deg=0.0, target_center_y=0.5,
            kp_forward=100.0, kp_backward=100.0, max_forward=1.0, max_backward=1.5,
        )
        cmd_approach = compute_velocity_command(_det(cy=0.01), cfg)   # far above center
        assert cmd_approach.forward_m_s == pytest.approx(1.0, abs=0.01)
        cmd_retreat = compute_velocity_command(_det(cy=0.99), cfg)    # far below center
        assert cmd_retreat.forward_m_s == pytest.approx(-1.5, abs=0.01)

    def test_ema_attenuates_step_input(self):
        """Low alpha produces slow convergence to a step input (via VelocityCommandAPI)."""
        import asyncio
        cfg = ControllerConfig(
            forward_alpha=0.07, max_forward=5.0, max_backward=5.0,
            smooth_forward=True, smooth_yaw=False, smooth_right=False, smooth_down=False,
        )
        api = VelocityCommandAPI(drone=None, config=cfg)
        from drone_follow.follow_api import VelocityCommand
        # Step from 0 → 1.0 m/s; after one send, output should be alpha * step = 0.07
        first = asyncio.run(api.send(VelocityCommand(1.0, 0.0, 0.0, 0.0)))
        assert first.forward_m_s == pytest.approx(0.07, abs=1e-6)
        # After many sends, converges toward the target
        for _ in range(100):
            result = asyncio.run(api.send(VelocityCommand(1.0, 0.0, 0.0, 0.0)))
        assert result.forward_m_s == pytest.approx(1.0, abs=0.01)

    def test_direction_reversal_is_smooth(self):
        """When input flips sign, EMA transitions through zero smoothly (via VelocityCommandAPI)."""
        import asyncio
        cfg = ControllerConfig(
            forward_alpha=0.2, max_forward=5.0, max_backward=5.0,
            smooth_forward=True, smooth_yaw=False, smooth_right=False, smooth_down=False,
        )
        api = VelocityCommandAPI(drone=None, config=cfg)
        from drone_follow.follow_api import VelocityCommand
        # Settle at +1.0
        for _ in range(100):
            asyncio.run(api.send(VelocityCommand(1.0, 0.0, 0.0, 0.0)))
        # Abrupt flip to -1.0 — output must pass through zero, not jump
        r = asyncio.run(api.send(VelocityCommand(-1.0, 0.0, 0.0, 0.0)))
        prev = r.forward_m_s
        for _ in range(10):
            r = asyncio.run(api.send(VelocityCommand(-1.0, 0.0, 0.0, 0.0)))
            nxt = r.forward_m_s
            # Each step should move toward -1.0 monotonically (no overshoot)
            assert nxt <= prev + 1e-9
            prev = nxt
        assert prev < 0.0  # crossed zero, now negative


class TestOrbitMode:
    def test_orbit_adds_lateral_velocity(self):
        """In orbit mode, tracking a target should produce lateral velocity."""
        cfg = ControllerConfig(follow_mode="orbit", orbit_speed_m_s=1.5, orbit_direction=1, yaw_only=False)
        cmd = compute_velocity_command(_det(cx=0.5, cy=0.5, bh=0.3), cfg)
        assert cmd.right_m_s == 1.5

    def test_orbit_ccw_negative_lateral(self):
        """Counter-clockwise orbit should produce negative lateral velocity."""
        cfg = ControllerConfig(follow_mode="orbit", orbit_speed_m_s=1.0, orbit_direction=-1, yaw_only=False)
        cmd = compute_velocity_command(_det(cx=0.5, cy=0.5, bh=0.3), cfg)
        assert cmd.right_m_s == -1.0

    def test_follow_mode_no_lateral(self):
        """In follow mode, there should be no lateral velocity."""
        cfg = ControllerConfig(follow_mode="follow", orbit_speed_m_s=2.0)
        cmd = compute_velocity_command(_det(cx=0.5, cy=0.5, bh=0.3), cfg)
        assert cmd.right_m_s == 0.0

    def test_search_mode_no_lateral_in_orbit(self):
        """In orbit mode, search (no detection) should have no lateral velocity."""
        cfg = ControllerConfig(follow_mode="orbit", orbit_speed_m_s=1.5)
        cmd = compute_velocity_command(None, cfg)
        assert cmd.right_m_s == 0.0

    def test_orbit_preserves_yaw_and_forward(self):
        """Orbit mode should still compute yaw and forward normally."""
        cfg = ControllerConfig(follow_mode="orbit", orbit_speed_m_s=1.0,
                               dead_zone_deg=0.0, dead_zone_y_deg=0.0, yaw_only=False)
        cmd = compute_velocity_command(_det(cx=0.7, cy=0.2, bh=0.3), cfg)
        assert cmd.yawspeed_deg_s > 0.0  # target right of center
        assert cmd.forward_m_s > 0.0     # above center -> approach
        assert cmd.right_m_s == 1.0      # lateral orbit velocity
