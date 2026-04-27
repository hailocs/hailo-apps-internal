"""Pure follow controller logic — no MAVSDK, no Hailo, no GStreamer dependencies.

Only depends on standard library + the types/config from this package.
"""

import math
from typing import Optional

from .types import Detection, VelocityCommand
from .config import ControllerConfig

__all__ = [
    "compute_velocity_command",
]


def _calculate_forward_speed(
    detection: Detection,
    config: ControllerConfig,
) -> float:
    """Signed square-root P controller on center_y error.

    Keeps the person vertically centred in the frame.  Symmetric to the yaw
    controller (center_x → yawspeed), but on the vertical/forward axis.

    Sign convention (fixed forward-facing camera, drone above person):
      person below centre (center_y > target) → too close → back up  (negative)
      person above centre (center_y < target) → too far  → approach  (positive)
    """
    if config.yaw_only or config.kp_forward == 0:
        return 0.0

    error_y_deg = (detection.center_y - config.target_center_y) * config.vfov

    if abs(error_y_deg) < config.dead_zone_y_deg:
        return 0.0

    # Person below centre → error positive → back up (negative forward)
    # Asymmetric gains: kp_backward for retreat, kp_forward for approach
    gain = config.kp_backward if error_y_deg > 0 else config.kp_forward
    raw = -math.copysign(gain * math.sqrt(abs(error_y_deg)), error_y_deg)
    return max(-config.max_backward, min(config.max_forward, raw))


def _calculate_altitude_speed(
    detection: Detection,
    config: ControllerConfig,
) -> float:
    """Plain P controller on bbox_height error → altitude command.

    Person too small → descend (positive down_m_s).
    Person too big  → climb   (negative down_m_s).

    Safety: bbox > max_bbox_height_safety → emergency max climb.
    Altitude floor/ceiling is enforced downstream in live_control_loop.
    """
    if config.yaw_only or config.kp_altitude == 0:
        return 0.0

    # Safety: bbox too large → emergency climb
    if detection.bbox_height > config.max_bbox_height_safety:
        return -config.max_climb_speed

    height_delta = config.target_bbox_height - detection.bbox_height
    dead_zone = (config.dead_zone_bbox_percent / 100.0) * config.target_bbox_height
    if abs(height_delta) < dead_zone:
        return 0.0

    # height_delta > 0: person too small → descend → positive down_m_s
    # height_delta < 0: person too big  → climb   → negative down_m_s
    raw = config.kp_altitude * height_delta
    return max(-config.max_climb_speed, min(config.max_climb_speed, raw))


def compute_velocity_command(
    detection: Optional[Detection],
    config: ControllerConfig,
    last_detection: Optional[Detection] = None,
    search_active: bool = True,
    hold_velocity: Optional[VelocityCommand] = None,
) -> VelocityCommand:
    """Compute a velocity command from the current detection and config.

    Control mapping:
      center_x    → yaw        (horizontal centering)
      center_y    → forward    (vertical centering)
      bbox_height → down       (distance via altitude)
    """
    # --- Search mode: no current detection ---
    if detection is None:
        if not search_active:
            return hold_velocity if hold_velocity is not None else VelocityCommand(0.0, 0.0, 0.0, 0.0)
        # Derive search direction from last seen position.
        search_direction = 1.0
        if last_detection is not None:
            search_direction = 1.0 if last_detection.center_x > 0.5 else -1.0
        return VelocityCommand(0.0, 0.0, 0.0, search_direction * config.search_yawspeed_slow)

    # --- Safety: bbox too large → emergency climb + reverse ---
    if not config.yaw_only and detection.bbox_height > config.max_bbox_height_safety:
        # Yaw still active during safety (keep tracking)
        error_x_deg = (detection.center_x - 0.5) * config.hfov
        if abs(error_x_deg) < config.dead_zone_deg:
            yawspeed = 0.0
        else:
            yawspeed = math.copysign(config.kp_yaw * math.sqrt(abs(error_x_deg)), error_x_deg)
        yawspeed = max(-config.max_yawspeed, min(config.max_yawspeed, yawspeed))
        right = config.orbit_speed_m_s * config.orbit_direction if config.follow_mode == "orbit" else 0.0
        return VelocityCommand(-config.max_backward, right, -config.max_climb_speed, yawspeed)

    # --- Tracking mode ---
    # Yaw: signed square-root response (horizontal centering)
    error_x_deg = (detection.center_x - 0.5) * config.hfov
    if abs(error_x_deg) < config.dead_zone_deg:
        yawspeed = 0.0
    else:
        yawspeed = math.copysign(config.kp_yaw * math.sqrt(abs(error_x_deg)), error_x_deg)
    yawspeed = max(-config.max_yawspeed, min(config.max_yawspeed, yawspeed))

    # Forward: signed square-root response (vertical centering)
    forward = _calculate_forward_speed(detection, config)

    # Altitude: plain P on bbox_height error
    down = _calculate_altitude_speed(detection, config)

    # Lateral: orbit mode only
    right = config.orbit_speed_m_s * config.orbit_direction if config.follow_mode == "orbit" else 0.0
    return VelocityCommand(forward, right, down, yawspeed)
