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
    """Default config with yaw_only=False so distance-mode forward + frame-edge
    safety can fire in the tests that exercise them."""
    return ControllerConfig(yaw_only=False)


# ---- No detection (search mode) ----

class TestSearchMode:
    def test_no_detection_returns_search_yaw(self, config):
        cmd = compute_velocity_command(None, config)
        assert cmd.yawspeed_deg_s == config.search_yawspeed_slow

    def test_no_detection_zero_velocity(self, config):
        cmd = compute_velocity_command(None, config)
        assert cmd.forward_m_s == 0.0
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


# ---- Combined scenarios ----

class TestCombined:
    def test_perfectly_centered_at_target(self, config):
        """Target perfectly centered (cy=0.5) and at desired bbox height -> all zeros."""
        cmd = compute_velocity_command(
            _det(cx=0.5, cy=0.5, bh=config.target_bbox_height), config
        )
        assert cmd.forward_m_s == 0.0
        assert cmd.down_m_s == 0.0
        assert cmd.yawspeed_deg_s == 0.0

    def test_yaw_and_forward_active_together(self):
        """Target off-center horizontally with bbox below target -> both yaw and forward active."""
        config = ControllerConfig(dead_zone_deg=0.0, yaw_only=False)
        # bh=0.15 is well below target_bbox_height=0.3 → factor>0 → forward
        cmd = compute_velocity_command(
            _det(cx=0.7, cy=0.5, bh=0.15), config
        )
        assert cmd.yawspeed_deg_s > 0.0    # right -> positive yaw
        assert cmd.forward_m_s > 0.0       # bbox too small -> approach


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

    def test_target_altitude_must_be_at_most_max_altitude(self):
        with pytest.raises(ValueError, match="target_altitude"):
            ControllerConfig(target_altitude=5.0, max_altitude=4.0)

    def test_target_altitude_at_max_is_valid(self):
        ControllerConfig(target_altitude=4.0, max_altitude=4.0).validate()

    def test_target_altitude_below_min_raises(self):
        with pytest.raises(ValueError, match="target_altitude"):
            ControllerConfig(target_altitude=1.0, min_altitude=2.0, max_altitude=4.0)


class TestForwardLowPass:
    """Tests for the first-order low-pass (EMA) that attenuates
    pitch-induced oscillation in forward velocity."""

    def test_ema_attenuates_step_input(self):
        """Low alpha produces slow convergence to a step input (via VelocityCommandAPI)."""
        import asyncio
        cfg = ControllerConfig(
            forward_alpha=0.07, max_forward=5.0, max_backward=5.0,
            smooth_forward=True, smooth_yaw=False, smooth_down=False,
        )
        api = VelocityCommandAPI(drone=None, config=cfg)
        from drone_follow.follow_api import VelocityCommand
        # Step from 0 → 1.0 m/s; after one send, output should be alpha * step = 0.07
        first = asyncio.run(api.send(VelocityCommand(1.0, 0.0, 0.0)))
        assert first.forward_m_s == pytest.approx(0.07, abs=1e-6)
        # After many sends, converges toward the target
        for _ in range(100):
            result = asyncio.run(api.send(VelocityCommand(1.0, 0.0, 0.0)))
        assert result.forward_m_s == pytest.approx(1.0, abs=0.01)

    def test_direction_reversal_is_smooth(self):
        """When input flips sign, EMA transitions through zero smoothly (via VelocityCommandAPI)."""
        import asyncio
        cfg = ControllerConfig(
            forward_alpha=0.2, max_forward=5.0, max_backward=5.0,
            smooth_forward=True, smooth_yaw=False, smooth_down=False,
        )
        api = VelocityCommandAPI(drone=None, config=cfg)
        from drone_follow.follow_api import VelocityCommand
        # Settle at +1.0
        for _ in range(100):
            asyncio.run(api.send(VelocityCommand(1.0, 0.0, 0.0)))
        # Abrupt flip to -1.0 — output must pass through zero, not jump
        r = asyncio.run(api.send(VelocityCommand(-1.0, 0.0, 0.0)))
        prev = r.forward_m_s
        for _ in range(10):
            r = asyncio.run(api.send(VelocityCommand(-1.0, 0.0, 0.0)))
            nxt = r.forward_m_s
            # Each step should move toward -1.0 monotonically (no overshoot)
            assert nxt <= prev + 1e-9
            prev = nxt
        assert prev < 0.0  # crossed zero, now negative


class TestDistanceForward:
    """bbox_height drives forward speed (distance control). Altitude is held
    by PX4 in live_control_loop, so the controller emits down=0."""

    def test_at_target_bbox_zero_forward(self, config):
        """Bbox at target -> no forward command."""
        cmd = compute_velocity_command(_det(bh=config.target_bbox_height), config)
        assert cmd.forward_m_s == 0.0
        assert cmd.down_m_s == 0.0

    def test_small_bbox_approaches(self, config):
        """Person far (bbox < target) -> forward (positive)."""
        cmd = compute_velocity_command(_det(bh=0.1), config)
        assert cmd.forward_m_s > 0.0
        assert cmd.down_m_s == 0.0

    def test_large_bbox_retreats(self, config):
        """Person close (bbox > target) -> backup (negative)."""
        cmd = compute_velocity_command(_det(bh=0.6), config)
        assert cmd.forward_m_s < 0.0
        assert cmd.down_m_s == 0.0

    def test_center_y_is_ignored(self, config):
        """center_y must not influence forward (within frame-edge safety
        margins — see TestFrameEdgeSafety for the edges)."""
        # bh=0.3, top_margin=bottom_margin=0.05 by default → safe cy ∈ [0.20, 0.80]
        cmd_top = compute_velocity_command(
            _det(cy=0.25, bh=config.target_bbox_height), config
        )
        cmd_bot = compute_velocity_command(
            _det(cy=0.75, bh=config.target_bbox_height), config
        )
        assert cmd_top.forward_m_s == 0.0
        assert cmd_bot.forward_m_s == 0.0

    def test_altitude_always_zero(self, config):
        """down_m_s must remain 0 across the bbox range."""
        for bh in (0.05, 0.2, config.target_bbox_height, 0.5, 0.7):
            cmd = compute_velocity_command(_det(bh=bh), config)
            assert cmd.down_m_s == 0.0, f"down should be 0 (bh={bh})"

    def test_emergency_bbox_no_climb(self, config):
        """Bbox > safety threshold -> max backward but no emergency climb."""
        cmd = compute_velocity_command(_det(bh=0.9), config)
        assert cmd.forward_m_s == -config.max_backward
        assert cmd.down_m_s == 0.0

    def test_clamped_to_max_forward(self):
        """Very small bbox with a high gain should saturate at max_forward."""
        cfg = ControllerConfig(yaw_only=False, kp_distance=100.0)  # force saturation
        cmd = compute_velocity_command(_det(bh=0.001), cfg)
        assert cmd.forward_m_s == cfg.max_forward

    def test_yaw_only_overrides_mode(self):
        """yaw_only=True still wins -> all axes zero except yaw."""
        cfg = ControllerConfig(yaw_only=True, dead_zone_deg=0.0)
        cmd = compute_velocity_command(_det(cx=0.8, bh=0.1), cfg)
        assert cmd.forward_m_s == 0.0
        assert cmd.down_m_s == 0.0
        assert cmd.yawspeed_deg_s > 0.0

    def test_dead_zone_holds_zero(self, config):
        """Bbox within the bbox dead zone -> no forward command."""
        # Distance-mode dead zone is interpreted as |factor| < dead_zone_bbox_percent/100.
        # bbox = target * 1.05 → factor = 1/1.05 - 1 ≈ -0.048, well inside 0.10.
        cmd = compute_velocity_command(
            _det(bh=config.target_bbox_height * 1.05), config
        )
        assert cmd.forward_m_s == 0.0

    def test_asymmetric_retreat_uses_kp_distance_back(self):
        """Retreat (factor<0) uses kp_distance_back; approach uses kp_distance.

        With kp_distance=1.0, kp_distance_back=3.0 and target=0.3:
          bh=0.6 → factor=0.3/0.6-1 = -0.5 → raw = 3.0 * -0.5 = -1.5 (retreat)
          bh=0.2 → factor=0.3/0.2-1 = +0.5 → raw = 1.0 * +0.5 = +0.5 (approach)
        Same |factor|, different magnitudes thanks to the asymmetry.
        """
        cfg = ControllerConfig(
            yaw_only=False, target_bbox_height=0.3,
            kp_distance=1.0, kp_distance_back=3.0,
            max_forward=5.0, max_backward=5.0, dead_zone_bbox_percent=0.0,
            top_margin_safety=0.0, bottom_margin_safety=0.0,
        )
        retreat = compute_velocity_command(_det(bh=0.6), cfg)
        approach = compute_velocity_command(_det(bh=0.2), cfg)
        assert retreat.forward_m_s == pytest.approx(-1.5, abs=1e-6)
        assert approach.forward_m_s == pytest.approx(0.5, abs=1e-6)
        # Retreat is 3× as aggressive as approach for the same |factor|.
        assert abs(retreat.forward_m_s) == pytest.approx(3.0 * approach.forward_m_s, abs=1e-6)

    def test_forward_below_deadband_clamped_to_zero(self):
        cfg = ControllerConfig(
            yaw_only=False, target_bbox_height=0.30,
            kp_distance=1.0, kp_distance_back=1.0,
            top_margin_safety=0.0, bottom_margin_safety=0.0,
            dead_zone_bbox_percent=0.0,
            forward_velocity_deadband=0.10,
        )
        # bbox=0.297 → factor = 0.30/0.297 - 1 ≈ 0.010, raw = 0.010 m/s, well under 0.10 deadband
        cmd = compute_velocity_command(_det(bh=0.297), cfg)
        assert cmd.forward_m_s == 0.0

    def test_forward_above_deadband_passes_through(self):
        cfg = ControllerConfig(
            yaw_only=False, target_bbox_height=0.30,
            kp_distance=1.0, kp_distance_back=1.0,
            top_margin_safety=0.0, bottom_margin_safety=0.0,
            dead_zone_bbox_percent=0.0,
            forward_velocity_deadband=0.05,
        )
        # bbox=0.20 → factor = 0.50, raw = 0.50 m/s ≫ 0.05 deadband
        cmd = compute_velocity_command(_det(bh=0.20), cfg)
        assert cmd.forward_m_s == pytest.approx(0.5, abs=1e-6)

    def test_emergency_safety_unaffected_by_deadband(self):
        """The bbox > max_bbox_height_safety branch returns max_backward;
        deadband must not interfere."""
        cfg = ControllerConfig(
            yaw_only=False, target_bbox_height=0.30,
            forward_velocity_deadband=10.0,  # absurdly high
        )
        cmd = compute_velocity_command(_det(bh=0.95), cfg)  # > 0.8 safety
        assert cmd.forward_m_s == -cfg.max_backward


class TestFrameEdgeSafety:
    """Top/bottom frame margins apply a gradient backward/forward bias as the
    bbox edge enters the margin. Force ramps linearly from 0 (at the inner
    boundary) to ±max (at the frame edge), and is combined with the natural
    command — only ever pushing more in the protective direction."""

    def _cfg(self, **overrides):
        # target_bbox_height pinned to 0.3 so the per-test bbox math
        # (factor = 0.3/bh - 1) below stays valid regardless of the package
        # default for target_bbox_height.
        # kp_distance_back mirrors kp_distance unless explicitly overridden,
        # so the retreat-direction math in these tests stays symmetric to the
        # approach side (these tests pre-date asymmetric retreat).
        defaults = dict(yaw_only=False, target_bbox_height=0.3,
                        top_margin_safety=0.05, bottom_margin_safety=0.05)
        defaults.update(overrides)
        defaults.setdefault("kp_distance_back", defaults.get("kp_distance", 1.0))
        return ControllerConfig(**defaults)

    def test_bottom_edge_full_breach_max_backward(self):
        cfg = self._cfg()
        # cy=0.95, bh=0.2 -> bottom = 1.05 (well past 1 - 0.05 = 0.95)
        # depth=0.10, ratio=clamp(0.10/0.05)=1.0 -> -max_backward
        cmd = compute_velocity_command(_det(cy=0.95, bh=0.2), cfg)
        assert cmd.forward_m_s == -cfg.max_backward

    def test_top_edge_full_breach_max_forward(self):
        cfg = self._cfg()
        # cy=0.05, bh=0.2 -> top = -0.05 (past 0.05)
        # depth=0.10, ratio=1.0 -> +max_forward
        cmd = compute_velocity_command(_det(cy=0.05, bh=0.2), cfg)
        assert cmd.forward_m_s == cfg.max_forward

    def test_bottom_partial_breach_proportional(self):
        """Bottom margin partially entered → gradient backward force."""
        cfg = self._cfg(kp_distance=2.0)
        # cy=0.93, bh=0.06 -> bottom=0.96 → depth=0.01, ratio=0.01/0.05=0.2
        # safety = -0.2 * 3 = -0.6
        # natural: factor=0.3/0.06-1=4.0, raw=2*4=8 → clamps to max_forward=2.0 (forward)
        # combined: min(2.0, -0.6) = -0.6  (safety wins, more protective)
        cmd = compute_velocity_command(_det(cy=0.93, bh=0.06), cfg)
        assert cmd.forward_m_s == pytest.approx(-0.2 * cfg.max_backward, abs=1e-6)

    def test_top_partial_breach_proportional(self):
        """Top margin partially entered → gradient forward force when natural is weaker."""
        cfg = self._cfg(kp_distance=1.0)
        # cy=0.165, bh=0.25 -> top=0.04, depth=0.05-0.04=0.01, ratio=0.2, safety=+0.4
        # natural: factor=0.3/0.25-1=0.2, raw=1.0*0.2=0.2 (forward, weaker)
        # combined: max(0.2, 0.4) = 0.4
        cmd = compute_velocity_command(_det(cy=0.165, bh=0.25), cfg)
        assert cmd.forward_m_s == pytest.approx(0.2 * cfg.max_forward, abs=1e-6)

    def test_natural_kept_when_more_protective_than_gradient(self):
        """If natural cmd already pushes harder in the protective direction, keep it."""
        cfg = self._cfg(kp_distance=2.0)
        # cy=0.71, bh=0.5 -> bottom=0.96, depth=0.01, ratio=0.2, safety=-0.6
        # natural: factor=0.3/0.5-1=-0.4, raw=2*-0.4=-0.8 (backward, stronger)
        # combined: min(-0.8, -0.6) = -0.8 (natural wins)
        cmd = compute_velocity_command(_det(cy=0.71, bh=0.5), cfg)
        assert cmd.forward_m_s == pytest.approx(-0.8, abs=1e-6)

    def test_no_breach_uses_normal_controller(self):
        cfg = self._cfg()
        # Centered, target bbox -> 0; no edge breach
        cmd = compute_velocity_command(_det(cy=0.5, bh=cfg.target_bbox_height), cfg)
        assert cmd.forward_m_s == 0.0

    def test_disabled_when_margin_zero(self):
        cfg = self._cfg(top_margin_safety=0.0, bottom_margin_safety=0.0)
        # Bbox bottom past frame bottom — without safety, normal controller runs.
        # bbox=0.2 < target=0.3 -> normal controller commands forward.
        cmd = compute_velocity_command(_det(cy=0.95, bh=0.2), cfg)
        assert cmd.forward_m_s > 0.0

    def test_yaw_only_disables_safety(self):
        cfg = ControllerConfig(yaw_only=True,
                               top_margin_safety=0.05, bottom_margin_safety=0.05,
                               dead_zone_deg=0.0)
        cmd = compute_velocity_command(_det(cx=0.5, cy=0.95, bh=0.2), cfg)
        assert cmd.forward_m_s == 0.0

    def test_emergency_bbox_overrides_edge_safety(self):
        """bbox_height > max_bbox_height_safety still wins over edge margins."""
        cfg = self._cfg()
        # bh=0.9 triggers emergency reverse path before tracking branch
        cmd = compute_velocity_command(_det(cy=0.5, bh=0.9), cfg)
        assert cmd.forward_m_s == -cfg.max_backward

    # --- Pre-margin fade zone (anti-oscillation) -----------------------------

    def test_bottom_fade_outside_margin_scales_approach(self):
        """In the fade zone just outside the bottom margin, positive natural
        forward is linearly scaled toward zero — preventing the chatter loop
        where bbox-too-small commanded approach but bbox-at-bottom commanded
        backward right next to it."""
        cfg = self._cfg(bottom_margin_safety=0.1, kp_distance=2.0)
        # bbox_bottom = 0.85 → halfway through fade zone [0.80, 0.90]
        # natural: factor=0.3/0.20-1=0.5, raw=2*0.5=1.0; fade=1-(0.85-0.80)/0.10=0.5 → 0.5
        # bbox_bottom < 1-margin (=0.90), no safety push
        cmd = compute_velocity_command(_det(cy=0.75, bh=0.20), cfg)
        assert cmd.forward_m_s == pytest.approx(0.5, abs=1e-6)

    def test_bottom_fade_at_margin_boundary_kills_approach(self):
        """At the inner edge of the bottom margin, natural approach is fully
        faded to 0 *and* safety push is still 0 — equilibrium with no
        oscillation across the boundary."""
        cfg = self._cfg(bottom_margin_safety=0.1, kp_distance=2.0)
        # bbox_bottom = 0.90 (margin entry), fade=1-(0.10/0.10)=0.0 → 0
        # safety: depth=0.0, no push
        cmd = compute_velocity_command(_det(cy=0.85, bh=0.10), cfg)
        assert cmd.forward_m_s == pytest.approx(0.0, abs=1e-6)

    def test_bottom_fade_does_not_touch_backward_natural(self):
        """The fade zone only damps the *offending* direction. A natural
        backward command (person too close) survives the bottom fade zone
        intact."""
        cfg = self._cfg(bottom_margin_safety=0.1, kp_distance=2.0)
        # bbox_bottom = 0.85 (in fade zone). bh=0.5 → factor=0.3/0.5-1=-0.4, raw=-0.8
        # Negative natural is not faded; no safety push (outside margin).
        cmd = compute_velocity_command(_det(cy=0.60, bh=0.50), cfg)
        assert cmd.forward_m_s == pytest.approx(-0.8, abs=1e-6)

    def test_top_fade_outside_margin_scales_retreat(self):
        """Symmetric: in the fade zone just outside the top margin, negative
        natural backward is linearly scaled toward zero."""
        cfg = self._cfg(top_margin_safety=0.1, kp_distance=2.0)
        # bbox_top = 0.15 → halfway through fade zone [0.10, 0.20]
        # natural: factor=0.3/0.5-1=-0.4, raw=-0.8; fade=1-(0.20-0.15)/0.10=0.5 → -0.4
        # bbox_top > margin (=0.10), no safety push
        cmd = compute_velocity_command(_det(cy=0.40, bh=0.50), cfg)
        assert cmd.forward_m_s == pytest.approx(-0.4, abs=1e-6)

    def test_top_fade_does_not_touch_forward_natural(self):
        """The top fade zone only damps backward natural; a forward natural
        command (person too small) survives it intact."""
        cfg = self._cfg(top_margin_safety=0.1, kp_distance=2.0)
        # bbox_top = 0.15 (in fade zone). bh=0.1 → factor=2.0, raw=4 → clamps to max_forward=2.0
        # Positive natural is not faded; no safety push.
        cmd = compute_velocity_command(_det(cy=0.20, bh=0.10), cfg)
        assert cmd.forward_m_s == pytest.approx(cfg.max_forward, abs=1e-6)


