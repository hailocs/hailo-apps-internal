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


def _calculate_distance_speed(
    detection: Detection,
    config: ControllerConfig,
) -> float:
    """Distance-error P controller → forward command.

    Uses ``(target_bbox / bbox) - 1`` as the proportional distance error.
    Since bbox ∝ 1/distance, this factor *is* the relative distance error:
    a person at 2× the target distance gives factor=1 regardless of absolute
    bbox size, so the response is scale-invariant — small far-away bboxes
    produce strong forward commands instead of the weak ones a linear
    bbox-delta P would yield.

    Sign convention:
      bbox << target (person far)   → factor positive → forward (positive)
      bbox >> target (person close) → factor negative → backup  (negative)

    ``dead_zone_bbox_percent`` is interpreted as the factor threshold in
    percent (10 → |factor| < 0.1, i.e. ±10% relative bbox error from target).
    """
    if config.yaw_only:
        return 0.0

    if detection.bbox_height <= 0:
        return 0.0

    factor = (config.target_bbox_height / detection.bbox_height) - 1.0
    dead_zone = config.dead_zone_bbox_percent / 100.0
    if abs(factor) < dead_zone:
        return 0.0

    # Asymmetric: retreat (factor<0, person too close) uses kp_distance_back so
    # it saturates max_backward before bbox reaches max_bbox_height_safety, the
    # binary "panic" threshold. Approach (factor>0) uses the gentler kp_distance.
    gain = config.kp_distance_back if factor < 0 else config.kp_distance
    if gain == 0:
        return 0.0
    raw = gain * factor
    return max(-config.max_backward, min(config.max_forward, raw))


def _apply_frame_edge_safety(
    forward: float,
    detection: Detection,
    config: ControllerConfig,
) -> float:
    """Bias forward away from the top/bottom frame edges using a linear gradient.

    Two stacked zones per edge, each as wide as the margin:

      pre-margin fade zone (just outside the margin) — the natural command in
        the offending direction is linearly scaled to 0 as the bbox approaches
        the margin. Other-direction natural is left untouched.
      safety push zone (inside the margin) — force ramps from 0 at the inner
        boundary of the margin to ±max at the frame edge, combined with the
        (already-faded) natural command via min/max so it can only push more
        in the protective direction.

    The fade zone removes the discontinuity at the margin boundary: by the
    time the bbox edge reaches the margin, the offending natural command is
    already 0, so equilibrium sits at the boundary instead of bouncing across
    it (the "too small → approach → at bottom → back off → too small" loop).

    bottom edge in bottom margin → person too close / falling out → backward
    top    edge in top    margin → person too far / sliding off  → forward
    Disabled when ``yaw_only`` is set or the corresponding margin is 0.
    """
    if config.yaw_only:
        return forward
    bbox_top = detection.center_y - detection.bbox_height / 2
    bbox_bottom = detection.center_y + detection.bbox_height / 2

    if config.bottom_margin_safety > 0:
        margin = config.bottom_margin_safety
        # Fade positive (approach) natural command across [1-2m, 1-m].
        if forward > 0:
            fade_depth = bbox_bottom - (1.0 - 2.0 * margin)
            if fade_depth > 0:
                fade = max(0.0, 1.0 - fade_depth / margin)
                forward *= fade
        # Safety push inside the margin.
        depth = bbox_bottom - (1.0 - margin)
        if depth > 0:
            ratio = min(depth / margin, 1.0)
            forward = min(forward, -ratio * config.max_backward)

    if config.top_margin_safety > 0:
        margin = config.top_margin_safety
        # Fade negative (retreat) natural command across [m, 2m].
        if forward < 0:
            fade_depth = (2.0 * margin) - bbox_top
            if fade_depth > 0:
                fade = max(0.0, 1.0 - fade_depth / margin)
                forward *= fade
        # Safety push inside the margin.
        depth = margin - bbox_top
        if depth > 0:
            ratio = min(depth / margin, 1.0)
            forward = max(forward, ratio * config.max_forward)

    return forward


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
      bbox_height → forward    (distance control)
      down        → 0          (altitude held by PX4 in live_control_loop)
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

    # --- Safety: bbox too large → emergency reverse ---
    if not config.yaw_only and detection.bbox_height > config.max_bbox_height_safety:
        # Yaw still active during safety (keep tracking)
        error_x_deg = (detection.center_x - 0.5) * config.hfov
        if abs(error_x_deg) < config.dead_zone_deg:
            yawspeed = 0.0
        else:
            yawspeed = math.copysign(config.kp_yaw * math.sqrt(abs(error_x_deg)), error_x_deg)
        yawspeed = max(-config.max_yawspeed, min(config.max_yawspeed, yawspeed))
        # Altitude held by PX4 in live_control_loop — don't override down here.
        return VelocityCommand(-config.max_backward, 0.0, 0.0, yawspeed)

    # --- Tracking mode ---
    # Yaw: signed square-root response (horizontal centering)
    error_x_deg = (detection.center_x - 0.5) * config.hfov
    if abs(error_x_deg) < config.dead_zone_deg:
        yawspeed = 0.0
    else:
        yawspeed = math.copysign(config.kp_yaw * math.sqrt(abs(error_x_deg)), error_x_deg)
    yawspeed = max(-config.max_yawspeed, min(config.max_yawspeed, yawspeed))

    forward = _calculate_distance_speed(detection, config)

    # Frame-edge safety: gradient bias that pushes forward away from top/bottom
    # frame edges as the bbox creeps into the margin (combined with natural cmd).
    forward = _apply_frame_edge_safety(forward, detection, config)

    return VelocityCommand(forward, 0.0, 0.0, yawspeed)
