"""Drone Follow — visual-servoing pipeline app for Hailo AI processors.

Architecture:
    follow_api/         Pure domain logic (types, config, state, controller math)
    drone_api/          MAVSDK flight controller adapter
    pipeline_adapter/   Hailo/GStreamer pipeline adapter + ByteTracker
    servers/            HTTP servers (follow target API, web UI)
    tools/              Standalone utilities (video bridge)
    drone_follow_app.py Composition root and CLI entrypoint
"""

from .follow_api import (
    Detection,
    VelocityCommand,
    SharedDetectionState,
    ControllerConfig,
    compute_velocity_command,
)

# Keep package import lightweight for tests/environments that don't have
# optional runtime deps (e.g. hailo, GStreamer).
try:
    from .pipeline_adapter import create_app
except ImportError:  # pragma: no cover - optional runtime dependencies
    create_app = None

try:
    from .servers import SharedUIState, WebServer
except ImportError:  # pragma: no cover - optional runtime dependencies
    SharedUIState = None
    WebServer = None

__all__ = [
    "Detection",
    "VelocityCommand",
    "SharedDetectionState",
    "ControllerConfig",
    "compute_velocity_command",
    "create_app",
    "SharedUIState",
    "WebServer",
]
