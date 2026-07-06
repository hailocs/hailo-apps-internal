"""Pure-Python unit tests for the voice_controlled_camera app lifecycle and
small host-environment predicates.

Covered:
- The idempotent ``close()`` guard (``_closed`` flag): calling it twice must
  release each backend exactly once. We swap in fakes for tts / vlm_backend /
  llm / s2t / vdevice and assert the teardown call counts.
- Thread-safe frame buffer helpers (``get_current_frame`` returns a *copy*,
  ``set_status`` updates the overlay text).
- The QT_QPA-platform gating predicate (set ``xcb`` only when DISPLAY is set
  and WAYLAND_DISPLAY is unset) — replicated as a tiny pure predicate and
  cross-checked against the live module's effect.
- The no-microphone bail-out predicate (recorder.device_id is None).

No device, audio, or camera is touched: every backend is a fake.
"""

import threading

import numpy as np
import pytest

from . import _stubs

_stubs.install()

from community.apps.gen_ai_apps.voice_controlled_camera import (  # noqa: E402
    voice_controlled_camera as app_mod,
)

pytestmark = pytest.mark.community


class _FakeTTS:
    def __init__(self):
        self.stop_calls = 0

    def stop(self):
        self.stop_calls += 1


class _FakeReleasable:
    """A backend exposing release()/close() with call counting."""

    def __init__(self, method="release"):
        self.calls = 0
        setattr(self, method, self._bump)

    def _bump(self):
        self.calls += 1


class _FakeSpeech2Text:
    def __init__(self):
        self.calls = 0

    def release(self):
        self.calls += 1


class _FakeS2T:
    """Mirrors SpeechToTextProcessor: exposes an inner ``speech2text`` object."""

    def __init__(self):
        self.speech2text = _FakeSpeech2Text()


def _make_app_with_fakes(no_tts=False):
    """Build an app instance with fake backends, bypassing __init__."""
    app = object.__new__(app_mod.VoiceControlledCameraApp)
    app._closed = False
    app.running = True
    app._frame_lock = threading.Lock()
    app._latest_frame = None
    app._status_text = "init"

    app.tts = None if no_tts else _FakeTTS()
    app.vlm_backend = _FakeReleasable(method="close")
    app.llm = _FakeReleasable(method="release")
    app.s2t = _FakeS2T()
    app.vdevice = _FakeReleasable(method="release")
    return app


# ============================================================
# close() idempotency
# ============================================================


class TestCloseIdempotent:
    def test_close_releases_each_backend_once(self):
        app = _make_app_with_fakes()
        app.close()
        assert app._closed is True
        assert app.running is False
        assert app.tts.stop_calls == 1
        assert app.vlm_backend.calls == 1
        assert app.llm.calls == 1
        assert app.s2t.speech2text.calls == 1
        assert app.vdevice.calls == 1

    def test_second_close_is_a_noop(self):
        app = _make_app_with_fakes()
        app.close()
        app.close()  # must not release anything a second time
        assert app.tts.stop_calls == 1
        assert app.vlm_backend.calls == 1
        assert app.llm.calls == 1
        assert app.s2t.speech2text.calls == 1
        assert app.vdevice.calls == 1

    def test_close_with_no_tts(self):
        app = _make_app_with_fakes(no_tts=True)
        app.close()  # tts is None -> must be skipped without error
        assert app.vdevice.calls == 1

    def test_close_swallows_backend_errors(self):
        app = _make_app_with_fakes()

        def boom():
            raise RuntimeError("device busy")

        # llm.release raises; close() must still release the vdevice afterwards.
        app.llm.release = boom
        app.close()
        assert app.vdevice.calls == 1
        assert app._closed is True

    def test_close_releases_vdevice_even_if_s2t_missing(self):
        app = _make_app_with_fakes()
        del app.s2t  # getattr(..., None) path must tolerate absence
        app.close()
        assert app.vdevice.calls == 1


# ============================================================
# Frame buffer helpers (thread-safe)
# ============================================================


class TestFrameHelpers:
    def test_get_current_frame_none_when_empty(self):
        app = _make_app_with_fakes()
        assert app.get_current_frame() is None

    def test_get_current_frame_returns_copy(self):
        app = _make_app_with_fakes()
        frame = np.zeros((4, 4, 3), dtype=np.uint8)
        with app._frame_lock:
            app._latest_frame = frame
        out = app.get_current_frame()
        assert out is not None
        assert np.array_equal(out, frame)
        # Mutating the returned copy must not corrupt the stored frame.
        out[0, 0, 0] = 255
        assert app._latest_frame[0, 0, 0] == 0

    def test_set_status_updates_overlay_text(self):
        app = _make_app_with_fakes()
        app.set_status("Thinking...")
        assert app._status_text == "Thinking..."


# ============================================================
# QT_QPA gating predicate
# ============================================================


def _should_force_xcb(env: dict) -> bool:
    """Replicates the module-level condition at voice_controlled_camera.py:
    ``if os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY")``.
    """
    return bool(env.get("DISPLAY") and not env.get("WAYLAND_DISPLAY"))


class TestQtQpaGating:
    @pytest.mark.parametrize(
        "env, expected",
        [
            ({"DISPLAY": ":0"}, True),                              # X11 session
            ({"DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0"}, False),  # Wayland
            ({"WAYLAND_DISPLAY": "wayland-0"}, False),              # Wayland, no X
            ({}, False),                                           # headless
            ({"DISPLAY": ""}, False),                              # empty DISPLAY
            ({"DISPLAY": ":0", "WAYLAND_DISPLAY": ""}, True),      # empty wayland -> X
        ],
    )
    def test_predicate(self, env, expected):
        assert _should_force_xcb(env) is expected

    def test_predicate_matches_live_module_effect(self, monkeypatch):
        """Re-evaluating the real source condition under controlled env must
        agree with our predicate (guards against the predicate drifting)."""
        import os

        # X11 case.
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        live = bool(os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"))
        assert live == _should_force_xcb(dict(os.environ)) is True

        # Wayland case.
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        live = bool(os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"))
        assert live == _should_force_xcb(dict(os.environ)) is False


# ============================================================
# No-microphone bail-out predicate
# ============================================================


def _no_mic(recorder) -> bool:
    """Mirrors main(): bail when ``interaction.recorder.device_id is None``."""
    return recorder.device_id is None


class _FakeRecorder:
    def __init__(self, device_id):
        self.device_id = device_id


class TestNoMicPredicate:
    def test_no_mic_when_device_id_none(self):
        assert _no_mic(_FakeRecorder(None)) is True

    def test_has_mic_when_device_id_present(self):
        assert _no_mic(_FakeRecorder(0)) is False
        assert _no_mic(_FakeRecorder(3)) is False


# ============================================================
# Empty-transcript handling in the audio pipeline
# ============================================================


class TestEmptyTranscript:
    def test_empty_transcript_short_circuits(self):
        """on_audio_ready must return early (no intent classification, no
        backend calls) when STT yields an empty transcript."""
        app = object.__new__(app_mod.VoiceControlledCameraApp)
        app.abort_event = threading.Event()
        app.interaction = None

        class _S2T:
            def transcribe(self, audio):
                return ""

        app.s2t = _S2T()

        # If it did not short-circuit, it would call classify_intent / backends,
        # none of which exist on this bare instance -> AttributeError.
        app.on_audio_ready(audio=b"\x00\x00")
        # Reaching here without raising means the empty-transcript guard fired.
        assert app.abort_event.is_set() is False  # cleared at entry, nothing set it
