import logging
import numpy as np
import webrtcvad

logger = logging.getLogger(__name__)

class VoiceActivityDetector:
    """
    Detects voice activity in audio chunks using Google's webrtcvad library.
    """

    def __init__(self, sample_rate: int, chunk_size: int, aggressiveness: int = 3,
                 min_speech_duration_ms: int = 200, min_silence_duration_ms: int = 1000,
                 energy_threshold: float = 0.05, warmup_chunks: int = 10):
        """
        Args:
            sample_rate: Audio sample rate.
            chunk_size: Number of samples per incoming chunk.
            aggressiveness: VAD filter aggressiveness (0-3).
            min_speech_duration_ms: Minimum duration of activity to trigger speech start.
            min_silence_duration_ms: Minimum duration of silence to trigger speech stop.
            energy_threshold: Minimum energy to trigger speech detection.
        """
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.aggressiveness = aggressiveness
        self.energy_threshold = energy_threshold

        self.vad = webrtcvad.Vad(aggressiveness)

        # webrtcvad supports 10, 20, or 30ms frames.
        self.frame_duration_ms = 30
        self.frame_size = int(sample_rate * self.frame_duration_ms / 1000)

        self.buffer = b""

        # State
        self.is_speech = False
        self.consecutive_speech_chunks = 0
        self.consecutive_silence_chunks = 0

        # Durations in "chunks" (incoming chunks, not VAD frames)
        incoming_chunk_ms = (chunk_size / sample_rate) * 1000
        self.min_speech_chunks = max(1, int(min_speech_duration_ms / incoming_chunk_ms))
        self.min_silence_chunks = max(1, int(min_silence_duration_ms / incoming_chunk_ms))

        # Warmup logic
        self.warmup_chunks = warmup_chunks
        self.warmup_counter = self.warmup_chunks

        logger.info(f"VAD initialized: rate={sample_rate}, aggr={aggressiveness}, threshold={energy_threshold}, warmup={warmup_chunks}")

    def process(self, audio_chunk: np.ndarray):
        """
        Process an audio chunk and return detection state and metrics.

        Args:
            audio_chunk: Float32 numpy array of audio samples.

        Returns:
            tuple: (is_speech, energy)
        """
        if len(audio_chunk) == 0:
            return self.is_speech, 0.0

        # Warmup check
        if self.warmup_counter > 0:
            self.warmup_counter -= 1
            # During warmup, we can calculate energy just for debugging/visuals if we wanted,
            # but to ensure we don't trigger, we assume silence.
            # We can still return actual energy so visualizer works, OR return 0.0 to prevent confusion.
            # Returning 0.0 ensures no visual "red bar" during warmup.
            return False, 0.0

        # 1. Calculate Energy (RMS) on the full chunk
        energy = np.sqrt(np.mean(audio_chunk**2))

        # GATE: If energy is too low, treat as silence immediately
        if energy < self.energy_threshold:
            chunk_is_speech = False
        else:
            # 2. Convert to 16-bit PCM for webrtcvad
            audio_int16 = (audio_chunk * 32767).clip(-32768, 32767).astype(np.int16)

            # 3. Buffer audio
            self.buffer += audio_int16.tobytes()

            # 4. Process frames from buffer
            speech_frames = 0
            total_frames = 0

            while len(self.buffer) >= self.frame_size * 2: # 2 bytes per sample
                frame_bytes = self.buffer[:self.frame_size * 2]
                self.buffer = self.buffer[self.frame_size * 2:]

                try:
                    if self.vad.is_speech(frame_bytes, self.sample_rate):
                        speech_frames += 1
                    total_frames += 1
                except Exception as e:
                    logger.debug("VAD error: %s", e)

            # 5. Logic: Decision based on majority vote of frames in the chunk
            # Stricter Majority Vote: 70% instead of 50%
            chunk_is_speech = False
            if total_frames > 0:
                if speech_frames / total_frames >= 0.7:
                    chunk_is_speech = True

        # 6. State Machine (Debounce)
        if chunk_is_speech:
            self.consecutive_speech_chunks += 1
            self.consecutive_silence_chunks = 0
        else:
            self.consecutive_silence_chunks += 1
            self.consecutive_speech_chunks = 0

        # State transitions
        if not self.is_speech:
            if self.consecutive_speech_chunks >= self.min_speech_chunks:
                self.is_speech = True
                logger.debug("VAD: Speech started")
        else:
            if self.consecutive_silence_chunks >= self.min_silence_chunks:
                self.is_speech = False
                logger.debug("VAD: Speech ended")

        return self.is_speech, energy

    def visualize(self, energy: float, width: int = 20) -> str:
        """
        Generates an ASCII bar visualization of the energy level.

        Args:
            energy: Current RMS energy.
            width: Width of the max bar in characters.

        Returns:
            str: ASCII string representation.
        """
        # Scale energy typically 0.0 - 0.5 for speech
        bar_count = int(min(energy * 40, width))
        bar_str = "|" * bar_count
        space_str = " " * (width - bar_count)
        return f"[{bar_str}{space_str}]"

    def reset(self):
        """Reset the detector state."""
        self.is_speech = False
        self.consecutive_speech_chunks = 0
        self.consecutive_silence_chunks = 0
        self.buffer = b""
        self.warmup_counter = self.warmup_chunks


def add_vad_args(parser):
    """
    Add VAD-related arguments to an argparse parser.

    Args:
        parser: argparse.ArgumentParser or legacy optparse (duck typed).
                Must have add_argument method.
    """
    parser.add_argument(
        "--vad",
        action="store_true",
        help="Enable Voice Activity Detection (hands-free mode)",
    )
    parser.add_argument(
        "--vad-aggressiveness",
        type=int,
        default=3,
        choices=[0, 1, 2, 3],
        help="VAD aggressiveness level (0-3). Higher is more aggressive in filtering out non-speech.",
    )
    parser.add_argument(
        "--vad-energy-threshold",
        type=float,
        default=0.005,
        help="Minimum RMS energy threshold for VAD to trigger (0.0-1.0).",
    )
