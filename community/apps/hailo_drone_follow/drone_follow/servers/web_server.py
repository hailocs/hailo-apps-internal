"""
Web server for drone follow UI.

Serves a React UI with live MJPEG video stream and interactive bounding boxes.
Detections are synchronized with video frames via atomic snapshots and SSE.

Architecture:
    SharedUIState receives data from two GStreamer sources:
        1. app_callback (identity element) -> detection metadata
        2. appsink callback (JPEG branch) -> encoded JPEG frames

    When a JPEG frame arrives (update_frame), the current detections are
    atomically snapshotted alongside it.  The SSE endpoint pushes these
    paired snapshots so the frontend always renders bboxes matching the
    displayed frame.

    WebServer (stdlib ThreadingHTTPServer) serves:
        GET  /api/video              -> MJPEG stream
        GET  /api/detections/stream  -> SSE detection stream (frame-synced)
        GET  /api/detections         -> JSON detection list (polling fallback)
        POST /api/follow/<id>        -> set follow target
        POST /api/follow/clear       -> clear target
        GET  /api/status             -> current status
        GET  /*                      -> React static build (SPA fallback)
"""

import json
import logging
import os
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

LOGGER = logging.getLogger(__name__)


class SharedUIState:
    """Thread-safe state shared between GStreamer callbacks and the web server."""

    def __init__(self):
        self._lock = threading.Lock()
        self._detections: list = []
        self._following_id: Optional[int] = None
        self._paused: bool = False
        self._frame_jpeg: Optional[bytes] = None
        self._frame_snapshot: Optional[dict] = None
        self._velocity = {
            "forward_m_s": 0.0,
            "down_m_s": 0.0,
            "yawspeed_deg_s": 0.0,
            "mode": "IDLE",
            "ts": time.time(),
        }
        self._perf = {}
        self._frame_event = threading.Event()
        self._logs: deque = deque(maxlen=200)
        self._log_counter: int = 0

    def update_detections(self, detections: list, following_id: Optional[int] = None,
                          paused: bool = False):
        """Called from app_callback with detection metadata."""
        with self._lock:
            self._detections = detections
            self._following_id = following_id
            self._paused = paused

    def update_frame(self, jpeg_bytes: bytes):
        """Called from appsink callback with pre-encoded JPEG bytes.

        Atomically snapshots the current detections alongside the frame
        so the SSE endpoint can push frame-synced bounding boxes.
        """
        with self._lock:
            self._frame_jpeg = jpeg_bytes
            self._frame_snapshot = {
                "detections": list(self._detections),
                "following_id": self._following_id,
                "paused": self._paused,
                "velocity": dict(self._velocity),
                "perf": dict(self._perf),
            }
        self._frame_event.set()
        self._frame_event.clear()

    def get_detections(self) -> dict:
        """Return current detections and following state."""
        with self._lock:
            return {
                "detections": list(self._detections),
                "following_id": self._following_id,
                "paused": self._paused,
                "velocity": dict(self._velocity),
                "perf": dict(self._perf),
            }

    def update_perf(self, perf: dict):
        """Called from pipeline callback with performance metrics."""
        with self._lock:
            self._perf = perf

    def update_velocity(self, forward_m_s: float, down_m_s: float, yawspeed_deg_s: float, mode: str, right_m_s: float = 0.0):
        """Called from control loop to expose current command velocity in UI."""
        with self._lock:
            self._velocity = {
                "forward_m_s": float(forward_m_s),
                "right_m_s": float(right_m_s),
                "down_m_s": float(down_m_s),
                "yawspeed_deg_s": float(yawspeed_deg_s),
                "mode": str(mode),
                "ts": time.time(),
            }

    def push_log(self, message: str):
        """Append a log message to the UI log buffer (thread-safe).

        The caller is responsible for also logging via LOGGER if desired.
        """
        with self._lock:
            self._log_counter += 1
            self._logs.append({
                "id": self._log_counter,
                "ts": time.time(),
                "msg": message,
            })

    def get_logs(self, since_id: int = 0) -> list:
        """Return log entries with id > since_id."""
        with self._lock:
            return [entry for entry in self._logs if entry["id"] > since_id]

    def wait_frame(self, timeout: float = 1.0) -> Optional[bytes]:
        """Block until a new frame is available (for MJPEG streaming)."""
        self._frame_event.wait(timeout=timeout)
        with self._lock:
            return self._frame_jpeg

    def wait_frame_with_detections(self, timeout: float = 1.0):
        """Block until a new frame; return (jpeg_bytes, snapshot_dict)."""
        self._frame_event.wait(timeout=timeout)
        with self._lock:
            return self._frame_jpeg, self._frame_snapshot


class _WebHandler(BaseHTTPRequestHandler):
    """HTTP handler for the drone-follow UI."""

    ui_state: SharedUIState = None
    target_state = None   # FollowTargetState
    shared_state = None   # SharedDetectionState
    controller_config = None  # ControllerConfig
    follow_server_port: int = 8080
    recording_ctl = None  # object with start_recording/stop_recording/is_recording
    def log_message(self, format, *args):
        pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, data, status=200):
        """Send a JSON response with CORS headers."""
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors_headers()
        self.end_headers()

    # ------------------------------------------------------------------
    # GET routes
    # ------------------------------------------------------------------

    def do_GET(self):
        if self.path == "/api/video":
            self._handle_mjpeg()
        elif self.path == "/api/detections/stream":
            self._handle_detections_sse()
        elif self.path == "/api/detections":
            self._handle_detections()
        elif self.path == "/api/status":
            self._handle_status()
        elif self.path == "/api/config":
            self._handle_get_config()
        elif self.path.startswith("/api/logs"):
            self._handle_logs()
        else:
            self._handle_static()

    def _handle_mjpeg(self):
        """Stream MJPEG: multipart/x-mixed-replace with JPEG frames."""
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self._cors_headers()
        self.end_headers()

        try:
            while True:
                jpeg = self.ui_state.wait_frame(timeout=2.0)
                if jpeg is None:
                    continue
                header = (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n"
                    b"\r\n"
                )
                self.wfile.write(header)
                self.wfile.write(jpeg)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _handle_detections_sse(self):
        """SSE: push frame-synced detection snapshots on every new MJPEG frame."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self._cors_headers()
        self.end_headers()

        try:
            while True:
                _jpeg, snapshot = self.ui_state.wait_frame_with_detections(timeout=2.0)
                if snapshot is None:
                    continue
                self.wfile.write(f"data: {json.dumps(snapshot)}\n\n".encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _handle_detections(self):
        self._send_json(self.ui_state.get_detections())

    def _handle_status(self):
        status = {}
        if self.target_state is not None:
            status = self.target_state.get_status()
        if self.shared_state is not None:
            status["available_ids"] = list(self.shared_state.get_available_ids())
        if self.recording_ctl is not None:
            status["recording"] = self.recording_ctl.is_recording
        self._send_json(status)

    _CONFIG_FIELDS = {
        "kp_yaw": float,
        "max_forward": float,
        "max_backward": float,
        "max_forward_accel": float,
        "max_yawspeed": float,
        "dead_zone_deg": float,
        "yaw_only": bool,
        "auto_select": bool,
        "target_bbox_height": float,
        "kp_distance": float,
        "kp_distance_back": float,
        "dead_zone_bbox_percent": float,
        "max_climb_speed": float,
        "kp_alt_hold": float,
        "min_altitude": float,
        "max_altitude": float,
        "top_margin_safety": float,
        "bottom_margin_safety": float,
        "smooth_yaw": bool,
        "yaw_alpha": float,
        "smooth_forward": bool,
        "forward_alpha": float,
        "smooth_down": bool,
        "down_alpha": float,
        "target_altitude": float,
    }

    def _handle_get_config(self):
        cfg = self.controller_config
        if cfg is None:
            self.send_error(404, "No controller config available")
            return
        data = {k: getattr(cfg, k) for k in self._CONFIG_FIELDS}
        data["follow_server_port"] = self.follow_server_port
        self._send_json(data)

    def _handle_logs(self):
        """Return log entries newer than ?since_id=N."""
        since_id = 0
        if "?" in self.path:
            query = self.path.split("?", 1)[1]
            for part in query.split("&"):
                if part.startswith("since_id="):
                    try:
                        since_id = int(part.split("=", 1)[1])
                    except ValueError:
                        pass
        self._send_json({"logs": self.ui_state.get_logs(since_id)})

    def _handle_post_config(self):
        cfg = self.controller_config
        if cfg is None:
            self.send_error(404, "No controller config available")
            return
        length = int(self.headers.get("Content-Length", 0))
        if length > 65536:  # 64 KB limit
            self.send_error(413, "Payload too large")
            return
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
            return
        _NULLABLE_FIELDS = set()
        changed_keys = {}
        for key, value in payload.items():
            if key not in self._CONFIG_FIELDS:
                continue
            expected = self._CONFIG_FIELDS[key]
            try:
                changed_keys[key] = getattr(cfg, key)
                if key in _NULLABLE_FIELDS and (value is None or value == 0):
                    setattr(cfg, key, None)
                else:
                    setattr(cfg, key, expected(value))
            except (TypeError, ValueError):
                changed_keys.pop(key, None)
                continue
        try:
            cfg.validate()
        except ValueError as e:
            for k, old_val in changed_keys.items():
                setattr(cfg, k, old_val)
            self._send_json({"error": str(e)}, status=400)
            return
        self._send_json({k: getattr(cfg, k) for k in self._CONFIG_FIELDS})

    def _handle_static(self):
        """Serve React static build with SPA fallback to index.html."""
        if self.static_dir is None or not os.path.isdir(self.static_dir):
            self.send_error(404, "UI not built. Run: cd ui && npm install && npm run build")
            return

        path = self.path.split("?")[0].split("#")[0]  # strip query/fragment
        path = path.lstrip("/")
        if not path:
            path = "index.html"

        file_path = os.path.normpath(os.path.join(self.static_dir, path))
        # Prevent directory traversal
        if not file_path.startswith(os.path.normpath(self.static_dir) + os.sep) and \
           file_path != os.path.normpath(self.static_dir):
            self.send_error(403, "Forbidden")
            return

        if not os.path.isfile(file_path):
            file_path = os.path.join(self.static_dir, "index.html")

        if not os.path.isfile(file_path):
            self.send_error(404, "UI not built. Run: cd ui && npm install && npm run build")
            return

        content_type = self._guess_content_type(file_path)
        with open(file_path, "rb") as f:
            body = f.read()

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def _guess_content_type(path: str) -> str:
        ext = os.path.splitext(path)[1].lower()
        return {
            ".html": "text/html",
            ".js": "application/javascript",
            ".css": "text/css",
            ".json": "application/json",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".svg": "image/svg+xml",
            ".ico": "image/x-icon",
            ".woff": "font/woff",
            ".woff2": "font/woff2",
        }.get(ext, "application/octet-stream")

    # ------------------------------------------------------------------
    # POST routes
    # ------------------------------------------------------------------

    def do_POST(self):
        if self.path == "/api/config":
            self._handle_post_config()
        elif self.path == "/api/config/save":
            self._handle_config_save()
        elif self.path == "/api/config/load":
            self._handle_config_load()
        elif self.path == "/api/record/start":
            self._handle_record_start()
        elif self.path == "/api/record/stop":
            self._handle_record_stop()
        else:
            self.send_error(404, "Not Found")

    def _handle_config_save(self):
        """Dump the live ControllerConfig to df_config.json on the air unit."""
        cfg = self.controller_config
        if cfg is None:
            self.send_error(404, "No controller config available")
            return
        from drone_follow.follow_api.config import DEFAULT_CONFIG_PATH
        try:
            cfg.save_json(DEFAULT_CONFIG_PATH)
        except OSError as e:
            self._send_json({"error": f"Save failed: {e}"}, status=500)
            return
        self._send_json({"saved": True, "path": DEFAULT_CONFIG_PATH})

    def _handle_config_load(self):
        """Live-reload ControllerConfig from df_config.json (in place)."""
        cfg = self.controller_config
        if cfg is None:
            self.send_error(404, "No controller config available")
            return
        from drone_follow.follow_api.config import DEFAULT_CONFIG_PATH
        try:
            changed = cfg.load_from_file(DEFAULT_CONFIG_PATH)
        except FileNotFoundError:
            self._send_json({"error": f"No saved config at {DEFAULT_CONFIG_PATH}"}, status=404)
            return
        except ValueError as e:
            self._send_json({"error": f"Invalid values in saved config: {e}"}, status=400)
            return
        except OSError as e:
            self._send_json({"error": f"Load failed: {e}"}, status=500)
            return
        self._send_json({"loaded": True, "path": DEFAULT_CONFIG_PATH,
                         "changed": changed})

    def _handle_record_start(self):
        if self.recording_ctl is None:
            self._send_json({"error": "Recording not available"}, status=404)
            return
        path = self.recording_ctl.start_recording()
        if path:
            self._send_json({"recording": True, "path": path})
        else:
            self._send_json({"error": "Failed to start recording (already recording or UI not enabled)"}, status=409)

    def _handle_record_stop(self):
        if self.recording_ctl is None:
            self._send_json({"error": "Recording not available"}, status=404)
            return
        path = self.recording_ctl.stop_recording()
        self._send_json({"recording": False, "path": path})


class WebServer:
    """Web server for drone-follow UI. Runs in a daemon thread."""

    def __init__(self, ui_state, target_state=None, shared_state=None,
                 controller_config=None, host="0.0.0.0", port=5001, static_dir=None,
                 follow_server_port=8080, recording_ctl=None):
        self.ui_state = ui_state
        self.target_state = target_state
        self.shared_state = shared_state
        self.controller_config = controller_config
        self.host = host
        self.port = port
        self.static_dir = static_dir
        self.follow_server_port = follow_server_port
        self.recording_ctl = recording_ctl
        self.server = None
        self.thread = None

    def start(self):
        _WebHandler.ui_state = self.ui_state
        _WebHandler.target_state = self.target_state
        _WebHandler.shared_state = self.shared_state
        _WebHandler.controller_config = self.controller_config
        _WebHandler.static_dir = self.static_dir
        _WebHandler.follow_server_port = self.follow_server_port
        _WebHandler.recording_ctl = self.recording_ctl

        ThreadingHTTPServer.allow_reuse_address = True
        self.server = ThreadingHTTPServer((self.host, self.port), _WebHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        LOGGER.info("Started on http://%s:%d", self.host, self.port)

    def stop(self):
        if self.server:
            self.server.shutdown()
            LOGGER.info("Stopped")
