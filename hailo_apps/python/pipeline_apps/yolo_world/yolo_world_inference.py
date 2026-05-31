"""HailoRT inference wrapper for the YOLO World v2s dual-input HEF.

`hailonet` does not support dual-input HEFs, so we drive HailoRT directly
from a Python user-callback. The HEF takes a 640x640x3 image plus a
(1, 80, 512) tensor of L2-normalized CLIP text embeddings. Output shape
depends on the build:
  * Hailo-10H HEF emits 6 raw tensors (3 cls maps + 3 reg maps at
    strides 8/16/32) — postprocess does DFL+NMS in Python.
  * Hailo-8 HEF emits a single ``yolov8_nms_postprocess`` tensor of
    decoded boxes — postprocess just score-filters.
Postprocess dispatches by output count; the wrapper itself is agnostic.

Hot-path notes:
- Bindings are created once at configure time and reused per frame.
- Input/output buffers are pre-allocated; the image is copied into the
  pre-allocated input slot instead of allocating a fresh buffer each frame.
- Outputs are returned as views into the pre-allocated buffers — callers
  must consume them synchronously before the next call to `run()` (the
  GStreamer callback always does).
"""
import numpy as np
import hailo_platform
from hailo_platform import HEF, FormatOrder, FormatType, VDevice

# HailoRT 4.x default BY_CLASS readout for the on-device NMS HEFs silently
# drops detections from non-zero class slots → we override to BY_SCORE there.
# HailoRT 5.x reads BY_CLASS correctly (multi-class output verified) and the
# BY_SCORE override raises HAILO_INVALID_ARGUMENT on configure() for these
# HEFs, so we leave the default.
_HRT_MAJOR = int(hailo_platform.__version__.split(".")[0])

from hailo_apps.python.core.common.defines import SHARED_VDEVICE_GROUP_ID
from hailo_apps.python.core.common.hailo_logger import get_logger

logger = get_logger(__name__)


class YoloWorldInference:
    """Runs YOLO World v2s inference on Hailo using the dual-input HEF."""

    def __init__(self, hef_path, text_embeddings):
        """Initialize inference engine.

        Args:
            hef_path: path to yolo_world_v2s HEF.
            text_embeddings: numpy array (1, 80, 512) float32, L2-normalized.
        """
        self._hef_path = str(hef_path)
        self._text_embeddings = np.ascontiguousarray(text_embeddings, dtype=np.float32)

        hef = HEF(self._hef_path)
        self._network_name = hef.get_network_group_names()[0]
        input_infos = hef.get_input_vstream_infos()
        output_infos = hef.get_output_vstream_infos()

        logger.info("HEF network: %s", self._network_name)
        logger.info("Inputs: %s", [(info.name, info.shape) for info in input_infos])
        logger.info("Outputs: %s", [(info.name, info.shape) for info in output_infos])

        # Identify the image vs text input by trailing dimension.
        self._image_input_name = None
        self._text_input_name = None
        for info in input_infos:
            shape = tuple(info.shape)
            if shape[-1] == 3:
                self._image_input_name = info.name
            elif shape[-1] == 512:
                self._text_input_name = info.name
        if not self._image_input_name or not self._text_input_name:
            raise ValueError(
                f"Could not identify input layers. Found: "
                f"{[(info.name, info.shape) for info in input_infos]}"
            )
        logger.info("Image input: %s", self._image_input_name)
        logger.info("Text input: %s", self._text_input_name)

        self._output_names = [info.name for info in output_infos]
        # On-device NMS HEFs (Hailo-8) emit a single output. We deliberately
        # read it as HAILO_NMS_BY_SCORE: the BY_CLASS layout silently dropped
        # everything but class 0 in HailoRT 4.23 with this HEF, even when the
        # model produced multi-class detections. BY_SCORE returns a packed
        # record stream (`uint16 n_dets` header + N × 22-byte rows of
        # `[y1, x1, y2, x2, score, class_id]`) where class_id is explicit
        # per detection — no silent suppression.
        self._nms_by_score = (
            len(output_infos) == 1
            and getattr(output_infos[0].format, "order", None) in (
                FormatOrder.HAILO_NMS_BY_CLASS,
                FormatOrder.HAILO_NMS_BY_SCORE,
            )
        )

        params = VDevice.create_params()
        params.group_id = SHARED_VDEVICE_GROUP_ID
        self._vdevice = VDevice(params)
        self._infer_model = self._vdevice.create_infer_model(self._hef_path)

        self._infer_model.input(self._image_input_name).set_format_type(FormatType.UINT8)
        self._infer_model.input(self._text_input_name).set_format_type(FormatType.FLOAT32)
        self._using_by_score = self._nms_by_score and _HRT_MAJOR < 5
        if self._using_by_score:
            self._infer_model.output(self._output_names[0]).set_format_order(
                FormatOrder.HAILO_NMS_BY_SCORE,
            )
            logger.info("Output format: HAILO_NMS_BY_SCORE (HailoRT 4.x path)")
        elif self._nms_by_score:
            self._infer_model.output(self._output_names[0]).set_format_type(FormatType.FLOAT32)
            logger.info("Output format: HAILO_NMS_BY_CLASS flat float32 (HailoRT 5.x path)")
        else:
            for name in self._output_names:
                self._infer_model.output(name).set_format_type(FormatType.FLOAT32)

        self._config_ctx = self._infer_model.configure()
        self._configured_model = self._config_ctx.__enter__()
        # HailoRT 4.x InferModel needs explicit stream activation; 5.x activates
        # implicitly on context entry and rejects a redundant activate() call as
        # an "Invalid operation". Gate on the runtime major version.
        if _HRT_MAJOR < 5 and hasattr(self._configured_model, "activate"):
            self._configured_model.activate()

        # Pre-allocate input/output buffers (hot path mustn't allocate).
        image_input_shape = self._infer_model.input(self._image_input_name).shape
        self._image_input_buffer = np.empty(image_input_shape, dtype=np.uint8)
        # Sanity check: should be (1, 640, 640, 3) or (640, 640, 3) — handled below.
        logger.info("Image input buffer shape: %s", self._image_input_buffer.shape)

        # Buffer dtype tracks the selected output format:
        #   * BY_SCORE (HailoRT 4.x path): uint8 byte stream
        #   * BY_CLASS flat / raw heads (5.x path or non-NMS HEFs): float32
        self._output_buffers = {}
        for name in self._output_names:
            shape = self._infer_model.output(name).shape
            if self._using_by_score:
                self._output_buffers[name] = np.empty(shape, dtype=np.uint8)
            else:
                self._output_buffers[name] = np.empty(shape, dtype=np.float32)

        # Create bindings once; HailoRT lets us reuse them across runs as long
        # as the buffer references stay valid.
        self._bindings = self._configured_model.create_bindings()
        self._bindings.input(self._image_input_name).set_buffer(self._image_input_buffer)
        self._bindings.input(self._text_input_name).set_buffer(self._text_embeddings)
        for name, buf in self._output_buffers.items():
            self._bindings.output(name).set_buffer(buf)

        logger.info("YOLO World inference engine initialized")

    def run(self, image):
        """Run inference on a single image frame.

        Args:
            image: numpy array (640, 640, 3) uint8 RGB.

        Returns:
            dict mapping output layer name to the corresponding pre-allocated
            output buffer (caller must consume before the next call).
        """
        # Copy frame into the pre-allocated input slot. np.copyto handles the
        # batch-dim mismatch via broadcasting where shapes are (1,H,W,3) vs (H,W,3).
        if self._image_input_buffer.shape[0] == 1 and image.ndim == 3:
            self._image_input_buffer[0] = image
        else:
            np.copyto(self._image_input_buffer, image)

        self._configured_model.run([self._bindings], timeout=10000)
        return self._output_buffers

    def update_text_embeddings(self, text_embeddings):
        """Swap the text embeddings tensor (zero-shot class change).

        Rebinds the text input to point at the new (1, 80, 512) array. Safe to
        call between frames from any thread (the file watcher uses this).
        """
        self._text_embeddings = np.ascontiguousarray(text_embeddings, dtype=np.float32)
        self._bindings.input(self._text_input_name).set_buffer(self._text_embeddings)
        logger.info("Text embeddings updated")

    def close(self):
        """Release HailoRT resources."""
        if self._config_ctx:
            if self._configured_model is not None and hasattr(
                self._configured_model, "deactivate",
            ):
                try:
                    self._configured_model.deactivate()
                except Exception:
                    pass
            self._config_ctx.__exit__(None, None, None)
            self._config_ctx = None
        logger.info("Inference engine closed")
