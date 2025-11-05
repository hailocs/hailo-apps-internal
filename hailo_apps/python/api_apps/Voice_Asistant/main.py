from processing import AIPipeline
from recorder import Recorder
from io import StringIO
from contextlib import redirect_stderr
import argparse
import tty
import termios
import threading
import sys


class TerminalRecorderApp:
    """
    Manages the main application logic for the terminal-based recorder.

    This class ties together the `Recorder` and `AIPipeline`, handling user
    input to control recording and processing states.
    """

    def __init__(self, debug=False, no_tts=False):
        """
        Initialize the terminal recorder application.

        Args:
            debug (bool): If True, saves recorded audio to WAV files for analysis.
            no_tts (bool): If True, disables text-to-speech output for lower resource usage.
        """
        self.recorder = Recorder(debug=debug)
        self.is_recording = False
        self.lock = threading.Lock()
        self.debug = debug
        print()
        if debug:
            print("Debug mode enabled: Audio will be saved to 'debug_audio_*.wav' files.")
        if no_tts:
            print("TTS disabled: Running in low-resource mode.")

        print("Loading AI pipeline... (This might take a moment)")
        # Suppress noisy ALSA messages during initialization
        with redirect_stderr(StringIO()):
            self.ai_pipeline = AIPipeline(no_tts=no_tts)
        print("✅ AI pipeline ready!")

    def toggle_recording(self):
        """Switches between starting and stopping a recording."""
        with self.lock:
            if not self.is_recording:
                self.start_recording()
            else:
                self.stop_recording()

    def start_recording(self):
        """Starts a new audio recording."""
        self.ai_pipeline.interrupt()
        self.recorder.start()
        self.is_recording = True
        print("\n🔴 Recording started. Press SPACE to stop.")

    def _show_banner(self):
        """Displays the full application banner with instructions."""
        print("\n" + "="*50)
        print("      Terminal Voice Assistant")
        print("="*50)
        print("Controls:")
        print("  - Press SPACE to start/stop recording.")
        print("  - Press Q to quit.")
        print("  - Press C to clear context.")
        print("="*50 + "\n")

    def stop_recording(self):
        """Stops the current recording and initiates AI processing."""
        print("\nProcessing... Please wait.")
        audio = self.recorder.stop()
        self.is_recording = False

        if audio.size > 0:
            self.ai_pipeline.process(audio)
        else:
            print("No audio recorded.")

        self._show_banner()

    def close(self):
        """Stops any active processes and cleans up resources."""
        print("\nShutting down...")
        if self.is_recording:
            # Stop recording without processing the audio
            self.recorder.stop()
            self.is_recording = False
        self.ai_pipeline.interrupt()
        self.recorder.close()


def get_char():
    """
    Reads a single character from stdin without requiring the user to press Enter.

    This is used to capture key presses for controlling the application (e.g.,
    spacebar to toggle recording, 'q' to quit). It temporarily changes the
    terminal settings to raw mode to achieve this.
    """
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(sys.stdin.fileno())
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    return ch


def main():
    """
    Main function: parses arguments, initializes the app, and runs the input loop.
    """
    parser = argparse.ArgumentParser(
        description='A simple, voice-controlled AI assistant for your terminal.')
    parser.add_argument('--debug', action='store_true',
                        help='Enable debug mode to save recorded audio files.')
    parser.add_argument('--no-tts', action='store_true',
                        help='Disable text-to-speech output for lower resource usage.')

    args = parser.parse_args()

    # Initialize the app and show welcome message
    app = TerminalRecorderApp(debug=args.debug, no_tts=args.no_tts)
    app._show_banner()  # Show initial banner

    # Main loop to capture key presses
    while True:
        ch = get_char().lower()
        if ch == "q":
            app.close()
            print("Exited.")
            break
        elif ch == " ":
            app.toggle_recording()
        elif ch == "\x03":  # Handle Ctrl+C
            app.close()
            print("Exited.")
            break
        elif ch == "c":
            app.ai_pipeline.llm.clear_context()
            print("Context cleared.")
        # Other characters are ignored


if __name__ == "__main__":
    main()
