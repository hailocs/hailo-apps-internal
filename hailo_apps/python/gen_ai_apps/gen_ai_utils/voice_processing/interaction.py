import logging
import threading
import traceback
from typing import Any, Callable, Optional

import numpy as np

from hailo_apps.python.gen_ai_apps.gen_ai_utils.llm_utils.terminal_ui import TerminalUI
from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.audio_recorder import AudioRecorder
from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.vad import VoiceActivityDetector
from hailo_apps.python.core.common.defines import TARGET_SR, CHUNK_SIZE

# Setup logger
logger = logging.getLogger(__name__)


class VoiceInteractionManager:
    """
    Manages the interactive voice loop (recording, UI, events).

    This class abstracts the common pattern of:
    1. Waiting for user input (SPACE to record, Q to quit, C to clear context).
    2. Managing the AudioRecorder.
    3. Delegating processing to callbacks.
    """

    def __init__(
        self,
        title: str,
        on_audio_ready: Callable[[np.ndarray], None],
        on_processing_start: Optional[Callable[[], None]] = None,
        on_clear_context: Optional[Callable[[], None]] = None,
        on_shutdown: Optional[Callable[[], None]] = None,
        on_abort: Optional[Callable[[], None]] = None,
        debug: bool = False,
        vad_enabled: bool = False,
        vad_aggressiveness: int = 1,
        vad_energy_threshold: float = 0.2,
        vad_inhibit: Optional[Callable[[], bool]] = None,
        tts: Optional[Any] = None,
    ):
        """
        Args:
            title (str): Title for the terminal banner.
            on_audio_ready (Callable): Callback when recording finishes with audio data.
            on_processing_start (Callable): Callback when recording starts (e.g. to stop TTS).
            on_clear_context (Callable): Callback when 'C' is pressed.
            on_shutdown (Callable): Callback when 'Q' or Ctrl+C is pressed.
            on_abort (Callable): Callback when 'X' is pressed.
            debug (bool): Enable debug logging for recorder.
            vad_enabled (bool): Enable Voice Activity Detection for hands-free operation.
            vad_aggressiveness (int): VAD aggressiveness (0-3).
            vad_energy_threshold (float): Minimum energy to trigger speech detection.
            tts (Optional): TextToSpeechProcessor instance for automatic inhibition and handshake.
        """
        self.title = title
        self.on_audio_ready = on_audio_ready
        self.on_processing_start = on_processing_start
        self.on_clear_context = on_clear_context
        self.on_shutdown = on_shutdown
        self.on_abort = on_abort
        self.debug = debug
        self.vad_enabled = vad_enabled
        self.vad_aggressiveness = vad_aggressiveness
        self.vad_energy_threshold = vad_energy_threshold
        self.tts = tts

        # Default inhibition using TTS if provided
        if self.tts and vad_inhibit is None:
             self.vad_inhibit = lambda: self.tts.is_speaking
        else:
             self.vad_inhibit = vad_inhibit

        self.recorder = AudioRecorder(debug=debug)
        self.is_recording = False
        self.lock = threading.Lock()

        # VAD State
        self.vad = None
        self.vad_speech_active = False
        self.vad_processing_thread = None
        self.vad_stop_event = threading.Event()

        if self.vad_enabled:
            # Note: We enforce 16kHz for VAD compatibility (webrtcvad requires 8/16/32/48k)
            # AudioRecorder might capture at higher rate (e.g. 44100), so we resample in callback.
            sample_rate = TARGET_SR

            # Calculate chunk size (in samples) equivalent to ~30ms-50ms for good VAD
            self.vad = VoiceActivityDetector(
                sample_rate=sample_rate,
                chunk_size=CHUNK_SIZE,
                aggressiveness=self.vad_aggressiveness,
                energy_threshold=self.vad_energy_threshold,
                warmup_chunks=10  # Ignore first ~0.6s to avoid startup clicks/pops
            )
            logger.info(f"VAD enabled with sample rate {sample_rate} Hz, aggressiveness {vad_aggressiveness}")

        self.controls = {
            "SPACE": "start/stop recording",
            "Q": "quit",
            "C": "clear context",
            "X": "abort generation",
        }

        # Check if we have a valid input device
        if self.recorder.device_id is None:
            print("\n⚠️  WARNING: No audio input device detected!")
            print("Run 'hailo-audio-troubleshoot' to diagnose audio issues.")

    def run(self):
        """Starts the main interaction loop."""
        TerminalUI.show_banner(title=self.title, controls=self.controls)
        logger.debug("Voice interaction started")

        if self.vad_enabled:
            print("\n🎤 Hands-free mode enabled. Just start speaking!")
        if self.vad_enabled:

            self.start_listening()

        try:
            while True:
                ch = TerminalUI.get_char().lower()
                if ch == "q":
                    logger.info("Quit requested")
                    self.close()
                    break
                elif ch == " ":
                    self.toggle_recording()
                elif ch == "\x03":  # Ctrl+C
                    logger.info("Ctrl+C received")
                    self.close()
                    break
                elif ch == "c":
                    logger.info("Clear context requested")
                    if self.on_clear_context:
                        self.on_clear_context()
                elif ch == "x":
                    logger.info("Abort requested")
                    if self.on_abort:
                        self.on_abort()
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt in main loop")
            self.close()
        except Exception as e:
            logger.error("Unexpected error in main loop: %s", e)
            if self.debug:
                logger.debug("Traceback: %s", traceback.format_exc())

    def toggle_recording(self):
        with self.lock:
            if not self.is_recording:
                self.start_recording()
            else:
                self.stop_recording()

    def start_listening(self):
        """Starts the active listening loop (VAD or regular recording)."""
        with self.lock:
            if self.is_recording:
                return

            if self.vad_enabled:
                 print("\n🎤 Listening for speech...")
                 self._start_vad_mode()
            else:
                 print("\nPress SPACE to start recording.")

    def _start_vad_mode(self):
        """Internal method to start VAD monitoring."""
        self.vad.reset()
        self.vad_speech_active = False

        # Start monitoring thread if not running
        if not self.vad_processing_thread or not self.vad_processing_thread.is_alive():
            self.vad_stop_event.clear()
            self.vad_processing_thread = threading.Thread(target=self._vad_monitor_loop, daemon=True)
            self.vad_processing_thread.start()

        self.start_recording(use_callback=True, trigger_start_event=False)

    def _vad_callback(self, chunk: np.ndarray):
        """
        Callback for audio chunks when VAD is enabled.
        Runs in the audio thread.
        """
        try:
            # Check for inhibition (e.g. TTS playing)
            if self.vad_inhibit and self.vad_inhibit():
                # Treat as silence or just return early
                # If we return early, no visualization, which is good.
                return

            # Flatten to 1D if necessary (sounddevice returns (N, 1))
            if chunk.ndim > 1:
                chunk = chunk.flatten()

            # Resample if necessary (e.g. 44100 -> 16000)
            if self.recorder.device_sr != TARGET_SR:
                # Simple linear interpolation
                num_samples = int(len(chunk) * TARGET_SR / self.recorder.device_sr)
                chunk = np.interp(
                    np.linspace(0.0, 1.0, num_samples, endpoint=False),
                    np.linspace(0.0, 1.0, len(chunk), endpoint=False),
                    chunk
                ).astype(np.float32)

            is_speech, energy = self.vad.process(chunk)

            # --- ASCII Visualizer ---
            status_symbol = "🗣️ " if self.vad_speech_active else "👂"
            if is_speech: status_symbol = "🔴" # Specifically this chunk is speech

            if self.vad_enabled:
                bar_chart = self.vad.visualize(energy)
                msg = f"\r{status_symbol} {bar_chart} Energy: {energy:.4f} (Aggr: {self.vad.aggressiveness})"
                print(msg, end="", flush=True)
            # ------------------------

            if is_speech and not self.vad_speech_active:
                # TRANSITION: Silence -> Speech
                self.vad_speech_active = True
                print("\n🗣️  Speech detected...", end="", flush=True)
                # Signal processing start (stops TTS)
                if self.on_processing_start:
                    try:
                        self.on_processing_start()
                    except Exception:
                        pass

            elif not is_speech and self.vad_speech_active:
                # TRANSITION: Speech -> Silence
                self.vad_speech_active = False
                # Signal monitor loop to stop recording and process
                self.vad_stop_event.set()

            elif not is_speech and not self.vad_speech_active:
                # Steady Silence - Trim buffer to keep only pre-roll
                # Simply keep last 15 chunks (approx for default settings)
                MAX_PREROLL_CHUNKS = 20
                if len(self.recorder.audio_frames) > MAX_PREROLL_CHUNKS:
                     self.recorder.audio_frames.pop(0)

        except Exception as e:
            logger.error("Error in VAD callback: %s", e)

    def _vad_monitor_loop(self):
        """
        Background thread to handle VAD state transitions (Stop -> Process -> Restart).
        """
        while True:
            # Wait for speech to end
            self.vad_stop_event.wait()
            self.vad_stop_event.clear()

            # Stop recording and process
            logger.debug("VAD: Speech ended, processing...")
            self.stop_recording()

            # Restarting listening is handled by the application layer (handshake)
            # to prevent self-triggering during TTS playback.
            pass

    def start_recording(self, use_callback: bool = False, trigger_start_event: bool = True):
        if trigger_start_event and self.on_processing_start:
            try:
                self.on_processing_start()
            except Exception as e:
                logger.warning("Failed to execute start callback: %s", e)

        try:
            callback = self._vad_callback if (self.vad_enabled and use_callback) else None
            self.recorder.start(stream_callback=callback)
            self.is_recording = True
            if not self.vad_enabled:
                print("\n🔴 Recording started. Press SPACE to stop.")
            else:
                # In VAD mode, we are "listening", not necessarily "recording" user speech yet.
                pass
        except Exception as e:
            logger.error("Failed to start recording: %s", e)
            print("\n❌ Error starting recording!")
            print(f"Error: {e}")
            print("Tip: Run 'hailo-audio-troubleshoot' to check your microphone.")
            self.is_recording = False


    def stop_recording(self):
        print("\nProcessing... Please wait.")
        try:
            audio = self.recorder.stop()
        except Exception as e:
            logger.error("Failed to stop recording: %s", e)
            self.is_recording = False
            return

        self.is_recording = False

        if audio.size > 0:
            logger.debug("Audio captured: %d samples", audio.size)
            if self.on_audio_ready:
                # Run processing in a separate thread to keep UI responsive (for abort)
                def processing_wrapper():
                    try:
                        self.on_audio_ready(audio)
                    except Exception as e:
                        logger.error("Processing failed: %s", e)
                        if self.debug:
                            logger.debug("Traceback: %s", traceback.format_exc())
                    finally:
                        # Show banner again after processing is done
                        TerminalUI.show_banner(title=self.title, controls=self.controls)
                        # Handshake: We do NOT automatically restart listening here.
                        # The Application must call interaction.start_listening() explicitly
                        # after it finishes its output (TTS).

                threading.Thread(target=processing_wrapper, daemon=True).start()
        else:
            logger.warning("No audio recorded")
            print("⚠️  No audio recorded.")
            TerminalUI.show_banner(title=self.title, controls=self.controls)

    def close(self):
        if self.on_shutdown:
            try:
                self.on_shutdown()
            except Exception as e:
                logger.error("Failed during shutdown callback: %s", e)

    def restart_after_tts(self):
        """
        Wait for TTS to finish (if active) and then restart listening.
        This handles the VAD-TTS handshake to prevent self-triggering.
        """
        if self.tts:
            self.tts.wait_for_completion()
        self.start_listening()
