"""HTTP server for drone follow application.

Provides a REST API to control which tracked person the drone should follow.
The server is always available and provides status information.

Usage:
    The server starts automatically in all modes.

    POST /follow/<detection_id>
        Start following the person with the specified tracking ID.
        Returns: {"status": "success", "following_id": <id>}

    GET /status
        Get current tracking status.
        Returns: {"following_id": <id or null>, "last_seen": <timestamp or null>}

Example:
    curl -X POST http://localhost:8080/follow/42
    curl http://localhost:8080/status
"""

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from drone_follow.follow_api.state import FollowTargetState

LOGGER = logging.getLogger(__name__)


class FollowServerHandler(BaseHTTPRequestHandler):
    """HTTP request handler for follow server."""

    target_state: FollowTargetState = None
    shared_state: 'SharedDetectionState' = None
    reid_manager = None  # Optional ReIDManager
    ui_state = None  # Optional SharedUIState — used to look up bbox at lock time
    controller_config = None  # Optional ControllerConfig — receives target_bbox_height capture

    def log_message(self, format, *args):
        LOGGER.debug(format, *args)

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def _capture_bbox_for_id(self, detection_id):
        """Look up the detection's current bbox via UI state and write target_bbox_height.

        Returns the value actually written, or None if either the UI state or controller
        config is unavailable or the detection wasn't found in the latest UI snapshot.
        """
        if self.ui_state is None or self.controller_config is None:
            return None
        snapshot = self.ui_state.get_detections()
        for det in snapshot.get("detections", []):
            if det.get("id") == detection_id:
                bbox = det.get("bbox") or {}
                h = bbox.get("h")
                if h is None:
                    return None
                # Avoid an import cycle: import locally
                from drone_follow.pipeline_adapter.hailo_drone_detection_manager import (
                    capture_bbox_setpoint_from_height,
                )
                return capture_bbox_setpoint_from_height(self.controller_config, h, source="CLICK")
        return None

    def do_POST(self):
        if self.path in ("/follow/clear", "/follow/"):
            self.target_state.enter_auto_mode()
            if self.reid_manager is not None:
                self.reid_manager.clear()
            self._send_json({
                "status": "success",
                "following_id": None,
                "message": "Cleared target, returning to auto mode",
            })
            LOGGER.info("Cleared target, returning to auto mode")
        elif self.path.startswith("/follow/"):
            try:
                detection_id = int(self.path.split("/follow/")[1])
            except (ValueError, IndexError) as e:
                self.send_error(400, f"Invalid detection ID: {e}")
                return

            if self.shared_state is not None:
                available_ids = self.shared_state.get_available_ids()
                if detection_id not in available_ids:
                    self._send_json({
                        "status": "error",
                        "message": f"Detection ID {detection_id} not found in current frame",
                        "available_ids": list(available_ids),
                    }, status=404)
                    LOGGER.info("Detection ID %d not found. Available: %s", detection_id, available_ids)
                    return

            self.target_state.set_paused(False)
            self.target_state.set_target(detection_id)
            self.target_state.set_explicit_lock(True)
            # Capture the clicked person's current bbox as the distance setpoint so
            # the drone holds its current distance instead of converging on a fixed value.
            captured_h = self._capture_bbox_for_id(detection_id)
            self._send_json({"status": "success", "following_id": detection_id,
                             "target_bbox_height": captured_h})
            LOGGER.info("Now following detection ID: %d (bbox height %s)",
                        detection_id,
                        f"{captured_h:.3f}" if captured_h is not None else "n/a")
        else:
            self.send_error(404, "Not Found")

    def do_GET(self):
        if self.path == "/status":
            status = self.target_state.get_status()
            if self.shared_state is not None:
                status["available_ids"] = list(self.shared_state.get_available_ids())
            self._send_json(status)
        else:
            self.send_error(404, "Not Found")


class FollowServer:
    """HTTP server for follow target selection."""

    def __init__(self, target_state: FollowTargetState, shared_state: 'SharedDetectionState' = None,
                 host: str = "0.0.0.0", port: int = 8080, reid_manager=None,
                 ui_state=None, controller_config=None):
        self.target_state = target_state
        self.shared_state = shared_state
        self.host = host
        self.port = port
        self.reid_manager = reid_manager
        self.ui_state = ui_state
        self.controller_config = controller_config
        self.server = None
        self.thread = None

    def start(self):
        """Start the HTTP server in a background thread."""
        FollowServerHandler.target_state = self.target_state
        FollowServerHandler.shared_state = self.shared_state
        FollowServerHandler.reid_manager = self.reid_manager
        FollowServerHandler.ui_state = self.ui_state
        FollowServerHandler.controller_config = self.controller_config

        HTTPServer.allow_reuse_address = True
        self.server = HTTPServer((self.host, self.port), FollowServerHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        LOGGER.info("Started on http://%s:%d", self.host, self.port)

    def stop(self):
        """Stop the HTTP server."""
        if self.server:
            self.server.shutdown()
            LOGGER.info("Stopped")
