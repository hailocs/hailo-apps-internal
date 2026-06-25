"""Pure-Python unit tests for ``visual_quality_inspector/backend.py``.

Covers (no device / no VLM / no camera -- everything is stubbed in conftest):

  * ``Backend.convert_resize_image`` channel-order handling -- the "RPI colour
    fix": with ``is_bgr=True`` an OpenCV/USB BGR frame is swapped to RGB; with
    ``is_bgr=False`` an RPi RGB888 frame is left untouched.
  * ``Backend.convert_resize_image`` central-crop geometry / output shape.
  * The inference timeout path: ``_execute_inference`` now catches
    ``queue.Empty`` (previously ``mp.TimeoutError``) -- a timed-out response
    queue must return the timeout result *and* trigger queue cleanup.
  * Error / cleanup edge cases on the inference path.
"""

import queue
import sys
from unittest.mock import MagicMock

import numpy as np
import pytest

pytestmark = pytest.mark.community

# Stubs (cv2 / hailo_platform / genai / picamera2) are installed by conftest.py
# before this import runs.
from community.apps.gen_ai_apps.visual_quality_inspector.backend import Backend


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _make_backend_without_process():
    """Build a Backend instance without starting the real worker process.

    ``Backend.__init__`` spins up an ``mp.Process`` running the VLM worker. For
    pure-python tests we bypass ``__init__`` entirely (``__new__``) and wire up
    only the attributes the methods under test need, using plain in-memory
    fakes for the queues.
    """
    b = Backend.__new__(Backend)
    b.system_prompt = "test system prompt"
    b.max_tokens = 300
    b.temperature = 0.1
    b.seed = 42
    b._request_queue = MagicMock(name="request_queue")
    b._response_queue = MagicMock(name="response_queue")
    return b


def _solid_frame(h, w, channels=(10, 20, 30)):
    """RGB-or-BGR frame where every pixel == ``channels`` (a 3-tuple)."""
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    frame[:, :, 0] = channels[0]
    frame[:, :, 1] = channels[1]
    frame[:, :, 2] = channels[2]
    return frame


# --------------------------------------------------------------------------- #
# convert_resize_image -- channel order (the RPI colour fix)
# --------------------------------------------------------------------------- #
class TestConvertResizeChannelOrder:
    def test_bgr_source_is_swapped_to_rgb(self):
        # Source channels (first, second, third) = (10, 20, 30) interpreted as
        # B=10, G=20, R=30. After BGR->RGB the channel order must reverse so the
        # output's first channel == 30 and last channel == 10.
        bgr = _solid_frame(480, 640, channels=(10, 20, 30))
        out = Backend.convert_resize_image(bgr, target_size=(336, 336), is_bgr=True)
        assert out.shape == (336, 336, 3)
        assert int(out[0, 0, 0]) == 30  # was R, now first
        assert int(out[0, 0, 1]) == 20  # green unchanged
        assert int(out[0, 0, 2]) == 10  # was B, now last

    def test_rgb_source_is_not_swapped(self):
        # RPi RGB888 frame -- is_bgr=False must NOT reorder channels.
        rgb = _solid_frame(480, 640, channels=(10, 20, 30))
        out = Backend.convert_resize_image(rgb, target_size=(336, 336), is_bgr=False)
        assert out.shape == (336, 336, 3)
        assert int(out[0, 0, 0]) == 10  # unchanged
        assert int(out[0, 0, 1]) == 20
        assert int(out[0, 0, 2]) == 30

    def test_default_is_bgr_true(self):
        # Default arg is is_bgr=True -> behaves like the BGR (swap) case.
        bgr = _solid_frame(100, 100, channels=(1, 2, 3))
        out = Backend.convert_resize_image(bgr, target_size=(50, 50))
        assert int(out[0, 0, 0]) == 3
        assert int(out[0, 0, 2]) == 1

    def test_bgr_and_rgb_outputs_are_reverse_of_each_other(self):
        frame = _solid_frame(200, 200, channels=(5, 90, 200))
        as_bgr = Backend.convert_resize_image(frame, target_size=(64, 64), is_bgr=True)
        as_rgb = Backend.convert_resize_image(frame, target_size=(64, 64), is_bgr=False)
        assert int(as_bgr[0, 0, 0]) == int(as_rgb[0, 0, 2])
        assert int(as_bgr[0, 0, 2]) == int(as_rgb[0, 0, 0])


# --------------------------------------------------------------------------- #
# convert_resize_image -- geometry / shape / dtype
# --------------------------------------------------------------------------- #
class TestConvertResizeGeometry:
    def test_output_shape_matches_target(self):
        out = Backend.convert_resize_image(_solid_frame(720, 1280), target_size=(336, 336))
        assert out.shape[:2] == (336, 336)

    def test_non_square_target(self):
        out = Backend.convert_resize_image(_solid_frame(480, 640), target_size=(256, 128))
        # target_size is (width, height) -> output rows=height, cols=width.
        assert out.shape[0] == 128
        assert out.shape[1] == 256

    def test_output_dtype_uint8(self):
        out = Backend.convert_resize_image(_solid_frame(480, 640), target_size=(336, 336))
        assert out.dtype == np.uint8

    def test_upscales_small_input_to_target(self):
        # Input smaller than target must still be covered (scale >= 1).
        out = Backend.convert_resize_image(_solid_frame(50, 50), target_size=(336, 336))
        assert out.shape[:2] == (336, 336)


# --------------------------------------------------------------------------- #
# _execute_inference -- normal, error and TIMEOUT (queue.Empty) paths
# --------------------------------------------------------------------------- #
class TestExecuteInferenceTimeout:
    def test_timeout_returns_timeout_result(self):
        """A response queue that raises queue.Empty must yield the timeout dict."""
        b = _make_backend_without_process()
        b._response_queue.get.side_effect = queue.Empty()
        # request/response queues report empty so cleanup loop exits immediately.
        b._request_queue.empty.return_value = True
        b._response_queue.empty.return_value = True

        result = b._execute_inference({"payload": 1}, timeout=7)

        assert "timed out" in result["answer"].lower()
        assert "7" in result["answer"]
        assert result["time"] == "7+ seconds"

    def test_timeout_triggers_queue_cleanup(self):
        """On timeout, both queues must be drained via _cleanup_queues."""
        b = _make_backend_without_process()
        b._response_queue.get.side_effect = queue.Empty()

        # Each queue has one stale item, then becomes empty.
        req_empty = iter([False, True])
        resp_empty = iter([False, True])
        b._request_queue.empty.side_effect = lambda: next(req_empty)
        b._response_queue.empty.side_effect = lambda: next(resp_empty)

        b._execute_inference({"payload": 1}, timeout=5)

        # The stale item in each queue was drained with get_nowait.
        b._request_queue.get_nowait.assert_called_once()
        b._response_queue.get_nowait.assert_called_once()

    def test_timeout_uses_queue_empty_not_mp_timeouterror(self):
        """Regression: the except clause catches queue.Empty (not mp.TimeoutError).

        If the code still caught only mp.TimeoutError, a queue.Empty would
        escape uncaught. Asserting no exception escapes proves the fix.
        """
        b = _make_backend_without_process()
        b._response_queue.get.side_effect = queue.Empty()
        b._request_queue.empty.return_value = True
        b._response_queue.empty.return_value = True

        # Must not raise.
        result = b._execute_inference({"payload": 1}, timeout=3)
        assert isinstance(result, dict)

    def test_request_is_enqueued_before_waiting(self):
        b = _make_backend_without_process()
        b._response_queue.get.return_value = {"result": {"answer": "ok", "time": "1s"}, "error": None}
        payload = {"numpy_image": "img", "prompts": {}}
        b._execute_inference(payload, timeout=9)
        b._request_queue.put.assert_called_once_with(payload)
        b._response_queue.get.assert_called_once_with(timeout=9)


class TestExecuteInferenceSuccessAndError:
    def test_success_returns_result_dict(self):
        b = _make_backend_without_process()
        expected = {"answer": "PASS - no defects", "time": "2.10 seconds"}
        b._response_queue.get.return_value = {"result": expected, "error": None}
        result = b._execute_inference({}, timeout=10)
        assert result == expected

    def test_worker_error_is_surfaced(self):
        b = _make_backend_without_process()
        b._response_queue.get.return_value = {"result": None, "error": "model exploded"}
        b._request_queue.empty.return_value = True
        b._response_queue.empty.return_value = True
        result = b._execute_inference({}, timeout=10)
        assert "model exploded" in result["answer"]
        assert result["answer"].startswith("Error:")

    def test_generic_queue_exception_is_caught_and_cleans_up(self):
        b = _make_backend_without_process()
        b._response_queue.get.side_effect = RuntimeError("queue broke")
        b._request_queue.empty.return_value = True
        b._response_queue.empty.return_value = True
        result = b._execute_inference({}, timeout=10)
        assert "Queue error" in result["answer"]
        assert "queue broke" in result["answer"]
        assert result["time"] == "error"


# --------------------------------------------------------------------------- #
# _cleanup_queues -- edge behaviour
# --------------------------------------------------------------------------- #
class TestCleanupQueues:
    def test_cleanup_on_empty_queues_is_noop(self):
        b = _make_backend_without_process()
        b._request_queue.empty.return_value = True
        b._response_queue.empty.return_value = True
        b._cleanup_queues()
        b._request_queue.get_nowait.assert_not_called()
        b._response_queue.get_nowait.assert_not_called()

    def test_cleanup_drains_multiple_items(self):
        b = _make_backend_without_process()
        req_empty = iter([False, False, True])
        b._request_queue.empty.side_effect = lambda: next(req_empty)
        b._response_queue.empty.return_value = True
        b._cleanup_queues()
        assert b._request_queue.get_nowait.call_count == 2

    def test_cleanup_breaks_on_get_nowait_exception(self):
        b = _make_backend_without_process()
        # empty() keeps saying "not empty" but get_nowait raises -> must break,
        # not loop forever.
        b._request_queue.empty.return_value = False
        b._request_queue.get_nowait.side_effect = queue.Empty()
        b._response_queue.empty.return_value = True
        b._cleanup_queues()  # must return without hanging
        b._request_queue.get_nowait.assert_called_once()


# --------------------------------------------------------------------------- #
# vlm_inference -- wires convert_resize_image + prompts through to _execute
# --------------------------------------------------------------------------- #
class TestVlmInferenceWiring:
    def test_passes_is_bgr_through_to_conversion(self, monkeypatch):
        b = _make_backend_without_process()
        captured = {}

        def fake_convert(image, is_bgr=True):
            captured["is_bgr"] = is_bgr
            return image

        monkeypatch.setattr(b, "convert_resize_image", fake_convert)
        b._execute_inference = lambda data, timeout: {"data": data, "timeout": timeout}

        result = b.vlm_inference(np.zeros((4, 4, 3), np.uint8), "is it ok?", timeout=12, is_bgr=False)

        assert captured["is_bgr"] is False
        assert result["timeout"] == 12
        sent = result["data"]
        assert sent["prompts"]["system_prompt"] == "test system prompt"
        assert sent["prompts"]["user_prompt"] == "is it ok?"
        assert "numpy_image" in sent
