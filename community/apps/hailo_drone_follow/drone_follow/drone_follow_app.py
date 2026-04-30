#!/usr/bin/env python3
"""
Drone Follow — composition root and CLI entrypoint.

Wires together follow_api (pure domain logic), drone_api (MAVSDK adapter),
and pipeline_adapter (Hailo/GStreamer) into a running application.

The parser is assembled here from each domain's add_*_args() function,
so no module sees arguments it doesn't own.

Usage:
    python drone_follow_app.py --input rpi  # live mode with camera + drone

Pipeline options (--input, --input-codec, etc.) are passed through to the tiling pipeline.
"""

import faulthandler
faulthandler.enable()

import os
os.environ.setdefault("HAILO_MONITOR", "1")

import argparse
import asyncio
import logging
import signal
import threading
import time
from drone_follow.follow_api import ControllerConfig, SharedDetectionState
from drone_follow.follow_api.state import FollowTargetState
from drone_follow.drone_api import run_live_drone
from drone_follow.drone_api.mavsdk_drone import add_drone_args
from drone_follow.servers import FollowServer, OpenHDBridge

LOGGER = logging.getLogger(__name__)

_DEFAULT_REID_HEF = "/usr/local/hailo/resources/models/hailo8/repvgg_a0_person_reid_512.hef"


def _configure_logging(verbosity: str) -> None:
    level = {
        "quiet": logging.WARNING,
        "normal": logging.INFO,
        "debug": logging.DEBUG,
    }.get(verbosity, logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger().setLevel(level)


def _resolve_serial_connection(args):
    """If --serial is given, override --connection with a serial:// URI."""
    if getattr(args, "serial", None) is not None:
        baud = getattr(args, "serial_baud", 115200)
        args.connection = f"serial://{args.serial}:{baud}"
        LOGGER.info("[drone] Serial mode: connection = %s", args.connection)


def _add_app_args(parser: argparse.ArgumentParser) -> None:
    """Register application-level CLI flags (servers, UI)."""
    group = parser.add_argument_group("app")

    group.add_argument("--follow-server-port", type=int, default=8080,
                       help="HTTP server port for target selection")
    group.add_argument("--ui", action="store_true",
                       help="Enable web UI with live video and clickable bounding boxes")
    group.add_argument("--ui-port", type=int, default=5001,
                       help="Web UI server port (default: 5001)")
    group.add_argument("--ui-fps", type=int, default=10,
                       help="MJPEG stream frame rate (default: 10)")
    group.add_argument("--record", action="store_true",
                       help="Auto-start recording on launch (recording is always available from the UI)")

    group.add_argument("--no-display", action="store_true",
                       help="Disable display window (headless mode)")

    group.add_argument("--log-perf", action="store_true",
                       help="Log pipeline and tracker performance metrics periodically")

    group.add_argument("--test-log", type=str, default=None,
                       help="Write per-frame detection log as JSONL to this path "
                            "(used by simulation tests)")

    # ReID re-identification
    group.add_argument("--reid-model", type=str, default=_DEFAULT_REID_HEF,
                       help="Path to ReID HEF model for appearance-based re-identification "
                            f"(default: {_DEFAULT_REID_HEF}). Use --no-reid to disable.")
    group.add_argument("--no-reid", action="store_true",
                       help="Disable ReID re-identification")
    group.add_argument("--update-interval", type=int, default=30,
                       help="Frames between ReID gallery embedding updates while following (default: 30)")
    group.add_argument("--reid-threshold", type=float, default=0.7,
                       help="Cosine similarity threshold for ReID match (0.0–1.0, default: 0.7)")
    group.add_argument("--reid-timeout", type=float, default=20.0,
                       help="Seconds to search for a lost locked target via ReID before returning "
                            "to auto mode (default: 20.0)")
    group.add_argument("--reid-drift-threshold", type=float, default=0.5,
                       help="Below this similarity vs gallery, an in-track embedding is treated "
                            "as drift; gallery is not updated and re-acquisition is triggered "
                            "(0.0–1.0, default: 0.5)")
    group.add_argument("--reid-duplicate-threshold", type=float, default=0.9,
                       help="Above this similarity, the embedding is redundant and skipped, "
                            "with periodic refresh via --reid-refresh-every (0.0–1.0, default: 0.9)")
    group.add_argument("--reid-refresh-every", type=int, default=5,
                       help="On every Nth consecutive duplicate-band decision, replace the oldest "
                            "gallery vector to keep the gallery fresh (default: 5)")

    # OpenHD integration
    group.add_argument("--openhd-stream", action="store_true",
                       help="Send overlay video to OpenHD via UDP RTP instead of display sink")
    group.add_argument("--openhd-port", type=int, default=5500,
                       help="OpenHD UDP input port (default: 5500)")
    group.add_argument("--openhd-bitrate", type=int, default=3917,
                       help="H264 encoding bitrate in kbps for OpenHD stream (default: 3917)")


def _build_parser() -> argparse.ArgumentParser:
    """Build the full CLI parser, assembling args from every domain.

    Each domain only registers arguments it owns:
      - follow_api:        controller gains, framing, search, smoothing, safety
      - drone_api:         MAVLink connection, flight lifecycle
      - app (this file):   UI/server ports
    """
    from hailo_apps.python.core.common.core import get_pipeline_parser
    from drone_follow.pipeline_adapter import add_tracker_args
    parser = get_pipeline_parser()

    ControllerConfig.add_args(parser)
    add_drone_args(parser)

    _add_app_args(parser)
    add_tracker_args(parser)

    # Camera is mounted right-side up: no mirroring needed.
    # The library defines --horizontal-mirror/--vertical-mirror (store_true, default=False).
    # Pass both flags on the command line if the camera is upside-down.
    return parser


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    shared_state = SharedDetectionState()
    shutdown = asyncio.Event()
    eos_reached = threading.Event()

    # Create target state for follow server
    target_state = FollowTargetState()

    # Pre-parse --ui flag to set up web UI before create_app parses all args.
    # --openhd-stream is also pre-parsed because, in OpenHD mode, the recording
    # branch must be present in the pipeline so QOpenHD's Record button (via the
    # OpenHD bridge) can toggle capture even when --record wasn't passed at startup.
    ui_pre = argparse.ArgumentParser(add_help=False)
    ui_pre.add_argument("--ui", action="store_true")
    ui_pre.add_argument("--ui-port", type=int, default=5001)
    ui_pre.add_argument("--ui-fps", type=int, default=10)
    ui_pre.add_argument("--record", action="store_true")
    ui_pre.add_argument("--openhd-stream", action="store_true")
    ui_pre.add_argument("--log-perf", action="store_true")
    ui_pre_args, _ = ui_pre.parse_known_args()

    # Build the recording branch whenever there is a control surface that can
    # trigger it remotely (--openhd-stream brings QOpenHD's Record button into
    # play; --record means autostart). --record additionally drives autostart;
    # the branch alone has negligible cost when the valve stays closed.
    record_branch_enabled = ui_pre_args.record or ui_pre_args.openhd_stream or ui_pre_args.ui

    # Always create SharedUIState — the OpenHD bridge needs it for bbox
    # messages even when the web UI is disabled.
    from drone_follow.servers import SharedUIState
    ui_state = SharedUIState()

    web_server = None
    if ui_pre_args.ui:
        from drone_follow.servers import WebServer
        # Check that the UI has been built
        _ui_build_index = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "ui", "build", "index.html")
        if not os.path.isfile(_ui_build_index):
            LOGGER.error("Web UI has not been built yet.")
            LOGGER.error("  cd drone_follow/ui")
            LOGGER.error("  npm install")
            LOGGER.error("  npm run build")
            raise SystemExit(1)
    # Build the full parser from all domains, then pass to pipeline adapter
    parser = _build_parser()

    # Pre-parse ReID args to initialize the manager before create_app
    reid_pre = argparse.ArgumentParser(add_help=False)
    reid_pre.add_argument("--reid-model", type=str, default=_DEFAULT_REID_HEF)
    reid_pre.add_argument("--no-reid", action="store_true")
    reid_pre.add_argument("--update-interval", type=int, default=30)
    reid_pre.add_argument("--reid-threshold", type=float, default=0.7)
    reid_pre.add_argument("--reid-timeout", type=float, default=20.0)
    reid_pre.add_argument("--reid-drift-threshold", type=float, default=0.5,
        help="Below this similarity vs gallery, an in-track embedding is "
             "treated as drift; gallery is not updated and re-acquisition "
             "is triggered.")
    reid_pre.add_argument("--reid-duplicate-threshold", type=float, default=0.9,
        help="Above this similarity, the embedding is redundant and skipped "
             "(with periodic refresh — see --reid-refresh-every).")
    reid_pre.add_argument("--reid-refresh-every", type=int, default=5,
        help="On every Nth consecutive duplicate-band decision, replace the "
             "oldest gallery vector to keep the gallery fresh.")
    reid_pre_args, _ = reid_pre.parse_known_args()

    reid_manager = None
    if not reid_pre_args.no_reid and reid_pre_args.reid_model:
        from drone_follow.pipeline_adapter.reid_manager import ReIDManager
        reid_manager = ReIDManager(
            hef_path=reid_pre_args.reid_model,
            update_interval=reid_pre_args.update_interval,
            reid_match_threshold=reid_pre_args.reid_threshold,
            drift_threshold=reid_pre_args.reid_drift_threshold,
            duplicate_threshold=reid_pre_args.reid_duplicate_threshold,
            refresh_every=reid_pre_args.reid_refresh_every,
        )

    from drone_follow.pipeline_adapter import create_app

    # Pre-parse --tracker to pass to create_app
    from drone_follow.pipeline_adapter.tracker_factory import TRACKER_CHOICES, DEFAULT_TRACKER
    tracker_pre = argparse.ArgumentParser(add_help=False)
    tracker_pre.add_argument("--tracker", default=DEFAULT_TRACKER, choices=TRACKER_CHOICES)
    tracker_pre_args, _ = tracker_pre.parse_known_args()

    recordings_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recordings")
    app = create_app(shared_state, target_state=target_state, eos_reached=eos_reached,
                     ui_state=ui_state, ui_fps=ui_pre_args.ui_fps, parser=parser,
                     record_enabled=record_branch_enabled, record_dir=recordings_dir,
                     reid_manager=reid_manager,
                     reid_search_timeout=reid_pre_args.reid_timeout,
                     tracker_name=tracker_pre_args.tracker,
                     log_perf=ui_pre_args.log_perf)
    args = app.options_menu
    _configure_logging(getattr(args, "log_verbosity", "normal"))
    _resolve_serial_connection(args)

    # Create controller config once so it can be shared (and mutated via web UI)
    controller_config = ControllerConfig.from_args(args)

    # Make the live config visible to the detection callback so it can read auto_select
    # and write target_bbox_height when a target is locked.
    app.user_data.controller_config = controller_config

    test_log_path = getattr(args, "test_log", None)
    if test_log_path:
        app.user_data.open_test_log(test_log_path)

    # --save-config: dump effective config to JSON and exit
    save_path = getattr(args, "save_config", None)
    if save_path:
        controller_config.save_json(save_path)
        LOGGER.info("[app] Config saved to %s", save_path)
        raise SystemExit(0)

    # Start follow server (always available)
    follow_server = FollowServer(target_state, shared_state, port=args.follow_server_port,
                                 reid_manager=reid_manager,
                                 ui_state=ui_state, controller_config=controller_config)
    follow_server.start()

    # Start OpenHD parameter bridge (allows QOpenHD to control follow params,
    # bitrate, and air-side recording start/stop).
    openhd_bridge = OpenHDBridge(controller_config, target_state=target_state,
                                 detection_state=shared_state, ui_state=ui_state,
                                 gst_app=app, recording_ctl=app)
    openhd_bridge.start()

    # Start web UI server
    if ui_pre_args.ui:
        static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui", "build")
        web_server = WebServer(ui_state, target_state, shared_state,
                               controller_config=controller_config,
                               port=args.ui_port, static_dir=static_dir,
                               follow_server_port=args.follow_server_port,
                               recording_ctl=app)

        web_server.start()

    def _quit_pipeline():
        """Tell GStreamer to quit (safe to call multiple times)."""
        try:
            app.loop.quit()
        except (AttributeError, RuntimeError):
            pass

    def _eos_to_shutdown():
        eos_reached.wait()
        shutdown.set()
        _quit_pipeline()
    threading.Thread(target=_eos_to_shutdown, daemon=True).start()

    def run_drone():
        """Run drone control in a background thread with its own asyncio loop."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(
                run_live_drone(args, shared_state, shutdown,
                              config=controller_config, ui_state=ui_state,
                              target_state=target_state))
        except Exception:
            LOGGER.warning("[drone] Drone connection failed — pipeline continues without drone control.", exc_info=True)
        finally:
            loop.close()

    drone_thread = threading.Thread(target=run_drone, daemon=True)
    drone_thread.start()
    LOGGER.info("[app] Drone control started in background thread")

    def on_signal(*_):
        if not shutdown.is_set():
            shutdown.set()
            LOGGER.warning("[drone] Ctrl+C received, shutting down...")
            _quit_pipeline()

    signal.signal(signal.SIGINT, on_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, on_signal)

    # Start recording from CLI flag after pipeline is running
    if ui_pre_args.record:
        def _start_recording_delayed():
            time.sleep(1.0)  # wait for pipeline to reach PLAYING
            app.start_recording()
        threading.Thread(target=_start_recording_delayed, daemon=True).start()

    # Run the GStreamer pipeline on the main thread (UI + Hailo start immediately)
    LOGGER.info("[app] Starting Hailo pipeline and UI on main thread")
    try:
        app.run()
    except (SystemExit, KeyboardInterrupt):
        pass
    finally:
        if not shutdown.is_set():
            shutdown.set()
        if app.is_recording:
            app.stop_recording()
        else:
            app.cleanup_recording_branch()
        # Wait for drone thread to finish cleanly
        drone_thread.join(timeout=5.0)
        if reid_manager is not None:
            reid_manager.release()
        app.user_data.close_test_log()
        if web_server is not None:
            web_server.stop()
        openhd_bridge.stop()
        follow_server.stop()


if __name__ == "__main__":
    main()
