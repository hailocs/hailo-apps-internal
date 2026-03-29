import numpy as np
from hailo_platform import HEF, VDevice, FormatType, HailoSchedulingAlgorithm

from hailo_apps.python.core.common.defines import SHARED_VDEVICE_GROUP_ID
from hailo_apps.python.core.common.hailo_logger import get_logger

logger = get_logger(__name__)


class YoloWorldInference:
    """Runs YOLO World v2s inference on Hailo using the dual-input HEF.

    The HEF has two inputs:
      - input_layer1: image (1, 640, 640, 3) uint8
      - input_layer2: text embeddings (1, 80, 512) float32

    And 6 outputs:
      - 3 classification maps (HxWx80) at strides 8, 16, 32
      - 3 regression maps (HxWx4) at strides 8, 16, 32
    """

    def __init__(self, hef_path, text_embeddings):
        """Initialize inference engine.

        Args:
            hef_path: path to yolo_world_v2s.hef
            text_embeddings: numpy array (1, 80, 512) float32, L2-normalized
        """
        self._hef_path = hef_path
        self._text_embeddings = np.ascontiguousarray(text_embeddings, dtype=np.float32)

        # Introspect HEF to get layer names
        hef = HEF(hef_path)
        self._network_name = hef.get_network_group_names()[0]
        input_infos = hef.get_input_vstream_infos()
        output_infos = hef.get_output_vstream_infos()

        logger.info("HEF network: %s", self._network_name)
        logger.info("Inputs: %s", [(info.name, info.shape) for info in input_infos])
        logger.info("Outputs: %s", [(info.name, info.shape) for info in output_infos])

        # Identify input layers by shape
        self._image_input_name = None
        self._text_input_name = None
        for info in input_infos:
            shape = tuple(info.shape)
            if len(shape) == 4 and shape[-1] == 3:
                self._image_input_name = info.name
            elif len(shape) == 3 and shape[-1] == 512:
                self._text_input_name = info.name

        if not self._image_input_name or not self._text_input_name:
            raise ValueError(
                f"Could not identify input layers. Found: "
                f"{[(info.name, info.shape) for info in input_infos]}"
            )

        logger.info("Image input: %s", self._image_input_name)
        logger.info("Text input: %s", self._text_input_name)

        # Store output names and shapes
        self._output_names = [info.name for info in output_infos]
        self._output_shapes = {info.name: tuple(info.shape) for info in output_infos}

        # Create VDevice and configure model
        params = VDevice.create_params()
        params.group_id = SHARED_VDEVICE_GROUP_ID
        self._vdevice = VDevice(params)

        self._infer_model = self._vdevice.create_infer_model(hef_path)

        # Set format types for inputs
        self._infer_model.input(self._image_input_name).set_format_type(FormatType.UINT8)
        self._infer_model.input(self._text_input_name).set_format_type(FormatType.FLOAT32)

        # Set format type for all outputs to float32
        for name in self._output_names:
            self._infer_model.output(name).set_format_type(FormatType.FLOAT32)

        # Configure (enter context)
        self._config_ctx = self._infer_model.configure()
        self._configured_model = self._config_ctx.__enter__()

        # Pre-allocate output buffers
        self._output_buffers = {
            name: np.empty(self._infer_model.output(name).shape, dtype=np.float32)
            for name in self._output_names
        }

        logger.info("YOLO World inference engine initialized")

    def run(self, image):
        """Run inference on a single image frame.

        Args:
            image: numpy array (640, 640, 3) uint8 RGB

        Returns:
            dict mapping output layer name to numpy array
        """
        bindings = self._configured_model.create_bindings()

        # Set image input
        image_input = np.ascontiguousarray(image, dtype=np.uint8)
        if len(image_input.shape) == 3:
            image_input = np.expand_dims(image_input, axis=0)
        bindings.input(self._image_input_name).set_buffer(image_input)

        # Set text embeddings input
        bindings.input(self._text_input_name).set_buffer(self._text_embeddings)

        # Set output buffers
        for name, buf in self._output_buffers.items():
            bindings.output(name).set_buffer(buf)

        # Run synchronous inference
        self._configured_model.run([bindings], timeout_ms=10000)

        # Collect outputs
        outputs = {}
        for name in self._output_names:
            outputs[name] = bindings.output(name).get_buffer().copy()

        return outputs

    def update_text_embeddings(self, text_embeddings):
        """Update the text embeddings tensor for zero-shot class changes.

        Args:
            text_embeddings: numpy array (1, 80, 512) float32, L2-normalized
        """
        self._text_embeddings = np.ascontiguousarray(text_embeddings, dtype=np.float32)
        logger.info("Text embeddings updated")

    def close(self):
        """Release HailoRT resources."""
        if self._config_ctx:
            self._config_ctx.__exit__(None, None, None)
        logger.info("Inference engine closed")
