"""Pure domain types for drone follow — no third-party dependencies."""

from dataclasses import dataclass


@dataclass
class VelocityCommand:
    """Velocity command in the drone body frame.

    This is a pure domain type that replaces direct use of
    mavsdk.offboard.VelocityBodyYawspeed in the follow logic, keeping
    the follow layer free of MAVSDK dependencies.
    """
    forward_m_s: float
    right_m_s: float
    down_m_s: float
    yawspeed_deg_s: float


@dataclass
class Detection:
    """A single person detection in normalized image coordinates."""
    label: str
    confidence: float
    center_x: float      # 0.0 to 1.0
    center_y: float      # 0.0 to 1.0
    bbox_height: float   # 0.0 to 1.0
    timestamp: float
