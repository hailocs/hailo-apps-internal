"""Unit tests for the blaze inference wrappers (BlazePalmDetector, BlazeHandLandmark).

These lock in the contract between the wrappers and the cross-platform
``HailoInfer`` async engine (``run(input_batch, callback)`` →
``callback(completion_info, bindings_list=...)`` → ``job.wait()``), which is
what makes the Python-inference variants run on Hailo-8/8L *and* Hailo-10H.

No Hailo device is required: ``HailoInfer`` is replaced with an in-process fake
that mimics the binding/callback protocol. This guards against regressions in
the binding wiring, the error path, and the per-crop batching loop.
"""

import sys
import types
from unittest.mock import MagicMock

import numpy as np
import pytest

pytestmark = pytest.mark.community


# --------------------------------------------------------------------------- #
# Fakes mimicking the HailoInfer / run_async binding protocol
# --------------------------------------------------------------------------- #
class _FakeVStreamInfo:
    def __init__(self, name, shape):
        self.name = name
        self.shape = shape


class _FakeBufferHandle:
    def __init__(self, buf):
        self._buf = buf

    def get_buffer(self):
        return self._buf


class _FakeBinding:
    """Mimics a HailoRT binding: ._output_names + .output(name).get_buffer()."""

    def __init__(self, outputs):
        self._outputs = outputs
        self._output_names = list(outputs.keys())

    def output(self, name):
        return _FakeBufferHandle(self._outputs[name])


class _FakeCompletionInfo:
    def __init__(self, exception=None):
        self.exception = exception


class _FakeJob:
    def wait(self, timeout_ms):
        return None


class FakeHailoInfer:
    """Configurable stand-in for HailoInfer.

    ``outputs`` maps output-layer name -> ndarray returned for every frame.
    ``raise_exception`` injects a completion-info exception to test the error path.
    """

    outputs = {}
    input_shape = (192, 192, 3)
    raise_exception = None
    instances = []
    run_calls = []

    def __init__(self, hef_path, batch_size=1, input_type=None, output_type=None):
        self.hef_path = hef_path
        self.batch_size = batch_size
        self.input_type = input_type
        self.output_type = output_type
        self.closed = False
        FakeHailoInfer.instances.append(self)

    def get_vstream_info(self):
        in_info = [_FakeVStreamInfo("input", self.input_shape)]
        out_info = [_FakeVStreamInfo(n, v.shape) for n, v in self.outputs.items()]
        return in_info, out_info

    def run(self, input_batch, inference_callback_fn):
        FakeHailoInfer.run_calls.append([np.asarray(f) for f in input_batch])
        bindings_list = [_FakeBinding(self.outputs) for _ in input_batch]
        completion = _FakeCompletionInfo(exception=self.raise_exception)
        inference_callback_fn(completion, bindings_list=bindings_list)
        return _FakeJob()

    def close(self):
        self.closed = True

    @classmethod
    def reset(cls, outputs, input_shape=(192, 192, 3), raise_exception=None):
        cls.outputs = outputs
        cls.input_shape = input_shape
        cls.raise_exception = raise_exception
        cls.instances = []
        cls.run_calls = []


# Install a fake hailo_inference module BEFORE importing the wrappers so they
# bind to FakeHailoInfer instead of the real (device-dependent) engine.
_fake_mod = types.ModuleType("hailo_apps.python.core.common.hailo_inference")
_fake_mod.HailoInfer = FakeHailoInfer
sys.modules["hailo_apps.python.core.common.hailo_inference"] = _fake_mod

from community.apps.pipeline_apps.gesture_detection import blaze_base  # noqa: E402
from community.apps.pipeline_apps.gesture_detection.blaze_palm_detector import (  # noqa: E402
    BlazePalmDetector,
)
from community.apps.pipeline_apps.gesture_detection.blaze_hand_landmark import (  # noqa: E402
    BlazeHandLandmark,
)


# --------------------------------------------------------------------------- #
# Palm-detection output shapes (192x192, 2016 anchors)
# --------------------------------------------------------------------------- #
def _palm_outputs(score_logit=-20.0):
    # Score tensors hold pre-sigmoid logits; a large negative value drives every
    # anchor below the detection threshold so the decode yields no detections.
    return {
        "conv29": np.full((24, 24, 2), score_logit, dtype=np.float32),   # scores large (1152)
        "conv24": np.full((12, 12, 6), score_logit, dtype=np.float32),   # scores small (864)
        "conv30": np.zeros((24, 24, 36), dtype=np.float32),  # boxes large  (1152*18)
        "conv25": np.zeros((12, 12, 108), dtype=np.float32),  # boxes small (864*18)
    }


def _hand_outputs(flag=0.9, handedness=0.7):
    return {
        "model/fc1": np.zeros((63,), dtype=np.float32),
        "model/fc2": np.zeros((63,), dtype=np.float32),
        "model/fc3": np.full((1,), handedness, dtype=np.float32),
        "model/fc4": np.full((1,), flag, dtype=np.float32),
    }


# --------------------------------------------------------------------------- #
# BlazePalmDetector
# --------------------------------------------------------------------------- #
class TestBlazePalmDetector:
    def test_constructs_hailoinfer_with_uint8_in_float32_out(self):
        FakeHailoInfer.reset(_palm_outputs())
        BlazePalmDetector("palm.hef")
        inst = FakeHailoInfer.instances[0]
        assert inst.hef_path == "palm.hef"
        assert inst.batch_size == 1
        assert inst.input_type == "UINT8"
        assert inst.output_type == "FLOAT32"

    def test_maps_scores_and_boxes_by_total_size(self):
        FakeHailoInfer.reset(_palm_outputs())
        pd = BlazePalmDetector("palm.hef")
        score_names = {n for n, _ in pd._score_tensors}
        box_names = {n for n, _ in pd._box_tensors}
        assert score_names == {"conv29", "conv24"}
        assert box_names == {"conv30", "conv25"}
        # Larger feature map (24x24) sorted first in each group
        assert pd._score_tensors[0][0] == "conv29"
        assert pd._box_tensors[0][0] == "conv30"

    def test_detect_runs_single_frame_and_returns_list(self):
        FakeHailoInfer.reset(_palm_outputs())
        pd = BlazePalmDetector("palm.hef")
        dets = pd.detect(np.zeros((192, 192, 3), dtype=np.uint8))
        # Zero scores → no detections survive thresholding.
        assert isinstance(dets, list)
        assert len(dets) == 0
        # Exactly one async job per detect() call, one frame in the batch.
        assert len(FakeHailoInfer.run_calls) == 1
        assert len(FakeHailoInfer.run_calls[0]) == 1

    def test_detect_casts_non_uint8_input(self):
        FakeHailoInfer.reset(_palm_outputs())
        pd = BlazePalmDetector("palm.hef")
        pd.detect(np.zeros((192, 192, 3), dtype=np.float32))
        assert FakeHailoInfer.run_calls[0][0].dtype == np.uint8

    def test_inference_exception_raises_runtimeerror(self):
        FakeHailoInfer.reset(_palm_outputs(), raise_exception=ValueError("boom"))
        pd = BlazePalmDetector("palm.hef")
        with pytest.raises(RuntimeError, match="Palm detection inference failed"):
            pd.detect(np.zeros((192, 192, 3), dtype=np.uint8))

    def test_close_releases_engine(self):
        FakeHailoInfer.reset(_palm_outputs())
        pd = BlazePalmDetector("palm.hef")
        pd.close()
        assert FakeHailoInfer.instances[0].closed is True


# --------------------------------------------------------------------------- #
# BlazeHandLandmark
# --------------------------------------------------------------------------- #
class TestBlazeHandLandmark:
    def test_maps_output_tensors_by_suffix(self):
        FakeHailoInfer.reset(_hand_outputs(), input_shape=(224, 224, 3))
        hl = BlazeHandLandmark("hand.hef")
        assert hl._tensor_map["landmarks"].endswith("fc1")
        assert hl._tensor_map["world_landmarks"].endswith("fc2")
        assert hl._tensor_map["handedness"].endswith("fc3")
        assert hl._tensor_map["confidence"].endswith("fc4")

    def test_predict_empty_returns_zero_arrays(self):
        FakeHailoInfer.reset(_hand_outputs(), input_shape=(224, 224, 3))
        hl = BlazeHandLandmark("hand.hef")
        flags, lms, handed = hl.predict(np.zeros((0, 224, 224, 3), dtype=np.float32))
        assert flags.shape == (0, 1)
        assert lms.shape == (0, 21, 3)
        assert handed.shape == (0, 1)
        # No inference launched for an empty batch.
        assert FakeHailoInfer.run_calls == []

    def test_predict_loops_once_per_crop(self):
        FakeHailoInfer.reset(_hand_outputs(), input_shape=(224, 224, 3))
        hl = BlazeHandLandmark("hand.hef")
        flags, lms, handed = hl.predict(np.zeros((3, 224, 224, 3), dtype=np.float32))
        assert flags.shape == (3, 1)
        assert lms.shape == (3, 21, 3)
        assert handed.shape == (3, 1)
        # One async run per crop, each a single-frame batch of uint8.
        assert len(FakeHailoInfer.run_calls) == 3
        assert FakeHailoInfer.run_calls[0][0].dtype == np.uint8

    def test_predict_normalizes_landmarks_by_resolution(self):
        outs = _hand_outputs()
        outs["model/fc1"] = np.full((63,), float(blaze_base.HAND_LANDMARK_RESOLUTION),
                                    dtype=np.float32)
        FakeHailoInfer.reset(outs, input_shape=(224, 224, 3))
        hl = BlazeHandLandmark("hand.hef")
        _, lms, _ = hl.predict(np.zeros((1, 224, 224, 3), dtype=np.float32))
        # fc1 == resolution → normalized landmarks == 1.0
        assert np.allclose(lms, 1.0)

    def test_predict_propagates_flag_and_handedness(self):
        FakeHailoInfer.reset(_hand_outputs(flag=0.42, handedness=0.66),
                             input_shape=(224, 224, 3))
        hl = BlazeHandLandmark("hand.hef")
        flags, _, handed = hl.predict(np.zeros((1, 224, 224, 3), dtype=np.float32))
        assert flags[0, 0] == pytest.approx(0.42)
        assert handed[0, 0] == pytest.approx(0.66)

    def test_inference_exception_raises_runtimeerror(self):
        FakeHailoInfer.reset(_hand_outputs(), input_shape=(224, 224, 3),
                             raise_exception=RuntimeError("device gone"))
        hl = BlazeHandLandmark("hand.hef")
        with pytest.raises(RuntimeError, match="Hand landmark inference failed"):
            hl.predict(np.zeros((1, 224, 224, 3), dtype=np.float32))
