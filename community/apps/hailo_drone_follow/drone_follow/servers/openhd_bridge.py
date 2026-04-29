"""OpenHD Bridge — UDP bridge for controlling drone follow parameters via MAVLink.

Listens for parameter change messages from OpenHD (C++ HailoFollowBridge) and
applies them to the shared ControllerConfig. Periodically reports current values
back so OpenHD can serve accurate read-back to the ground station.

Float params use native MAVLink REAL32 — no scaling needed.
Int/bool params use MAVLink INT32.

Wire protocol (JSON over UDP):
  OpenHD -> Python (port 5510): {"param": "<field_name>", "value": <number>}
  Python -> OpenHD (port 5511): {"params": {<field_name>: <number>, ...}}

Detection/tracking state (follow_id, active_id, bboxes) is sent exclusively
via the binary detection payload v3 on WFB port 40 — not in this JSON report.
The JSON report carries only configuration parameters for bidirectional sync.

follow_id semantics (DF_FOLLOW_ID):
  -1  → IDLE: drone holds position, ignores all detections
   0  → AUTO: system auto-follows largest person in frame
   N  → LOCKED: operator explicitly selected person N

active_id (DF_ACTIVE_ID):
  The currently active tracking ID reported by FollowTargetState regardless of
  whether it was auto-selected or operator-locked. 0 means no one being tracked.
  QOpenHD uses this to distinguish AUTO-tracking-someone from no-one-in-view.
"""

import json
import logging
import socket
import threading
import time

LOGGER = logging.getLogger(__name__)

# Mapping: wire_name -> (mavlink_id, python_type)
# wire_name matches both the JSON "param" field from OpenHD and the
# ControllerConfig attribute name.  Values are native float or int (no scaling).
_CONFIG_PARAMS = {
    "kp_yaw":                   ("DF_KP_YAW",    float),
    "max_forward":              ("DF_MAX_FWD",    float),
    "max_backward":             ("DF_MAX_BACK",   float),
    "max_forward_accel":        ("DF_MAX_ACC",   float),
    "dead_zone_deg":            ("DF_DZ_YAW",    float),
    "kp_distance":              ("DF_KP_DIST",   float),
    "kp_distance_back":         ("DF_KP_DIST_B", float),
    "target_bbox_height":       ("DF_TGT_BH",    float),
    "dead_zone_bbox_percent":   ("DF_DZ_BH_PCT", float),
    "max_climb_speed":          ("DF_MAX_CLM",   float),
    "max_yawspeed":             ("DF_MAX_YAW",   float),
    "kp_alt_hold":              ("DF_KP_ALT_H",  float),
    "min_altitude":             ("DF_MIN_ALT",   float),
    "max_altitude":             ("DF_MAX_ALT",   float),
    "yaw_alpha":                ("DF_YAW_ALPHA",  float),
    "forward_alpha":            ("DF_FWD_ALPHA",  float),
    "target_altitude":          ("DF_TGT_ALT",   float),
    "yaw_only":                 ("DF_YAW_ONLY",   bool),
    "auto_select":              ("DF_AUTO_SEL",  bool),
    "smooth_yaw":               ("DF_SMTH_YAW",   bool),
    "smooth_forward":           ("DF_SMTH_FWD",   bool),
    "down_alpha":               ("DF_DN_ALPHA",   float),
    "smooth_down":              ("DF_SMTH_DN",    bool),
}

# Fields where value 0 maps to Python None
_NULLABLE_FIELDS = set()

# Special params for follow target control (not in ControllerConfig)
_FOLLOW_ID_PARAM = "follow_id"
_ACTIVE_ID_PARAM = "active_id"
_BITRATE_PARAM = "bitrate_kbps"
_RECORDING_PARAM = "recording"  # 1 = start, 0 = stop; routed to recording_ctl
_SAVE_CONFIG_PARAM = "save_config"  # 1 = momentary trigger → save ControllerConfig to disk; echo 0 back
_LOAD_CONFIG_PARAM = "load_config"  # 1 = momentary trigger → live-reload ControllerConfig from disk


class OpenHDBridge:
    """UDP bridge between OpenHD MAVLink params and ControllerConfig."""

    def __init__(self, controller_config, target_state=None, detection_state=None,
                 ui_state=None, gst_app=None, recording_ctl=None,
                 listen_port=5510, report_port=5511, report_interval=0.1):
        self._config = controller_config
        self._target_state = target_state
        self._detection_state = detection_state
        self._ui_state = ui_state
        self._gst_app = gst_app  # GstApp for dynamic encoder control
        self._recording_ctl = recording_ctl  # GstApp with start/stop_recording + is_recording
        self._listen_port = listen_port
        self._report_port = report_port
        self._report_interval = report_interval
        self._running = False
        self._listen_thread = None
        self._report_thread = None
        self._sock = None

        # Tracks operator's explicit follow_id intent:
        #   -1 = IDLE (drone hold), 0 = AUTO, N = locked to person N
        # Reported back to QOpenHD instead of target_state.get_target() so that
        # the badge reflects the operator's choice, not the auto-selected ID.
        self._explicit_follow_id = 0
        self._current_bitrate_kbps = 0  # dedup repeated bitrate updates

    def start(self):
        """Start listener and reporter daemon threads."""
        if self._running:
            return
        self._running = True

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", self._listen_port))
        self._sock.settimeout(1.0)

        self._listen_thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._listen_thread.start()

        self._report_thread = threading.Thread(target=self._report_loop, daemon=True)
        self._report_thread.start()

        LOGGER.info("[openhd_bridge] Started (listen=%d, report=%d)",
                    self._listen_port, self._report_port)

    def stop(self):
        """Stop the bridge threads."""
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
        if self._listen_thread:
            self._listen_thread.join(timeout=3.0)
        if self._report_thread:
            self._report_thread.join(timeout=3.0)
        LOGGER.info("[openhd_bridge] Stopped")

    # -- Listener: OpenHD -> Python ------------------------------------------

    def _listen_loop(self):
        while self._running:
            try:
                data, _ = self._sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                if self._running:
                    LOGGER.warning("[openhd_bridge] Socket error in listener")
                break

            try:
                msg = json.loads(data.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                LOGGER.warning("[openhd_bridge] Invalid JSON received")
                continue

            param_name = msg.get("param")
            value = msg.get("value")
            if param_name is None or value is None:
                continue

            if param_name == _FOLLOW_ID_PARAM:
                self._apply_follow_id(int(value))
            elif param_name == _ACTIVE_ID_PARAM:
                pass  # read-only from Python's side; ignore any set forwarded by OpenHD
            elif param_name == _BITRATE_PARAM:
                self._apply_bitrate(int(value))
            elif param_name == _RECORDING_PARAM:
                self._apply_recording(int(value))
            elif param_name == _SAVE_CONFIG_PARAM:
                self._apply_save_config(int(value))
            elif param_name == _LOAD_CONFIG_PARAM:
                self._apply_load_config(int(value))
            elif param_name in _CONFIG_PARAMS:
                self._apply_config_param(param_name, value)
            else:
                LOGGER.warning("[openhd_bridge] Unknown param: %s", param_name)

    def _apply_follow_id(self, value: int):
        """Handle follow target selection from ground station.

        -1 → IDLE (drone holds position, ignores detections)
         0 → AUTO (follow largest)
         N → LOCKED to person N
        """
        if self._target_state is None:
            LOGGER.warning("[openhd_bridge] follow_id received but no target_state")
            return
        self._explicit_follow_id = value
        if value < 0:
            self._target_state.set_paused(True)
            self._target_state.set_target(None)
            self._target_state.set_explicit_lock(False)
            LOGGER.info("[openhd_bridge] IDLE mode (drone holding position)")
        elif value == 0:
            self._target_state.enter_auto_mode()
            LOGGER.info("[openhd_bridge] AUTO mode (follow largest person)")
        else:
            self._target_state.set_paused(False)
            self._target_state.set_target(value)
            self._target_state.set_explicit_lock(True)
            LOGGER.info("[openhd_bridge] LOCKED to ID %d", value)
        # Immediately push state back so QOpenHD badge updates without waiting
        # for the next periodic report cycle.
        self._send_immediate_report()

    def _apply_bitrate(self, kbps: int):
        """Dynamically set x264enc bitrate from WFB link recommendation.

        Only applies in --openhd-stream mode where the drone-follow app owns the
        x264enc encoder. In SHM mode OpenHD handles encoding directly.
        """
        if kbps == self._current_bitrate_kbps:
            return
        if self._gst_app is None or not hasattr(self._gst_app, 'pipeline'):
            return
        pipeline = self._gst_app.pipeline
        if pipeline is None:
            return
        encoder = pipeline.get_by_name("openhd_stream_encoder")
        if encoder is None:
            # SHM mode — no local encoder; OpenHD handles bitrate directly
            return
        encoder.set_property("bitrate", kbps)
        self._current_bitrate_kbps = kbps
        LOGGER.info("[openhd_bridge] x264enc bitrate set to %d kbps", kbps)

    def _apply_recording(self, value: int):
        """Start or stop air-side recording from QOpenHD's Record button.

        Idempotent: 1 means "ensure recording", 0 means "ensure stopped".
        Mirrors the web UI's POST /api/record/start and /api/record/stop.
        """
        if self._recording_ctl is None:
            LOGGER.warning("[openhd_bridge] recording requested but no recording_ctl wired")
            return
        try:
            currently_recording = bool(self._recording_ctl.is_recording)
        except Exception:
            LOGGER.exception("[openhd_bridge] is_recording query failed")
            return
        if value and not currently_recording:
            try:
                path = self._recording_ctl.start_recording()
            except Exception:
                LOGGER.exception("[openhd_bridge] start_recording failed")
                return
            if path:
                LOGGER.info("[openhd_bridge] Recording started → %s", path)
            else:
                LOGGER.warning("[openhd_bridge] start_recording returned None (was --record passed?)")
        elif not value and currently_recording:
            try:
                path = self._recording_ctl.stop_recording()
            except Exception:
                LOGGER.exception("[openhd_bridge] stop_recording failed")
                return
            LOGGER.info("[openhd_bridge] Recording stopped → %s", path)
        # Push state immediately so QOpenHD's button updates without
        # waiting for the next periodic report cycle.
        self._send_immediate_report()

    def _apply_save_config(self, value: int):
        """Momentary trigger — on value=1, save ControllerConfig to DEFAULT_CONFIG_PATH.

        QOpenHD's toggle returns to OFF automatically via the immediate report
        (both `save_config` and `load_config` are always reported as 0).
        """
        if not value:
            return
        from drone_follow.follow_api.config import DEFAULT_CONFIG_PATH
        try:
            self._config.save_json(DEFAULT_CONFIG_PATH)
            LOGGER.info("[openhd_bridge] Config saved → %s", DEFAULT_CONFIG_PATH)
        except OSError as e:
            LOGGER.error("[openhd_bridge] Config save failed: %s", e)
        self._send_immediate_report()

    def _apply_load_config(self, value: int):
        """Momentary trigger — on value=1, live-reload ControllerConfig from disk."""
        if not value:
            return
        from drone_follow.follow_api.config import DEFAULT_CONFIG_PATH
        try:
            changed = self._config.load_from_file(DEFAULT_CONFIG_PATH)
            LOGGER.info("[openhd_bridge] Config loaded ← %s (%d changed)",
                        DEFAULT_CONFIG_PATH, len(changed))
        except FileNotFoundError:
            LOGGER.warning("[openhd_bridge] No saved config at %s", DEFAULT_CONFIG_PATH)
        except (OSError, ValueError) as e:
            LOGGER.error("[openhd_bridge] Config load failed: %s", e)
        self._send_immediate_report()

    def _apply_config_param(self, param_name, value):
        """Apply a single parameter change from OpenHD to ControllerConfig."""
        _, py_type = _CONFIG_PARAMS[param_name]

        # Convert to Python type
        if param_name in _NULLABLE_FIELDS and value == 0:
            py_value = None
        elif py_type is bool:
            py_value = bool(int(value))
        elif py_type is float:
            py_value = float(value)
        else:
            py_value = value

        # Save old value for rollback on validation failure
        old_value = getattr(self._config, param_name, None)
        try:
            setattr(self._config, param_name, py_value)
            self._config.validate()
            LOGGER.info("[openhd_bridge] %s = %s", param_name, py_value)
        except ValueError as e:
            setattr(self._config, param_name, old_value)
            LOGGER.warning("[openhd_bridge] Rejected %s=%s: %s",
                           param_name, py_value, e)

    # -- Reporter: Python -> OpenHD ------------------------------------------

    def _send_immediate_report(self):
        """Send a one-shot report on a transient socket (callable from any thread)."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self._send_report(sock)
        except OSError:
            pass
        finally:
            sock.close()

    def _report_loop(self):
        """Periodically send current config values to OpenHD for read-back sync."""
        report_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self._send_report(report_sock)
            while self._running:
                time.sleep(self._report_interval)
                if self._running:
                    self._send_report(report_sock)
        finally:
            report_sock.close()

    def _send_report(self, sock):
        """Send all current parameter values to OpenHD."""
        params = {}
        for param_name, (_, py_type) in _CONFIG_PARAMS.items():
            py_value = getattr(self._config, param_name, None)
            if param_name in _NULLABLE_FIELDS and py_value is None:
                params[param_name] = 0.0
            elif py_type is bool:
                params[param_name] = int(py_value) if py_value is not None else 0
            elif py_type is float:
                params[param_name] = float(py_value) if py_value is not None else 0.0
            else:
                params[param_name] = py_value if py_value is not None else 0

        # Sync follow_id/active_id into params for OpenHD's HailoFollowBridge
        # parameter cache (these are also in the binary v3 payload, but the
        # bridge needs them here to populate the MAVLink DF_FOLLOW_ID /
        # DF_ACTIVE_ID settings for QOpenHD parameter reads).
        if self._target_state is not None:
            actual_target = self._target_state.get_target()

            # If the callback fell back after losing an explicit lock,
            # sync follow_id so QOpenHD badge reflects the actual state.
            if self._explicit_follow_id > 0 and not self._target_state.is_explicit_lock():
                if self._target_state.is_paused():
                    self._explicit_follow_id = -1
                    LOGGER.info("[openhd_bridge] Explicit lock lost — syncing to IDLE")
                else:
                    self._explicit_follow_id = 0
                    LOGGER.info("[openhd_bridge] Explicit lock lost — syncing to AUTO")

            params[_FOLLOW_ID_PARAM] = self._explicit_follow_id
            params[_ACTIVE_ID_PARAM] = actual_target if actual_target is not None else 0

        # Sync recording state so QOpenHD's button reflects reality —
        # covers air-side --record autostart, web-UI toggles, and stop-on-EOS.
        if self._recording_ctl is not None:
            try:
                params[_RECORDING_PARAM] = int(bool(self._recording_ctl.is_recording))
            except Exception:
                pass

        # save_config / load_config are momentary triggers — always reported as 0
        # so QOpenHD's toggles return to rest after each trigger is processed.
        params[_SAVE_CONFIG_PARAM] = 0
        params[_LOAD_CONFIG_PARAM] = 0

        payload = {"params": params}

        # Bounding boxes: sent here so OpenHD's HailoFollowBridge can build the
        # binary detection payload v3 and transmit it via WFB port 40 to ground.
        if self._ui_state is not None:
            det_data = self._ui_state.get_detections()
            active_id = det_data.get("following_id")
            bboxes = []
            for det in det_data.get("detections", []):
                bbox = det.get("bbox", {})
                x = bbox.get("x", 0.0)
                y = bbox.get("y", 0.0)
                w = bbox.get("w", 0.0)
                h = bbox.get("h", 0.0)
                det_id = det.get("id")
                bboxes.append({
                    "id": det_id if det_id is not None else 0,
                    "cx": round(x + w / 2, 4),
                    "cy": round(y + h / 2, 4),
                    "w": round(w, 4),
                    "h": round(h, 4),
                    "tracked": det_id is not None and det_id == active_id,
                })
            payload["bboxes"] = bboxes

        msg = json.dumps(payload).encode("utf-8")
        try:
            sock.sendto(msg, ("127.0.0.1", self._report_port))
        except OSError as e:
            LOGGER.debug("[openhd_bridge] Report send failed: %s", e)
