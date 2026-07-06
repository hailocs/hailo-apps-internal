"""Pure-Python unit tests for the Voice Activity Detector used by the
voice_controlled_camera app (``gen_ai_utils.voice_processing.vad``).

``webrtcvad`` is a native C extension whose ``Vad.is_speech`` verdict we make
fully deterministic by stubbing the module, so every test here exercises the
*Python* logic: the energy gate, the per-chunk majority vote, the
speech/silence debounce state machine, warmup gating and ``reset``.

No microphone, no device, no audio backend — synthetic numpy frames only.
"""

import argparse
import sys
from unittest.mock import MagicMock

import numpy as np
import pytest

from . import _stubs

_stubs.install()

# Import the real VAD logic; only ``webrtcvad`` underneath it is stubbed.
from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.vad import (  # noqa: E402
    VoiceActivityDetector,
    add_vad_args,
)

pytestmark = pytest.mark.community


# Use a real-world telephony rate (16 kHz). At a 30 ms VAD frame that is
# 480 samples/frame. We size incoming chunks at 30 ms (480 samples) too, so
# one incoming chunk == exactly one VAD frame, which keeps the math simple.
SAMPLE_RATE = 16000
CHUNK_SIZE = 480  # 30 ms at 16 kHz


def _set_vad_verdict(detector: VoiceActivityDetector, verdict: bool):
    """Force the stubbed webrtcvad backend to a fixed is_speech() verdict."""
    detector.vad = MagicMock()
    detector.vad.is_speech.return_value = verdict


def _loud_chunk(n=CHUNK_SIZE, amp=0.5):
    """A constant-amplitude frame whose RMS energy is ``amp`` (> threshold)."""
    return np.full(n, amp, dtype=np.float32)


def _quiet_chunk(n=CHUNK_SIZE, amp=0.0):
    """A near-silent frame below the energy threshold."""
    return np.full(n, amp, dtype=np.float32)


def _new_detector(**kwargs):
    """Construct a detector with warmup disabled unless overridden."""
    defaults = dict(
        sample_rate=SAMPLE_RATE,
        chunk_size=CHUNK_SIZE,
        aggressiveness=3,
        min_speech_duration_ms=60,   # -> ~2 chunks of 30 ms
        min_silence_duration_ms=90,  # -> 3 chunks of 30 ms
        energy_threshold=0.05,
        warmup_chunks=0,
    )
    defaults.update(kwargs)
    return VoiceActivityDetector(**defaults)


# ============================================================
# Initialization / derived parameters
# ============================================================


class TestInit:
    def test_frame_size_is_30ms(self):
        det = _new_detector()
        assert det.frame_duration_ms == 30
        assert det.frame_size == int(SAMPLE_RATE * 30 / 1000)  # 480

    def test_min_chunk_counts_derived_from_durations(self):
        # incoming_chunk_ms = 480/16000*1000 = 30 ms
        # min_speech 60ms / 30 = 2 ; min_silence 90ms / 30 = 3
        det = _new_detector(min_speech_duration_ms=60, min_silence_duration_ms=90)
        assert det.min_speech_chunks == 2
        assert det.min_silence_chunks == 3

    def test_min_chunk_counts_floored_to_one(self):
        # A duration shorter than one chunk must still require >= 1 chunk.
        det = _new_detector(min_speech_duration_ms=1, min_silence_duration_ms=1)
        assert det.min_speech_chunks == 1
        assert det.min_silence_chunks == 1

    def test_initial_state_is_silence(self):
        det = _new_detector()
        assert det.is_speech is False
        assert det.consecutive_speech_chunks == 0
        assert det.consecutive_silence_chunks == 0
        assert det.buffer == b""


# ============================================================
# Energy gate + empty-frame edge cases
# ============================================================


class TestEnergyGate:
    def test_empty_chunk_returns_current_state_and_zero_energy(self):
        det = _new_detector()
        is_speech, energy = det.process(np.array([], dtype=np.float32))
        assert is_speech is False
        assert energy == 0.0

    def test_quiet_chunk_below_threshold_never_triggers(self):
        det = _new_detector()
        _set_vad_verdict(det, True)  # even if VAD *would* say speech...
        for _ in range(10):
            is_speech, energy = det.process(_quiet_chunk())
        # ...the energy gate short-circuits before webrtcvad is consulted.
        det.vad.is_speech.assert_not_called()
        assert is_speech is False

    def test_energy_value_is_rms_of_chunk(self):
        det = _new_detector()
        _set_vad_verdict(det, False)
        _, energy = det.process(_loud_chunk(amp=0.5))
        assert energy == pytest.approx(0.5, abs=1e-3)


# ============================================================
# Per-chunk majority vote (70% of VAD frames must be speech)
# ============================================================


class TestMajorityVote:
    def test_all_frames_speech_counts_as_speech_chunk(self):
        det = _new_detector(min_speech_duration_ms=30)  # 1 chunk to start
        _set_vad_verdict(det, True)
        is_speech, _ = det.process(_loud_chunk())
        assert is_speech is True

    def test_all_frames_nonspeech_with_energy_is_silence(self):
        det = _new_detector(min_speech_duration_ms=30)
        _set_vad_verdict(det, False)
        # Loud enough to pass the energy gate, but webrtcvad says "not speech".
        is_speech, energy = det.process(_loud_chunk())
        assert energy > det.energy_threshold
        assert is_speech is False

    def test_below_70pct_threshold_is_not_speech(self):
        # Feed a big chunk that splits into several VAD frames; make only ~half
        # of them return speech so the 0.7 ratio is NOT met.
        big_chunk = _loud_chunk(n=CHUNK_SIZE * 4)  # 4 frames
        det = _new_detector(chunk_size=CHUNK_SIZE * 4, min_speech_duration_ms=30)
        det.vad = MagicMock()
        det.vad.is_speech.side_effect = [True, True, False, False]
        is_speech, _ = det.process(big_chunk)
        assert is_speech is False


# ============================================================
# Debounce state machine: speech start / stop transitions
# ============================================================


class TestStateMachine:
    def test_speech_starts_only_after_min_speech_chunks(self):
        det = _new_detector(min_speech_duration_ms=60)  # needs 2 chunks
        _set_vad_verdict(det, True)
        # First speech chunk: not enough yet.
        is_speech, _ = det.process(_loud_chunk())
        assert is_speech is False
        assert det.consecutive_speech_chunks == 1
        # Second speech chunk crosses the threshold.
        is_speech, _ = det.process(_loud_chunk())
        assert is_speech is True

    def test_speech_stops_only_after_min_silence_chunks(self):
        det = _new_detector(min_speech_duration_ms=30, min_silence_duration_ms=90)
        # Drive into speech state.
        _set_vad_verdict(det, True)
        det.process(_loud_chunk())
        assert det.is_speech is True
        # Now feed silence: needs 3 silence chunks to drop out.
        for i in range(2):
            is_speech, _ = det.process(_quiet_chunk())
            assert is_speech is True, f"dropped too early at silence chunk {i+1}"
        is_speech, _ = det.process(_quiet_chunk())
        assert is_speech is False

    def test_intermittent_speech_resets_silence_counter(self):
        det = _new_detector(min_speech_duration_ms=30, min_silence_duration_ms=90)
        _set_vad_verdict(det, True)
        det.process(_loud_chunk())  # enter speech
        det.process(_quiet_chunk())  # 1 silence
        det.process(_quiet_chunk())  # 2 silence
        assert det.consecutive_silence_chunks == 2
        det.process(_loud_chunk())  # speech again -> silence counter resets
        assert det.consecutive_silence_chunks == 0
        assert det.is_speech is True

    def test_silence_only_audio_stays_silent(self):
        det = _new_detector()
        _set_vad_verdict(det, False)
        for _ in range(50):
            is_speech, _ = det.process(_quiet_chunk())
        assert is_speech is False
        assert det.consecutive_speech_chunks == 0


# ============================================================
# Warmup gating
# ============================================================


class TestWarmup:
    def test_warmup_suppresses_detection_and_reports_zero_energy(self):
        det = _new_detector(warmup_chunks=3, min_speech_duration_ms=30)
        _set_vad_verdict(det, True)
        for _ in range(3):
            is_speech, energy = det.process(_loud_chunk())
            assert is_speech is False
            assert energy == 0.0
        # webrtcvad must not even be consulted during warmup.
        det.vad.is_speech.assert_not_called()

    def test_detection_resumes_after_warmup(self):
        det = _new_detector(warmup_chunks=2, min_speech_duration_ms=30)
        _set_vad_verdict(det, True)
        det.process(_loud_chunk())  # warmup 1
        det.process(_loud_chunk())  # warmup 2
        is_speech, energy = det.process(_loud_chunk())  # real
        assert is_speech is True
        assert energy > 0.0


# ============================================================
# reset()
# ============================================================


class TestReset:
    def test_reset_clears_state_and_restores_warmup(self):
        det = _new_detector(warmup_chunks=5, min_speech_duration_ms=30)
        det.warmup_counter = 0  # pretend warmup already elapsed
        _set_vad_verdict(det, True)
        det.process(_loud_chunk())
        assert det.is_speech is True
        det.reset()
        assert det.is_speech is False
        assert det.consecutive_speech_chunks == 0
        assert det.consecutive_silence_chunks == 0
        assert det.buffer == b""
        assert det.warmup_counter == det.warmup_chunks == 5


# ============================================================
# visualize() — pure string helper
# ============================================================


class TestVisualize:
    def test_zero_energy_is_empty_bar(self):
        det = _new_detector()
        out = det.visualize(0.0, width=20)
        assert out == "[" + " " * 20 + "]"

    def test_high_energy_clamps_to_width(self):
        det = _new_detector()
        out = det.visualize(99.0, width=10)
        assert out == "[" + "|" * 10 + "]"

    def test_partial_energy_bar_length(self):
        det = _new_detector()
        # bar_count = int(min(energy*40, width)); energy 0.1 -> 4 bars
        out = det.visualize(0.1, width=20)
        assert out.count("|") == 4
        assert len(out) == 22  # 20 inner + 2 brackets


# ============================================================
# add_vad_args() — CLI wiring (duck-typed parser)
# ============================================================


class TestAddVadArgs:
    def test_defaults(self):
        parser = argparse.ArgumentParser()
        add_vad_args(parser)
        args = parser.parse_args([])
        assert args.vad is False
        assert args.vad_aggressiveness == 3
        assert args.vad_energy_threshold == pytest.approx(0.005)

    def test_enable_and_override(self):
        parser = argparse.ArgumentParser()
        add_vad_args(parser)
        args = parser.parse_args(
            ["--vad", "--vad-aggressiveness", "1", "--vad-energy-threshold", "0.2"]
        )
        assert args.vad is True
        assert args.vad_aggressiveness == 1
        assert args.vad_energy_threshold == pytest.approx(0.2)

    def test_aggressiveness_choices_enforced(self):
        parser = argparse.ArgumentParser()
        add_vad_args(parser)
        with pytest.raises(SystemExit):
            parser.parse_args(["--vad-aggressiveness", "9"])
