"""
Hand landmark detection using MediaPipe hand_landmark_lite HEF model on Hailo-8.

Loads the model via a shared VDevice and runs inference with InferVStreams.
Maps 4 output tensors: fc1→landmarks(21x3), fc4→confidence, fc3→handedness.

Based on AlbertaBeef/blaze_app_python (https://github.com/AlbertaBeef/blaze_app_python).
"""

import numpy as np
from hailo_platform import (HEF, VDevice, HailoStreamInterface,
                            InferVStreams, ConfigureParams,
                            InputVStreamParams, OutputVStreamParams,
                            FormatType)

from . import blaze_base


class BlazeHandLandmark:
    """Hand landmark wrapper for hand_landmark_lite.hef on Hailo-8."""

    def __init__(self, hef_path, vdevice=None):
        """Initialize hand landmark model.

        Args:
            hef_path: Path to hand_landmark_lite.hef.
            vdevice: Optional shared VDevice. Created if not provided.
        """
        self.resolution = blaze_base.HAND_LANDMARK_RESOLUTION

        self.hef = HEF(hef_path)
        self._owns_vdevice = vdevice is None
        self.vdevice = vdevice or VDevice()

        self.network_group = self.vdevice.configure(self.hef)[0]
        self.network_group_params = self.network_group.create_params()

        self.input_vstreams_params = InputVStreamParams.make(
            self.network_group, format_type=FormatType.UINT8)
        self.output_vstreams_params = OutputVStreamParams.make(
            self.network_group, format_type=FormatType.FLOAT32)

        self.input_vstream_info = self.hef.get_input_vstream_infos()[0]
        self.output_vstream_infos = self.hef.get_output_vstream_infos()

        self._map_output_tensors()

    def _map_output_tensors(self):
        """Map output tensors by name suffix.

        hand_landmark_lite outputs:
          fc1: (63,) -> screen landmarks (21 * 3 = 63)
          fc4: (1,)  -> hand presence confidence
          fc3: (1,)  -> handedness (left/right)
          fc2: (63,) -> world landmarks (unused)
        """
        self._tensor_map = {}
        for info in self.output_vstream_infos:
            name = info.name
            if name.endswith("fc1"):
                self._tensor_map["landmarks"] = name
            elif name.endswith("fc4"):
                self._tensor_map["confidence"] = name
            elif name.endswith("fc3"):
                self._tensor_map["handedness"] = name
            elif name.endswith("fc2"):
                self._tensor_map["world_landmarks"] = name

    def predict(self, imgs):
        """Run hand landmark inference on batch of cropped hand images.

        Args:
            imgs: np.ndarray (N, 224, 224, 3) float32 in [0, 1].

        Returns:
            (flags, landmarks, handedness) where:
            - flags: np.ndarray (N, 1) hand presence confidence (sigmoid).
            - landmarks: np.ndarray (N, 21, 3) normalized to [0, 1].
            - handedness: np.ndarray (N, 1) left/right score.
        """
        n = imgs.shape[0]
        if n == 0:
            return (np.zeros((0, 1), dtype=np.float32),
                    np.zeros((0, 21, 3), dtype=np.float32),
                    np.zeros((0, 1), dtype=np.float32))

        all_flags = []
        all_landmarks = []
        all_handedness = []

        for i in range(n):
            # Convert [0,1] float to uint8 for Hailo
            img_uint8 = np.clip(imgs[i] * 255.0, 0, 255).astype(np.uint8)
            input_data = {self.input_vstream_info.name: np.expand_dims(img_uint8, axis=0)}

            with self.network_group.activate(self.network_group_params):
                with InferVStreams(self.network_group, self.input_vstreams_params,
                                   self.output_vstreams_params) as pipeline:
                    results = pipeline.infer(input_data)

            # Extract tensors
            flag = results[self._tensor_map["confidence"]].flatten()
            landmarks = results[self._tensor_map["landmarks"]].reshape(1, 21, 3)
            landmarks = landmarks / float(self.resolution)  # normalize to [0,1]
            handedness = results[self._tensor_map["handedness"]].flatten()

            all_flags.append(flag)
            all_landmarks.append(landmarks[0])
            all_handedness.append(handedness)

        flags = np.array(all_flags, dtype=np.float32)
        landmarks = np.array(all_landmarks, dtype=np.float32)
        handedness = np.array(all_handedness, dtype=np.float32)

        return flags, landmarks, handedness
