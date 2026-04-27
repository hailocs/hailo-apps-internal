"""servers — HTTP servers and bridges for drone follow application.

FollowServer: REST API for target selection.
WebServer: Web UI with MJPEG stream and interactive bounding boxes.
OpenHDBridge: UDP bridge for controlling params via OpenHD MAVLink settings.
"""

from .follow_server import FollowServer
from .openhd_bridge import OpenHDBridge
from .web_server import SharedUIState, WebServer

__all__ = [
    "FollowServer",
    "OpenHDBridge",
    "SharedUIState",
    "WebServer",
]
