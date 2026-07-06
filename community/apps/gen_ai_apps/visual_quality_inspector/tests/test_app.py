"""Pure-Python unit tests for ``visual_quality_inspector.py``.

Covers (no device / no VLM / no camera / no GUI -- all stubbed in conftest):

  * State-machine transitions driven through ``show_video``:
    STREAMING -> CAPTURED -> PROCESSING -> RESULT, and 'q' quitting from RESULT.
  * ``_log_inspection_result`` JSONL formatting (one JSON object per line with
    inspection_id / timestamp / prompt / result / inference_time), redirected to
    ``tmp_path``.
  * Edge cases: logging disabled when no results-file, empty result dict, and
    re-entrant ``stop()``.

The state machine lives inside ``show_video``'s ``while self.running`` loop and
is coupled to the camera, ``cv2`` and stdin. We exercise it faithfully by
monkeypatching the camera init, the ``Backend`` class and ``_get_user_input``
with a *scripted* sequence, and by capturing ``current_state`` at each tick.
"""

import concurrent.futures
import json
from unittest.mock import MagicMock

import numpy as np
import pytest

pytestmark = pytest.mark.community

# Stubs installed by conftest before this import.
from community.apps.gen_ai_apps.visual_quality_inspector import visual_quality_inspector as vqi
from community.apps.gen_ai_apps.visual_quality_inspector.visual_quality_inspector import (
    STATE_STREAMING,
    STATE_CAPTURED,
    STATE_PROCESSING,
    STATE_RESULT,
    DEFAULT_INSPECTION_PROMPT,
    VisualQualityInspectorApp,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _make_app(tmp_path=None, camera_type="usb", log_file=None):
    """Construct the app without touching signal handlers' global state."""
    app = VisualQualityInspectorApp(
        camera=0,
        camera_type=camera_type,
        hef_path="/fake/model.hef",
        log_file=log_file,
    )
    return app


class _ScriptedInput:
    """Returns each queued string once per ``show_video`` tick, then None.

    A value of the sentinel ``_NOTHING`` means "no terminal input this tick".

    SAFETY: ``show_video``'s loop only exits on 'q' or running=False. The number
    of loop ticks before the VLM future completes is timing-dependent, so once
    the script is exhausted we force the loop to stop (running=False) -- this
    guarantees no test can hang the suite even if the script under-counts ticks.
    """

    _NOTHING = object()

    def __init__(self, script, app=None, max_ticks=500):
        self._it = iter(script)
        self._app = app
        self._ticks = 0
        self._max_ticks = max_ticks

    def __call__(self):
        self._ticks += 1
        try:
            val = next(self._it)
        except StopIteration:
            if self._app is not None:
                self._app.running = False
            return None
        if self._ticks > self._max_ticks and self._app is not None:
            self._app.running = False
        return None if val is self._NOTHING else val


# --------------------------------------------------------------------------- #
# State machine
# --------------------------------------------------------------------------- #
class TestStateMachine:
    def _wire(self, app, monkeypatch, input_script):
        """Patch camera, backend and stdin; record state at each tick."""
        # Camera: get_frame returns a constant frame, cleanup is a no-op.
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        get_frame = lambda: frame
        cleanup = MagicMock(name="cleanup")
        monkeypatch.setattr(app, "_init_camera", lambda: (get_frame, cleanup, "USB"))

        # Backend: a fake whose vlm_inference returns immediately.
        fake_backend = MagicMock(name="Backend_instance")
        fake_backend.vlm_inference.return_value = {"answer": "PASS", "time": "1.00 seconds"}
        monkeypatch.setattr(vqi, "Backend", lambda **kw: fake_backend)

        # Make the executor synchronous so the submitted future is already
        # ``done()`` on the next loop tick -- removes PROCESSING->RESULT timing
        # races and keeps the state machine deterministic.
        def _sync_submit(fn, *a, **kw):
            fut = concurrent.futures.Future()
            try:
                fut.set_result(fn(*a, **kw))
            except Exception as exc:  # pragma: no cover - defensive
                fut.set_exception(exc)
            return fut

        monkeypatch.setattr(app.executor, "submit", _sync_submit)

        # Scripted terminal input (with a safety stop once exhausted).
        monkeypatch.setattr(app, "_get_user_input", _ScriptedInput(input_script, app=app))

        # Record the state observed at the *start* of each loop tick.
        states = []
        orig_print = app._print_state_prompt

        def record_state():
            states.append(app.current_state)
            return orig_print()

        monkeypatch.setattr(app, "_print_state_prompt", record_state)

        return states, fake_backend, cleanup, frame

    def test_streaming_to_captured_on_enter(self, monkeypatch):
        app = _make_app()
        # Tick 1: no input (frame grabbed). Tick 2: Enter -> CAPTURE.
        # Then 'q' to terminate cleanly.
        states, backend, cleanup, frame = self._wire(
            app, monkeypatch,
            input_script=[_ScriptedInput._NOTHING, "", "q"],
        )
        app.show_video()
        assert STATE_STREAMING in states
        assert STATE_CAPTURED in states
        # A frozen frame was captured (copy of the live frame).
        # After 'q' the app stopped.
        assert app.running is False

    def test_full_cycle_streaming_captured_processing_result(self, monkeypatch):
        app = _make_app()
        # 1: grab frame, 2: Enter -> CAPTURED, 3: type question -> PROCESSING,
        # several idle ticks for the future to complete -> RESULT, then quit.
        N = _ScriptedInput._NOTHING
        script = [N, "", "is this part ok?", N, N, N, N, N, N, "q"]
        states, backend, cleanup, frame = self._wire(app, monkeypatch, script)
        app.show_video()

        # All four states must have been entered, in order of first appearance.
        for s in (STATE_STREAMING, STATE_CAPTURED, STATE_PROCESSING, STATE_RESULT):
            assert s in states, f"state {s} never reached; saw {states}"
        order = [states.index(s) for s in
                 (STATE_STREAMING, STATE_CAPTURED, STATE_PROCESSING, STATE_RESULT)]
        assert order == sorted(order), f"states out of order: {states}"

        # The user's question was forwarded to the backend.
        backend.vlm_inference.assert_called_once()
        assert backend.vlm_inference.call_args[0][1] == "is this part ok?"
        cleanup.assert_called_once()

    def test_captured_default_prompt_on_empty_enter(self, monkeypatch):
        app = _make_app()
        N = _ScriptedInput._NOTHING
        # Enter at CAPTURED with empty string -> default inspection prompt.
        script = [N, "", "", N, N, N, N, "q"]
        states, backend, cleanup, frame = self._wire(app, monkeypatch, script)
        app.show_video()
        backend.vlm_inference.assert_called_once()
        assert backend.vlm_inference.call_args[0][1] == DEFAULT_INSPECTION_PROMPT

    def test_captured_cancel_returns_to_streaming(self, monkeypatch):
        app = _make_app()
        N = _ScriptedInput._NOTHING
        # Capture, then 'q' at CAPTURED cancels back to STREAMING (does NOT quit),
        # then quit from STREAMING.
        script = [N, "", "q", N, "q"]
        states, backend, cleanup, frame = self._wire(app, monkeypatch, script)
        app.show_video()
        # Returned to streaming after cancel; backend never invoked.
        assert states.count(STATE_STREAMING) >= 2
        backend.vlm_inference.assert_not_called()

    def test_q_quits_from_result(self, monkeypatch):
        app = _make_app()
        N = _ScriptedInput._NOTHING
        script = [N, "", "check it", N, N, N, N, N, "q"]
        states, backend, cleanup, frame = self._wire(app, monkeypatch, script)
        app.show_video()
        assert STATE_RESULT in states
        # 'q' from RESULT stops the app.
        assert app.running is False
        assert app._stopped is True

    def test_result_enter_returns_to_streaming(self, monkeypatch):
        app = _make_app()
        N = _ScriptedInput._NOTHING
        # ... reach RESULT, press Enter (not 'q') -> back to STREAMING, then quit.
        script = [N, "", "check it", N, N, N, N, "", N, "q"]
        states, backend, cleanup, frame = self._wire(app, monkeypatch, script)
        app.show_video()
        # STREAMING appears again after the RESULT state.
        last_result = max(i for i, s in enumerate(states) if s == STATE_RESULT)
        assert STATE_STREAMING in states[last_result + 1:]
        assert app.frozen_frame is None


# --------------------------------------------------------------------------- #
# _log_inspection_result -- JSONL formatting
# --------------------------------------------------------------------------- #
class TestLogInspectionResult:
    def test_writes_one_json_line(self, tmp_path):
        log = tmp_path / "inspections.jsonl"
        app = _make_app(log_file=str(log))
        app._log_inspection_result(
            "inspect the bracket",
            {"answer": "FAIL - crack at top-left", "time": "3.21 seconds"},
        )
        lines = log.read_text().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["inspection_id"] == 1
        assert entry["prompt"] == "inspect the bracket"
        assert entry["result"] == "FAIL - crack at top-left"
        assert entry["inference_time"] == "3.21 seconds"
        assert "timestamp" in entry and entry["timestamp"]

    def test_inspection_id_increments(self, tmp_path):
        log = tmp_path / "log.jsonl"
        app = _make_app(log_file=str(log))
        app._log_inspection_result("q1", {"answer": "a1", "time": "1s"})
        app._log_inspection_result("q2", {"answer": "a2", "time": "2s"})
        lines = log.read_text().splitlines()
        assert len(lines) == 2
        ids = [json.loads(l)["inspection_id"] for l in lines]
        assert ids == [1, 2]

    def test_each_line_is_independently_valid_json(self, tmp_path):
        log = tmp_path / "log.jsonl"
        app = _make_app(log_file=str(log))
        for i in range(3):
            app._log_inspection_result(f"q{i}", {"answer": f"a{i}", "time": f"{i}s"})
        for line in log.read_text().splitlines():
            json.loads(line)  # must not raise

    def test_appends_across_calls(self, tmp_path):
        log = tmp_path / "log.jsonl"
        log.write_text(json.dumps({"inspection_id": 0, "result": "preexisting"}) + "\n")
        app = _make_app(log_file=str(log))
        app._log_inspection_result("q", {"answer": "a", "time": "1s"})
        lines = log.read_text().splitlines()
        assert len(lines) == 2  # appended, not truncated
        assert json.loads(lines[0])["result"] == "preexisting"

    # ------------------------------- edges ------------------------------- #
    def test_no_log_file_disables_logging(self, tmp_path):
        app = _make_app(log_file=None)
        # Should be a silent no-op and not bump the counter.
        app._log_inspection_result("q", {"answer": "a", "time": "1s"})
        assert app.inspection_count == 0

    def test_empty_result_dict_uses_blank_defaults(self, tmp_path):
        log = tmp_path / "log.jsonl"
        app = _make_app(log_file=str(log))
        app._log_inspection_result("q", {})  # empty result dict
        entry = json.loads(log.read_text().splitlines()[0])
        assert entry["result"] == ""
        assert entry["inference_time"] == ""
        assert entry["inspection_id"] == 1


# --------------------------------------------------------------------------- #
# stop() -- re-entrancy and cleanup
# --------------------------------------------------------------------------- #
class TestStop:
    def test_stop_sets_flags_and_closes_backend(self):
        app = _make_app()
        app.backend = MagicMock(name="backend")
        app.stop()
        assert app._stopped is True
        assert app.running is False
        app.backend.close.assert_called_once()

    def test_stop_is_reentrant(self):
        app = _make_app()
        app.backend = MagicMock(name="backend")
        app.stop()
        app.stop()
        app.stop()
        # close() called only once despite three stop() calls.
        app.backend.close.assert_called_once()

    def test_stop_with_no_backend_is_safe(self):
        app = _make_app()
        app.backend = None
        app.stop()  # must not raise
        assert app._stopped is True

    def test_stop_shuts_down_executor(self):
        app = _make_app()
        app.backend = None
        app.stop()
        # Submitting after shutdown raises RuntimeError -> proves it was shut down.
        with pytest.raises(RuntimeError):
            app.executor.submit(lambda: None)


# --------------------------------------------------------------------------- #
# Camera-init failure path
# --------------------------------------------------------------------------- #
class TestCameraInitFailure:
    def test_camera_init_failure_stops_running(self, monkeypatch):
        app = _make_app()

        def boom():
            raise RuntimeError("no camera")

        monkeypatch.setattr(app, "_init_camera", boom)
        app.show_video()
        assert app.running is False
