import threading
import signal
import os
import cv2
import sys
import json
import concurrent.futures
import select
import time
from datetime import datetime
from typing import Optional, Callable, Any

os.environ["QT_QPA_PLATFORM"] = 'xcb'
from community.apps.gen_ai_apps.visual_quality_inspector.backend import Backend
from hailo_apps.python.core.common.core import get_standalone_parser, get_logger, handle_list_models_flag, resolve_hef_path
from hailo_apps.python.core.common.camera_utils import get_usb_video_devices
from hailo_apps.python.core.gstreamer.gstreamer_helper_pipelines import get_source_type
from hailo_apps.python.core.common.defines import (
    VLM_CHAT_APP,
    HAILO10H_ARCH,
    RPI_NAME_I,
    USB_CAMERA
)

# Configuration Constants
MAX_TOKENS = 300
TEMPERATURE = 0.1
SEED = 42
SYSTEM_PROMPT = (
    "You are an expert quality inspection assistant for manufactured parts. "
    "When shown an image of a part, analyze it carefully and report: "
    "1) Overall assessment (PASS or FAIL), "
    "2) Any defects found (scratches, dents, cracks, discoloration, warping, missing features, surface irregularities), "
    "3) Severity of each defect (minor, moderate, critical), "
    "4) Location of each defect in the image. "
    "Be precise and concise. If no defects are found, state that the part passes inspection."
)
INFERENCE_TIMEOUT = 60
SAVE_FRAMES = False

# Default inspection prompt used when the user presses Enter without typing
DEFAULT_INSPECTION_PROMPT = (
    "Inspect this manufactured part for quality defects. "
    "Describe any visible defects including their type, severity, and location."
)

# App States
STATE_STREAMING = "STREAMING"
STATE_CAPTURED = "CAPTURED"
STATE_PROCESSING = "PROCESSING"
STATE_RESULT = "RESULT"

# Initialize logger
logger = get_logger(__name__)


class VisualQualityInspectorApp:
    """
    Visual Quality Inspector application using VLM to describe defects
    in manufactured parts captured from a camera.
    """

    def __init__(self, camera: Any, camera_type: str, log_file: Optional[str] = None):
        """
        Initialize the Visual Quality Inspector Application.

        Args:
            camera (Any): Camera source (device index or connection object).
            camera_type (str): Type of camera ('usb' or 'rpi').
            log_file (Optional[str]): Path to log file for defect reports. None to disable.
        """
        self.camera = camera
        self.camera_type = camera_type
        self.log_file = log_file
        self.running = True
        self.executor = concurrent.futures.ThreadPoolExecutor()
        signal.signal(signal.SIGINT, self.signal_handler)
        self.frozen_frame = None
        self.current_state = STATE_STREAMING
        self.user_question = ''
        self.backend: Optional[Backend] = None
        self.video_thread: Optional[threading.Thread] = None
        self.inspection_count = 0

    def signal_handler(self, sig, frame):
        """Handle interrupt signals."""
        print('')
        logger.info("Signal received, shutting down...")
        self.stop()

    def stop(self):
        """Stop the application and clean up resources."""
        self.running = False
        if self.backend:
            self.backend.close()
        self.executor.shutdown(wait=True)

    def _get_user_input(self) -> Optional[str]:
        """
        Check for user input from stdin without blocking.

        Returns:
            Optional[str]: User input string if available, else None.
        """
        if select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], []):
            return sys.stdin.readline().strip()
        return None

    def _init_camera(self) -> tuple[Callable[[], Any], Callable[[], None], str]:
        """
        Initialize the camera based on type.

        Returns:
            tuple: (get_frame_callback, cleanup_callback, camera_name)
        """
        if self.camera_type == RPI_NAME_I:
            try:
                from picamera2 import Picamera2
                picam2 = Picamera2()
                config = picam2.create_preview_configuration(main={"size": (640, 480), "format": "RGB888"})
                picam2.configure(config)
                picam2.start()
                get_frame = lambda: picam2.capture_array()
                cleanup = lambda: picam2.stop()
                camera_name = "RPI"
                return get_frame, cleanup, camera_name
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
            camera_name = "USB"
            return get_frame, cleanup, camera_name

    def _print_state_prompt(self):
        """Print prompt based on current state."""
        print("\n" + "=" * 80)
        if self.current_state == STATE_STREAMING:
            print("  LIVE VIDEO  |  Press Enter to CAPTURE part image ('q' to quit)")
            print("=" * 80)
        elif self.current_state == STATE_CAPTURED:
            print("  IMAGE CAPTURED  |  Type question (Enter for default inspection, 'q' to Cancel)")
            print("=" * 80)
            print("Question: ", end="", flush=True)
        elif self.current_state == STATE_PROCESSING:
            print("  INSPECTING...  |  Analyzing part for defects")
            print("=" * 80)
        elif self.current_state == STATE_RESULT:
            print("  INSPECTION COMPLETE  |  Press Enter to continue")
            print("=" * 80)

    def _log_inspection_result(self, question: str, result: dict):
        """
        Log inspection result to file if logging is enabled.

        Args:
            question (str): The inspection prompt used.
            result (dict): The VLM inference result.
        """
        if not self.log_file:
            return

        self.inspection_count += 1
        entry = {
            "inspection_id": self.inspection_count,
            "timestamp": datetime.now().isoformat(),
            "prompt": question,
            "result": result.get('answer', ''),
            "inference_time": result.get('time', '')
        }

        try:
            with open(self.log_file, 'a') as f:
                f.write(json.dumps(entry) + "\n")
            logger.info(f"Inspection #{self.inspection_count} logged to {self.log_file}")
        except IOError as e:
            logger.error(f"Failed to write to log file: {e}")

    def show_video(self):
        """Main loop for displaying video and handling user interaction."""
        try:
            get_frame, cleanup, _ = self._init_camera()
        except Exception:
            logger.error("Failed to initialize camera. Exiting.")
            self.running = False
            return

        # Initialize Backend
        try:
            self.backend = Backend(
                hef_path=str(hef_path),
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
                seed=SEED,
                system_prompt=SYSTEM_PROMPT
            )
        except Exception as e:
            logger.error(f"Failed to initialize backend: {e}")
            cleanup()
            self.running = False
            return

        vlm_future = None

        # Initial Prompt
        self._print_state_prompt()

        frame = None

        try:
            while self.running:
                # Display Logic
                if self.current_state == STATE_STREAMING:
                    raw_frame = get_frame()
                    if raw_frame is None:
                        logger.error("Failed to read frame from camera")
                        break

                    rgb_frame = Backend.convert_resize_image(raw_frame)
                    frame = cv2.cvtColor(rgb_frame, cv2.COLOR_RGB2BGR)

                    cv2.imshow('Quality Inspector', frame)
                elif self.current_state in [STATE_CAPTURED, STATE_PROCESSING, STATE_RESULT]:
                    if self.frozen_frame is not None:
                        cv2.imshow('Quality Inspector', self.frozen_frame)

                # Key Handling (Window)
                key = cv2.waitKey(25) & 0xFF
                if key == ord('q'):
                    self.stop()
                    break

                # Input Handling (Terminal)
                user_input = self._get_user_input()

                # State Machine Logic
                if self.current_state == STATE_STREAMING:
                    if user_input is not None:
                        stripped = user_input.strip()
                        if stripped.lower() in ['q', 'quit']:
                            self.stop()
                            break

                        if frame is not None:
                            self.frozen_frame = frame.copy()
                            self.current_state = STATE_CAPTURED
                            self._print_state_prompt()

                elif self.current_state == STATE_CAPTURED:
                    if user_input is not None:
                        stripped = user_input.strip()
                        if stripped.lower() in ['q', 'quit']:
                            self.current_state = STATE_STREAMING
                            self.frozen_frame = None
                            self._print_state_prompt()
                            continue

                        self.user_question = stripped or DEFAULT_INSPECTION_PROMPT
                        if not stripped:
                            print(f"Using default prompt: '{self.user_question}'")

                        if SAVE_FRAMES and self.frozen_frame is not None:
                            timestamp = time.strftime("%Y%m%d-%H%M%S")
                            cv2.imwrite(f"inspection_{timestamp}.jpg", self.frozen_frame)
                            print(f"Frame saved as inspection_{timestamp}.jpg")

                        self.current_state = STATE_PROCESSING
                        self._print_state_prompt()

                        vlm_future = self.executor.submit(
                            self.backend.vlm_inference,
                            self.frozen_frame.copy(),
                            self.user_question,
                            INFERENCE_TIMEOUT
                        )

                elif self.current_state == STATE_PROCESSING:
                    if vlm_future and vlm_future.done():
                        try:
                            result = vlm_future.result()
                            self._log_inspection_result(self.user_question, result)
                        except Exception as e:
                            logger.error(f"Error getting future result: {e}")
                            print(f"\nError processing request: {e}")

                        vlm_future = None
                        self.current_state = STATE_RESULT
                        self._print_state_prompt()

                elif self.current_state == STATE_RESULT:
                    if user_input is not None:
                        self.current_state = STATE_STREAMING
                        self.frozen_frame = None
                        self._print_state_prompt()

        finally:
            cleanup()
            cv2.destroyAllWindows()
            self.stop()

    def run(self):
        """Start the application thread."""
        self.video_thread = threading.Thread(target=self.show_video)
        self.video_thread.start()
        try:
            self.video_thread.join()
        except KeyboardInterrupt:
            self.stop()
            self.video_thread.join()


if __name__ == "__main__":
    parser = get_standalone_parser()
    parser.add_argument(
        "--log-file",
        type=str,
        default=None,
        help="Path to a JSONL file to log inspection results. Each line is a JSON object with inspection_id, timestamp, prompt, result, and inference_time."
    )

    # Handle --list-models flag before full initialization
    # Reuse vlm_chat app name for model resolution since we use the same VLM model
    handle_list_models_flag(parser, VLM_CHAT_APP)

    options_menu = parser.parse_args()

    # Resolve HEF path with auto-download (VLM is Hailo-10H only)
    hef_path = resolve_hef_path(
        options_menu.hef_path if hasattr(options_menu, 'hef_path') else None,
        app_name=VLM_CHAT_APP,
        arch=HAILO10H_ARCH
    )
    if hef_path is None:
        logger.error("Failed to resolve HEF path for VLM model. Exiting.")
        sys.exit(1)

    video_source = options_menu.input
    if video_source == USB_CAMERA:
        logger.debug("USB_CAMERA detected; scanning USB devices...")
        video_source = get_usb_video_devices()
        if not video_source:
            logger.error("No USB camera found for '--input usb'")
            print(
                'Provided argument "--input" is set to "usb", however no available USB cameras found. '
                'Please connect a camera or specify a different input method.'
            )
            sys.exit(1)
        else:
            logger.debug(f"Using USB camera: {video_source[0]}")
            video_source = video_source[0]

    # Determine source type (usb, rpi, file, etc.)
    source_type = get_source_type(video_source) if video_source else None

    if not video_source:
        print('Please provide an input source using the "--input" argument: "usb" for USB camera or "rpi" for Raspberry Pi camera.')
        sys.exit(1)

    app = VisualQualityInspectorApp(
        camera=video_source,
        camera_type=source_type,
        log_file=options_menu.log_file
    )
    app.run()
    sys.exit(0)
