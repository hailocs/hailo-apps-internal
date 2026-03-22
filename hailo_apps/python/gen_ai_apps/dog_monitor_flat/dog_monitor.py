"""
Dog Monitor — Continuous VLM-based pet monitoring application.

Captures camera frames at a configurable interval, analyses them with
the Hailo-10H VLM, classifies dog activities, and maintains an event log.
Press Ctrl+C for a graceful shutdown with a full session summary.
"""

from __future__ import annotations

import os
import signal
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "xcb"

import cv2

from hailo_apps.python.gen_ai_apps.vlm_chat.backend import Backend
from hailo_apps.python.gen_ai_apps.dog_monitor_flat.event_tracker import EventTracker, EventType
from hailo_apps.python.core.common.core import (
    get_logger,
    get_standalone_parser,
    handle_list_models_flag,
    resolve_hef_path,
)
from hailo_apps.python.core.common.camera_utils import get_usb_video_devices
from hailo_apps.python.core.gstreamer.gstreamer_helper_pipelines import get_source_type
from hailo_apps.python.core.common.defines import (
    DOG_MONITOR_FLAT_APP,
    HAILO10H_ARCH,
    RPI_NAME_I,
    USB_CAMERA,
)

# ── VLM configuration ──────────────────────────────────────────────────────
MAX_TOKENS = 150
TEMPERATURE = 0.1
SEED = 42
INFERENCE_TIMEOUT = 60

SYSTEM_PROMPT = (
    "You are a pet monitoring assistant watching a home camera. "
    "Your job is to describe what the dog is doing RIGHT NOW in one concise sentence. "
    "Focus on: drinking water, eating food, sleeping/resting, playing, barking/alert behavior, "
    "waiting at the door. If no dog is visible, say \"No dog visible.\" Be specific and factual."
)

MONITORING_PROMPT = "What is the dog doing right now? Describe the current activity in one sentence."

logger = get_logger(__name__)


# ── Main application class ─────────────────────────────────────────────────

class ContinuousMonitor:
    """Continuously captures frames and analyses dog activity via the VLM backend."""

    def __init__(self, camera, camera_type: str, hef_path: str,
                 interval: int = 10, save_events: bool = False, events_dir: str = "./dog_events"):
        self.camera = camera
        self.camera_type = camera_type
        self.hef_path = hef_path
        self.interval = interval
        self.save_events = save_events
        self.events_dir = events_dir

        self.running = True
        self.tracker = EventTracker()
        self.backend: Backend | None = None

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    # ── lifecycle ───────────────────────────────────────────────────────────

    def _signal_handler(self, sig, frame):
        print("")
        logger.info("Signal received, shutting down…")
        self.running = False

    def _init_camera(self):
        """Return (get_frame, cleanup, camera_name) matching the camera type."""
        if self.camera_type == RPI_NAME_I:
            try:
                from picamera2 import Picamera2
                picam2 = Picamera2()
                config = picam2.create_preview_configuration(main={"size": (640, 480), "format": "RGB888"})
                picam2.configure(config)
                picam2.start()
                return lambda: picam2.capture_array(), lambda: picam2.stop(), "RPI"
            except (ImportError, Exception) as e:
                logger.error(f"Error initialising RPi camera: {e}")
                raise
        else:
            cap = cv2.VideoCapture(self.camera)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            cap.set(cv2.CAP_PROP_FPS, 30)
            get_frame = lambda: (lambda r: r[1] if r[0] else None)(cap.read())
            return get_frame, lambda: cap.release(), "USB"

    def _draw_overlay(self, frame):
        """Draw status overlay on the display frame."""
        h, w = frame.shape[:2]
        overlay = frame.copy()
        # Semi-transparent bar at the top
        cv2.rectangle(overlay, (0, 0), (w, 60), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)

        status = f"Last: {self.tracker.last_event_type.value}"
        cv2.putText(frame, "DOG MONITOR", (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.putText(frame, status, (10, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        events_total = len(self.tracker.events)
        cv2.putText(frame, f"Events: {events_total}", (w - 140, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        return frame

    # ── main loop ───────────────────────────────────────────────────────────

    def run(self):
        """Entry point — initialise resources and start the monitoring loop."""
        # Camera
        try:
            get_frame, cleanup_camera, cam_name = self._init_camera()
        except Exception:
            logger.error("Failed to initialise camera. Exiting.")
            return

        logger.info(f"Camera initialised ({cam_name})")

        # Backend
        try:
            self.backend = Backend(
                hef_path=self.hef_path,
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
                seed=SEED,
                system_prompt=SYSTEM_PROMPT,
            )
        except Exception as e:
            logger.error(f"Failed to initialise VLM backend: {e}")
            cleanup_camera()
            return

        logger.info(f"VLM backend ready — monitoring every {self.interval}s")
        print("\n" + "=" * 60)
        print("  DOG MONITOR — Continuous monitoring started")
        print(f"  Interval: {self.interval}s | Save events: {self.save_events}")
        print("  Press Ctrl+C to stop and see session summary")
        print("=" * 60 + "\n")

        last_analysis_time = 0.0

        try:
            while self.running:
                raw_frame = get_frame()
                if raw_frame is None:
                    logger.error("Failed to read frame from camera")
                    break

                # Prepare display frame (central-cropped like the model sees)
                rgb_frame = Backend.convert_resize_image(raw_frame)
                display_frame = cv2.cvtColor(rgb_frame, cv2.COLOR_RGB2BGR)
                display_frame = self._draw_overlay(display_frame)
                cv2.imshow("Dog Monitor", display_frame)

                # Interval-based analysis
                now = time.time()
                if now - last_analysis_time >= self.interval:
                    last_analysis_time = now
                    logger.info("Capturing frame for analysis…")
                    try:
                        result = self.backend.vlm_inference(
                            raw_frame.copy(), MONITORING_PROMPT, INFERENCE_TIMEOUT
                        )
                        answer = result.get("answer", "")
                        event_type = self.tracker.classify_response(answer)
                        self.tracker.log_event(event_type, answer)

                        if self.save_events and event_type not in (EventType.NO_DOG, EventType.IDLE):
                            self.tracker.save_frame(raw_frame, self.events_dir, event_type)

                    except Exception as e:
                        logger.error(f"Analysis error: {e}")

                # OpenCV window event processing
                key = cv2.waitKey(25) & 0xFF
                if key == ord("q"):
                    self.running = False

        finally:
            cleanup_camera()
            cv2.destroyAllWindows()
            if self.backend:
                self.backend.close()
            self.tracker.print_summary()


# ── CLI entry point ─────────────────────────────────────────────────────────

def main():
    parser = get_standalone_parser()

    # App-specific arguments
    parser.add_argument(
        "--interval",
        type=int,
        default=10,
        help="Seconds between automatic frame captures (default: 10).",
    )
    parser.add_argument(
        "--save-events",
        action="store_true",
        help="Save frames to disk when interesting events are detected.",
    )
    parser.add_argument(
        "--events-dir",
        type=str,
        default="./dog_events",
        help="Directory to save event frames (default: ./dog_events).",
    )

    handle_list_models_flag(parser, DOG_MONITOR_FLAT_APP)
    args = parser.parse_args()

    # Resolve HEF (VLM is Hailo-10H only)
    hef_path = resolve_hef_path(
        args.hef_path if hasattr(args, "hef_path") else None,
        app_name=DOG_MONITOR_FLAT_APP,
        arch=HAILO10H_ARCH,
    )
    if hef_path is None:
        logger.error("Failed to resolve HEF path for VLM model. Exiting.")
        sys.exit(1)

    # Resolve camera source
    video_source = args.input
    if video_source == USB_CAMERA:
        logger.debug("Scanning for USB cameras…")
        devices = get_usb_video_devices()
        if not devices:
            logger.error("No USB camera found for '--input usb'")
            print('No USB camera detected. Connect a camera or use "--input rpi".')
            sys.exit(1)
        video_source = devices[0]
        logger.debug(f"Using USB camera: {video_source}")

    source_type = get_source_type(video_source) if video_source else None
    if not video_source:
        print('Please specify an input source: "--input usb" or "--input rpi".')
        sys.exit(1)

    monitor = ContinuousMonitor(
        camera=video_source,
        camera_type=source_type,
        hef_path=str(hef_path),
        interval=args.interval,
        save_events=args.save_events,
        events_dir=args.events_dir,
    )
    monitor.run()
    sys.exit(0)


if __name__ == "__main__":
    main()
