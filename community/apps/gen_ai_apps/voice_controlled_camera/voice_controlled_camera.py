"""
Voice-Controlled Smart Camera

A hands-free smart camera that responds to voice commands to detect and describe objects.
Combines Whisper speech-to-text, Qwen LLM for intent parsing, Qwen2-VL VLM for scene
description, and Piper TTS for audio responses.

Voice commands:
- "What do you see?" / "Describe the scene" -> VLM scene description
- "Detect people" / "Count cars" -> Object detection via VLM
- "Read that sign" -> OCR/text reading via VLM

Usage:
    python -m hailo_apps.python.gen_ai_apps.voice_controlled_camera.voice_controlled_camera

    # With USB camera
    python voice_controlled_camera.py --input usb

    # Without TTS (text-only output)
    python voice_controlled_camera.py --input usb --no-tts
"""

import argparse
import os
import signal
import sys
import threading
import time
import traceback
from io import StringIO
from contextlib import redirect_stderr
from enum import Enum
from typing import Optional

import cv2
import numpy as np

os.environ["QT_QPA_PLATFORM"] = "xcb"

from hailo_platform import VDevice
from hailo_platform.genai import LLM

from hailo_apps.python.core.common.defines import (
    HAILO10H_ARCH,
    LLM_PROMPT_PREFIX,
    SHARED_VDEVICE_GROUP_ID,
    USB_CAMERA,
    VLM_CHAT_APP,
    VLM_MODEL_NAME_H10,
    VOICE_ASSISTANT_APP,
    VOICE_ASSISTANT_MODEL_NAME,
)
from hailo_apps.python.core.common.core import (
    get_logger,
    resolve_hef_path,
)
from hailo_apps.python.core.common.camera_utils import get_usb_video_devices
from hailo_apps.python.core.common.hailo_logger import (
    add_logging_cli_args,
    init_logging,
    level_from_args,
)
from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.interaction import (
    VoiceInteractionManager,
)
from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.vad import add_vad_args
from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.speech_to_text import (
    SpeechToTextProcessor,
)
from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.text_to_speech import (
    TextToSpeechProcessor,
    PiperModelNotFoundError,
)
from hailo_apps.python.gen_ai_apps.gen_ai_utils.llm_utils import streaming
from hailo_apps.python.gen_ai_apps.vlm_chat.backend import Backend


logger = get_logger(__name__)

# Intent classification keywords
DESCRIBE_KEYWORDS = ["describe", "what do you see", "scene", "look", "tell me what", "show me"]
DETECT_KEYWORDS = ["detect", "count", "find", "how many", "where", "spot"]
READ_KEYWORDS = ["read", "ocr", "text", "sign", "writing", "says"]

# VLM configuration
VLM_MAX_TOKENS = 200
VLM_TEMPERATURE = 0.1
VLM_SEED = 42

# Camera configuration
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480
CAMERA_FPS = 30

# Display window name
WINDOW_NAME = "Voice Controlled Camera"


class CommandIntent(Enum):
    """Classified voice command intents."""
    DESCRIBE = "describe"
    DETECT = "detect"
    READ = "read"
    CHAT = "chat"


class VoiceControlledCameraApp:
    """
    Voice-controlled smart camera application.

    Combines:
    - Whisper STT for voice input
    - LLM for intent classification and chat
    - VLM for scene description and visual analysis
    - TTS for spoken responses
    - OpenCV for camera feed display
    """

    def __init__(
        self,
        camera_source,
        no_tts: bool = False,
        debug: bool = False,
    ):
        """
        Initialize the voice-controlled camera app.

        Args:
            camera_source: Camera device index or path.
            no_tts: If True, disable text-to-speech output.
            debug: If True, enable debug logging.
        """
        self.camera_source = camera_source
        self.no_tts = no_tts
        self.debug = debug
        self.abort_event = threading.Event()
        self.running = True
        self.interaction = None

        # Latest camera frame (shared between threads)
        self._frame_lock = threading.Lock()
        self._latest_frame: Optional[np.ndarray] = None
        self._status_text = "Initializing..."

        print("Initializing AI components... (This might take a moment)")

        # Suppress noisy ALSA messages during initialization
        with redirect_stderr(StringIO()):
            # 1. VDevice (shared across models)
            params = VDevice.create_params()
            params.group_id = SHARED_VDEVICE_GROUP_ID
            self.vdevice = VDevice(params)

            # 2. Speech to Text (Whisper)
            self.s2t = SpeechToTextProcessor(self.vdevice)

            # 3. LLM for intent classification and chat responses
            llm_model_path = resolve_hef_path(
                hef_path=VOICE_ASSISTANT_MODEL_NAME,
                app_name=VOICE_ASSISTANT_APP,
                arch=HAILO10H_ARCH,
            )
            if llm_model_path is None:
                raise RuntimeError(
                    "Failed to resolve HEF path for LLM model. "
                    "Please ensure the model is available."
                )
            self.llm = LLM(self.vdevice, str(llm_model_path))

            # 4. TTS (Piper)
            self.tts = None
            if not no_tts:
                try:
                    self.tts = TextToSpeechProcessor()
                except PiperModelNotFoundError:
                    logger.warning("Piper TTS model not found. Running without TTS.")
                    self.tts = None

        # 5. VLM Backend (runs in separate process)
        vlm_model_path = resolve_hef_path(
            hef_path=VLM_MODEL_NAME_H10,
            app_name=VLM_CHAT_APP,
            arch=HAILO10H_ARCH,
        )
        if vlm_model_path is None:
            raise RuntimeError(
                "Failed to resolve HEF path for VLM model. "
                "Please ensure the model is available."
            )
        self.vlm_backend = Backend(
            hef_path=str(vlm_model_path),
            max_tokens=VLM_MAX_TOKENS,
            temperature=VLM_TEMPERATURE,
            seed=VLM_SEED,
            system_prompt=(
                "You are a helpful visual assistant for a smart camera. "
                "Describe what you see clearly and concisely. "
                "When asked to detect or count objects, be specific about quantities and locations."
            ),
        )

        self._status_text = "Ready - Listening for commands"
        print("AI components ready!")

    def classify_intent(self, text: str) -> CommandIntent:
        """
        Classify the user's voice command into an intent.

        Args:
            text: Transcribed voice command text.

        Returns:
            CommandIntent enum value.
        """
        text_lower = text.lower()

        for keyword in READ_KEYWORDS:
            if keyword in text_lower:
                return CommandIntent.READ

        for keyword in DETECT_KEYWORDS:
            if keyword in text_lower:
                return CommandIntent.DETECT

        for keyword in DESCRIBE_KEYWORDS:
            if keyword in text_lower:
                return CommandIntent.DESCRIBE

        # Default: use LLM for chat response
        return CommandIntent.CHAT

    def get_current_frame(self) -> Optional[np.ndarray]:
        """Get the latest camera frame (thread-safe)."""
        with self._frame_lock:
            if self._latest_frame is not None:
                return self._latest_frame.copy()
            return None

    def set_status(self, text: str):
        """Set the status text displayed on the camera feed."""
        with self._frame_lock:
            self._status_text = text

    def _build_vlm_prompt(self, intent: CommandIntent, user_text: str) -> str:
        """
        Build a VLM prompt based on the classified intent.

        Args:
            intent: The classified command intent.
            user_text: The original user command text.

        Returns:
            Prompt string for the VLM.
        """
        if intent == CommandIntent.DESCRIBE:
            return (
                "Describe this scene in detail. What objects, people, and activities "
                "do you see? Be concise but thorough."
            )
        elif intent == CommandIntent.DETECT:
            return (
                f"The user asked: '{user_text}'. "
                "Look at the image carefully. Identify and count the relevant objects. "
                "Report what you found with specific quantities."
            )
        elif intent == CommandIntent.READ:
            return (
                "Look at this image and read any text, signs, labels, or writing "
                "that you can see. Report the text content."
            )
        else:
            return user_text

    def on_processing_start(self):
        """Called when voice recording starts processing."""
        self.on_abort()
        if self.tts:
            self.tts.interrupt()

    def on_abort(self):
        """Abort current generation and speech."""
        self.abort_event.set()
        if self.tts:
            self.tts.interrupt()

    def on_audio_ready(self, audio):
        """
        Callback when voice audio is ready for processing.

        This is the main processing pipeline:
        1. Transcribe speech to text
        2. Classify intent
        3. Route to VLM (visual) or LLM (chat)
        4. Speak the response via TTS

        Args:
            audio: Recorded audio data from the microphone.
        """
        self.abort_event.clear()

        # 1. Transcribe
        user_text = self.s2t.transcribe(audio)
        if not user_text:
            print("No speech detected.")
            return

        print(f"\nYou: {user_text}")

        # 2. Classify intent
        intent = self.classify_intent(user_text)
        logger.debug("Classified intent: %s", intent.value)

        # 3. Route based on intent
        if intent in (CommandIntent.DESCRIBE, CommandIntent.DETECT, CommandIntent.READ):
            self._handle_visual_command(intent, user_text)
        else:
            self._handle_chat_command(user_text)

        # 4. Handshake: Wait for TTS to finish, then restart listening
        if self.interaction:
            try:
                self.interaction.restart_after_tts()
            except Exception:
                pass

    def _handle_visual_command(self, intent: CommandIntent, user_text: str):
        """
        Handle a visual command by capturing a frame and running VLM inference.

        Args:
            intent: The classified command intent.
            user_text: The original user command text.
        """
        self.set_status(f"Processing: {intent.value}...")
        print(f"\n[{intent.value.upper()}] Capturing frame and analyzing...")

        # Capture current frame
        frame = self.get_current_frame()
        if frame is None:
            response = "I cannot see anything right now. The camera may not be connected."
            print(f"\nAssistant: {response}")
            self._speak(response)
            self.set_status("Ready - Listening for commands")
            return

        # Build VLM prompt
        vlm_prompt = self._build_vlm_prompt(intent, user_text)
        logger.debug("VLM prompt: %s", vlm_prompt)

        # Run VLM inference
        try:
            result = self.vlm_backend.vlm_inference(
                frame, vlm_prompt, timeout=60
            )
            response = result.get("answer", "I could not analyze the image.")
            inference_time = result.get("time", "unknown")
            logger.debug("VLM inference time: %s", inference_time)
        except Exception as e:
            logger.error("VLM inference failed: %s", e)
            response = "Sorry, I had trouble analyzing the image. Please try again."

        print(f"\nAssistant: {response}")
        self._speak(response)
        self.set_status("Ready - Listening for commands")

    def _handle_chat_command(self, user_text: str):
        """
        Handle a general chat command using the LLM.

        Args:
            user_text: The user's chat message.
        """
        self.set_status("Thinking...")
        print("\nAssistant:\n")

        # Prepare TTS state
        current_gen_id = None
        state = {
            "sentence_buffer": "",
            "first_chunk_sent": False,
        }

        if self.tts:
            self.tts.clear_interruption()
            current_gen_id = self.tts.get_current_gen_id()

        # Generate LLM response
        prompt_text = LLM_PROMPT_PREFIX + user_text
        formatted_prompt = [{"role": "user", "content": prompt_text}]

        def tts_callback(chunk: str):
            if self.tts:
                state["sentence_buffer"] += chunk
                state["sentence_buffer"] = self.tts.chunk_and_queue(
                    state["sentence_buffer"],
                    current_gen_id,
                    not state["first_chunk_sent"],
                )
                if not state["first_chunk_sent"] and not self.tts.speech_queue.empty():
                    state["first_chunk_sent"] = True

        streaming.generate_and_stream_response(
            llm=self.llm,
            prompt=formatted_prompt,
            prefix="",
            show_raw_stream=self.debug,
            token_callback=tts_callback,
            abort_callback=self.abort_event.is_set,
        )

        # Send remaining text to TTS
        if self.tts and state["sentence_buffer"].strip():
            self.tts.queue_text(state["sentence_buffer"].strip(), current_gen_id)

        print()  # New line after streaming
        self.set_status("Ready - Listening for commands")

    def _speak(self, text: str):
        """
        Speak the given text via TTS.

        Args:
            text: Text to speak.
        """
        if self.tts:
            self.tts.clear_interruption()
            self.tts.queue_text(text)

    def on_clear_context(self):
        """Clear the LLM conversation context."""
        self.llm.clear_context()
        print("Context cleared.")

    def camera_loop(self):
        """
        Main camera display loop. Runs in a separate thread.
        Captures frames and displays them with status overlay.
        """
        cap = cv2.VideoCapture(self.camera_source)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
        cap.set(cv2.CAP_PROP_FPS, CAMERA_FPS)

        if not cap.isOpened():
            logger.error("Failed to open camera: %s", self.camera_source)
            self.running = False
            return

        try:
            while self.running:
                ret, frame = cap.read()
                if not ret:
                    logger.error("Failed to read frame from camera")
                    break

                # Store latest frame for VLM processing
                with self._frame_lock:
                    self._latest_frame = frame.copy()
                    status = self._status_text

                # Draw status overlay
                display_frame = frame.copy()
                cv2.putText(
                    display_frame,
                    status,
                    (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 255, 0),
                    2,
                )

                cv2.imshow(WINDOW_NAME, display_frame)

                # Check for 'q' key to quit
                key = cv2.waitKey(25) & 0xFF
                if key == ord("q"):
                    self.running = False
                    break
        finally:
            cap.release()
            cv2.destroyAllWindows()

    def close(self):
        """Clean up all resources."""
        self.running = False

        if self.tts:
            try:
                self.tts.stop()
            except Exception:
                pass

        if self.vlm_backend:
            try:
                self.vlm_backend.close()
            except Exception:
                pass

        try:
            self.llm.release()
        except Exception:
            pass


def main():
    """Main entry point for the voice-controlled camera app."""
    parser = argparse.ArgumentParser(
        description="Voice-controlled smart camera with scene description and object detection."
    )
    add_logging_cli_args(parser)

    parser.add_argument(
        "--input",
        type=str,
        default="usb",
        help='Input source: "usb" for USB camera, or device path/index (default: usb)',
    )
    parser.add_argument(
        "--no-tts",
        action="store_true",
        help="Disable text-to-speech output.",
    )
    add_vad_args(parser)

    args = parser.parse_args()

    # Initialize logging
    init_logging(level=level_from_args(args))
    debug_mode = getattr(args, "debug", False)

    # Resolve camera source
    video_source = args.input
    if video_source == USB_CAMERA:
        usb_devices = get_usb_video_devices()
        if not usb_devices:
            print(
                'No USB camera found for "--input usb". '
                "Please connect a camera or specify a different input."
            )
            sys.exit(1)
        video_source = usb_devices[0]
        logger.debug("Using USB camera: %s", video_source)

    if args.no_tts:
        print("TTS disabled: Running in text-only mode.")

    # Initialize the app
    app = VoiceControlledCameraApp(
        camera_source=video_source,
        no_tts=args.no_tts,
        debug=debug_mode,
    )

    # Start camera display in a background thread
    camera_thread = threading.Thread(target=app.camera_loop, daemon=True)
    camera_thread.start()

    # Set up signal handler
    def signal_handler(sig, frame):
        print("\nShutting down...")
        app.running = False
        app.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    # Initialize and run the voice interaction manager
    interaction = VoiceInteractionManager(
        title="Voice Controlled Camera",
        on_audio_ready=app.on_audio_ready,
        on_processing_start=app.on_processing_start,
        on_clear_context=app.on_clear_context,
        on_shutdown=app.close,
        on_abort=app.on_abort,
        debug=debug_mode,
        vad_enabled=args.vad,
        vad_aggressiveness=args.vad_aggressiveness,
        vad_energy_threshold=args.vad_energy_threshold,
        tts=app.tts,
    )

    # Inject interaction into app for handshake control
    app.interaction = interaction

    # Run the voice interaction loop (blocks until shutdown)
    interaction.run()

    # Cleanup
    app.close()
    camera_thread.join(timeout=2)


if __name__ == "__main__":
    main()
