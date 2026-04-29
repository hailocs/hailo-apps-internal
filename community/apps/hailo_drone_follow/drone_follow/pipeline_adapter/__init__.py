"""pipeline_adapter — Hailo/GStreamer pipeline adapters.

All Hailo and GStreamer imports are confined to this package.
Other modules receive detections as pure Detection objects via callbacks.
"""

def create_app(*args, **kwargs):
    from .hailo_drone_detection_manager import create_app as _create_app
    return _create_app(*args, **kwargs)

from .tracker_factory import add_tracker_args

__all__ = [
    "create_app",
    "add_tracker_args",
]
