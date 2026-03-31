"""Voice Activity Detection — Detects speech in audio using WebRTC VAD."""

import numpy as np
import webrtcvad


class VoiceActivityDetector:

    def __init__(self,
        sample_rate: int = 16000,
        aggressiveness: int = 3,
        speech_threshold: int = 6,
        silence_threshold: int = 10,
        frame_duration_ms: int = 30,
        decay_rate: int = 1
    ):
        """
        Initialize Voice Activity Detector.
        
        Args:
            sample_rate: Audio sample rate in Hz
            aggressiveness: webrtcvad sensitivity (0-3, higher = more aggressive filtering)
            speech_threshold: Frames of speech needed to trigger speech state
            silence_threshold: Frames of silence needed to end speech state
            frame_duration_ms: Frame duration (10, 20, or 30 ms)
            decay_rate: How fast counters decay on opposite detection (gradual reset)
        """
        self.sample_rate = sample_rate
        self.vad = webrtcvad.Vad(aggressiveness)

        samples_per_frame = int(sample_rate * frame_duration_ms / 1000)
        self.bytes_per_frame = samples_per_frame * np.dtype(np.int16).itemsize

        self.speech_threshold = speech_threshold
        self.silence_threshold = silence_threshold
        self.decay_rate = decay_rate

        self._leftover_audio_bytes = b""
        self._speech_frames = 0
        self._silence_frames = 0
        self._is_speech = False

    def process(self, audio_chunk: np.ndarray) -> bool:
        """Process int16 audio chunk, return True if speech detected."""

        audio_bytes_buffer = self._leftover_audio_bytes + audio_chunk.tobytes()

        offset = 0
        while offset + self.bytes_per_frame <= len(audio_bytes_buffer):
            current_frame = audio_bytes_buffer[offset:offset + self.bytes_per_frame]
            offset += self.bytes_per_frame
            is_current_frame_speech = self.vad.is_speech(current_frame, self.sample_rate)

            if is_current_frame_speech:
                self._speech_frames += 1
                # Gradual decay of silence counter
                self._silence_frames = max(0, self._silence_frames - self.decay_rate)
            else:
                self._silence_frames += 1
                # Gradual decay of speech counter
                self._speech_frames = max(0, self._speech_frames - self.decay_rate)

            if not self._is_speech and self._speech_frames >= self.speech_threshold:
                self._is_speech = True
            elif self._is_speech and self._silence_frames >= self.silence_threshold:
                self._is_speech = False

        self._leftover_audio_bytes = audio_bytes_buffer[offset:]
        return self._is_speech

    def reset(self):
        """Reset state for a new utterance."""
        self._leftover_audio_bytes = b""
        self._speech_frames = 0
        self._silence_frames = 0
        self._is_speech = False
