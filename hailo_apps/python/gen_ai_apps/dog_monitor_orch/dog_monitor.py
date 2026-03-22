"""
Dog Monitor — Continuous pet activity tracker using Hailo-10H VLM.

Watches a home camera and classifies dog activities at configurable intervals.
Reuses the VLM Chat Backend for inference, adds EventTracker for classification.
"""

import os
import sys
import time
import signal
import threading
import concurrent.futures
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "xcb"

import cv2

from hailo_apps.python.gen_ai_apps.vlm_chat.backend import Backend
from hailo_apps.python.gen_ai_apps.dog_monitor_orch.event_tracker import EventTracker, EventType
from hailo_apps.python.core.common.core import (
    get_standalone_parser,
    get_logger,
    handle_list_models_flag,
    resolve_hef_path,
)
from hailo_apps.python.core.common.camera_utils import get_usb_video_devices
from hailo_apps.python.core.gstreamer.gstreamer_helper_pipelines import get_source_type
from hailo_apps.python.core.common.defines import (
    DOG_MONITOR_ORCH_APP,
    VLM_MODEL_NAME_H10,
    HAILO10H_ARCH,
    RPI_NAME_I,
    USB_CAMERA,
)

# Configuration
MAX_TOKENS = 300
TEMPERATURE = 0.1
SEED = 42
INFERENCE_TIMEOUT = 60

SYSTEM_PROMPT = (
    "You are a pet monitoring assistant watching a home camera. "
    "Your job is to describe what the dog is doing RIGHT NOW in one concise sentence. "
    "Focus on: drinking water, eating food, sleeping/resting, playing, barking/alert behavior, "
    "waiting at the door. If no dog is visible, say \"No dog visible.\" "
    "Be specific and factual."
)

MONITORING_PROMPT = (
    "What is the dog doing right now? Describe the current activity in one sentence."
)

logger = get_logger(__name__)


class DogMonitorApp:
    """Continuous dog activity monitoring application using VLM inference."""

    def __init__(self, camera, camera_type: str, hef_path: str,
                 interval: int = 10, save_events: bool = False,
                 events_dir: str = "./dog_events", no_display: bool = False) -> None:
        self.camera = camera
        self.camera_type = camera_type
        self.hef_path = hef_path
        self.interval = interval
        self.save_events = save_events
        self.events_dir = Path(events_dir)
        self.no_display = no_display

        self.running = True
        self.tracker = EventTracker()
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.backend = None
        self._inference_pending = False

        if self.save_events:
            self.events_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Event frames will be saved to {self.events_dir}")

        signal.signal(signal.SIGINT, self._signal_handler)
        logger.info(
            f"DogMonitorApp initialized — interval={interval}s, "
            f"save_events={save_events}, display={'off' if no_display else 'on'}"
        )

    def _signal_handler(self, sig, frame):
        """Handle SIGINT: print summary and shut down gracefully."""
        print("")
        logger.info("Signal received, shutting down...")
        self.running = False

    def _init_camera(self):
        """Initialize camera and return (get_frame, cleanup, name) tuple."""
        if self.camera_type == RPI_NAME_I:
            try:
                from picamera2 import Picamera2
                picam2 = Picamera2()
                config = picam2.create_preview_configuration(
                    main={"size": (640, 480), "format": "RGB888"}
                )
                picam2.configure(config)
                picam2.start()
                get_frame = lambda: picam2.capture_array()
                cleanup = lambda: picam2.stop()
                return get_frame, cleanup, "RPI"
            except (ImportError, Exception) as e:
                logger.error(f"Error initializing RPI camera: {e}")
                raise
        else:
            cap = cv2.VideoCapture(self.camera)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            cap.set(cv2.CAP_PROP_FPS, 30)
            get_frame = lambda: (lambda r: r[1] if r[0] else None)(cap.read())
            cleanup = lambda: cap.release()
            return get_frame, cleanup, "USB"

    def capture_and_analyze(self, frame):
        """Capture a frame, run VLM inference, classify and log the event."""
        try:
            rgb_frame = Backend.convert_resize_image(frame)
            result = self.backend.vlm_inference(rgb_frame, MONITORING_PROMPT, INFERENCE_TIMEOUT)
            answer = result.get("answer", "")
            inference_time = result.get("time", "unknown")

            event_type = self.tracker.classify_response(answer)
            frame_path = None

            if self.save_events and event_type not in (EventType.IDLE, EventType.NO_DOG):
                timestamp = time.strftime("%Y%m%d-%H%M%S")
                frame_path = str(self.events_dir / f"event_{timestamp}.jpg")
                cv2.imwrite(frame_path, frame)
                logger.debug(f"Event frame saved: {frame_path}")

            self.tracker.add_event(event_type, answer, frame_path)

            print(f"\n[{time.strftime('%H:%M:%S')}] {event_type.value.upper()}: {answer} "
                  f"({inference_time})")

        except Exception as e:
            logger.error(f"Error during analysis: {e}")
        finally:
            self._inference_pending = False

    def _draw_overlay(self, frame):
        """Draw status overlay on the display frame."""
        overlay = frame.copy()
        h, w = overlay.shape[:2]

        # Semi-transparent black bar at top
        cv2.rectangle(overlay, (0, 0), (w, 60), (0, 0, 0), -1)
        frame_out = cv2.addWeighted(overlay, 0.6, frame, 0.4, 0)

        # Title
        cv2.putText(frame_out, "Dog Monitor", (10, 20),
                     cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 1)

        # Last event
        last = self.tracker.last_event()
        if last:
            status = f"Last: {last.event_type.value} @ {last.timestamp.strftime('%H:%M:%S')}"
        else:
            status = "Waiting for first analysis..."
        cv2.putText(frame_out, status, (10, 45),
                     cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        # Event counts at bottom
        counts = self.tracker.get_counts()
        active = {k.value: v for k, v in counts.items() if v > 0}
        if active:
            count_str = " | ".join(f"{k}:{v}" for k, v in active.items())
            cv2.putText(frame_out, count_str, (10, h - 10),
                         cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)

        return frame_out

    def run(self):
        """Main monitoring loop."""
        try:
            get_frame, cleanup, camera_name = self._init_camera()
        except Exception:
            logger.error("Failed to initialize camera. Exiting.")
            return

        try:
            self.backend = Backend(
                hef_path=str(self.hef_path),
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
                seed=SEED,
                system_prompt=SYSTEM_PROMPT,
            )
        except Exception as e:
            logger.error(f"Failed to initialize VLM backend: {e}")
            cleanup()
            return

        print(f"\n{'=' * 60}")
        print(f"  Dog Monitor — Watching via {camera_name} camera")
        print(f"  Analysis interval: {self.interval}s | Press 'q' to quit")
        print(f"{'=' * 60}\n")

        last_analysis_time = 0.0

        try:
            while self.running:
                raw_frame = get_frame()
                if raw_frame is None:
                    logger.error("Failed to read frame from camera")
                    break

                # Display
                if not self.no_display:
                    display_frame = self._draw_overlay(raw_frame)
                    cv2.imshow("Dog Monitor", display_frame)
                    key = cv2.waitKey(25) & 0xFF
                    if key == ord("q"):
                        logger.info("Quit key pressed")
                        break
                else:
                    time.sleep(0.025)

                # Periodic analysis
                now = time.time()
                if (now - last_analysis_time >= self.interval) and not self._inference_pending:
                    last_analysis_time = now
                    self._inference_pending = True
                    self.executor.submit(self.capture_and_analyze, raw_frame.copy())

        finally:
            self.running = False
            self.print_summary()
            cleanup()
            if not self.no_display:
                cv2.destroyAllWindows()
            if self.backend:
                self.backend.close()
            self.executor.shutdown(wait=False)
            logger.info("Dog Monitor shut down complete")

    def print_summary(self):
        """Print the session summary report."""
        summary = self.tracker.get_summary()
        print(summary)


def main():
    """Entry point for the Dog Monitor application."""
    parser = get_standalone_parser()
    parser.add_argument(
        "--interval", type=int, default=10,
        help="Seconds between VLM analysis frames (default: 10)"
    )
    parser.add_argument(
        "--save-events", action="store_true", default=False,
        help="Save frames when notable events are detected"
    )
    parser.add_argument(
        "--events-dir", type=str, default="./dog_events",
        help="Directory to save event frames (default: ./dog_events)"
    )

    handle_list_models_flag(parser, DOG_MONITOR_ORCH_APP)
    args = parser.parse_args()

    # Resolve HEF path
    hef_path = resolve_hef_path(
        args.hef_path if hasattr(args, "hef_path") else None,
        app_name=DOG_MONITOR_ORCH_APP,
        arch=HAILO10H_ARCH,
    )
    if hef_path is None:
        logger.error("Failed to resolve HEF path for VLM model. Exiting.")
        sys.exit(1)

    # Resolve video source
    video_source = args.input
    if video_source == USB_CAMERA:
        logger.debug("Scanning USB video devices...")
        devices = get_usb_video_devices()
        if not devices:
            logger.error("No USB camera found for '--input usb'")
            print('Provided argument "--input" is set to "usb", however no available USB cameras found.')
            sys.exit(1)
        video_source = devices[0]
        logger.debug(f"Using USB camera: {video_source}")

    source_type = get_source_type(video_source) if video_source else None

    if not video_source:
        print('Please provide an input source using the "--input" argument.')
        sys.exit(1)

    app = DogMonitorApp(
        camera=video_source,
        camera_type=source_type,
        hef_path=hef_path,
        interval=args.interval,
        save_events=args.save_events,
        events_dir=args.events_dir,
        no_display=getattr(args, "no_display", False),
    )
    app.run()
    sys.exit(0)


if __name__ == "__main__":
    main()
