"""
Hand landmark detection using MediaPipe hand_landmark_lite HEF model.

Loads the model via the cross-platform HailoInfer engine (async
create_infer_model / run_async API with a shared ROUND_ROBIN scheduler) and
runs inference. This works on Hailo-8, Hailo-8L and Hailo-10H — unlike the
legacy synchronous InferVStreams API, which is Hailo-8/8L only
(VDevice.configure raises HAILO_NOT_IMPLEMENTED on Hailo-10H).

Maps 4 output tensors: fc1→landmarks(21x3), fc4→confidence, fc3→handedness.

Based on AlbertaBeef/blaze_app_python (https://github.com/AlbertaBeef/blaze_app_python).
"""

import numpy as np

from hailo_apps.python.core.common.hailo_inference import HailoInfer

from . import blaze_base


class BlazeHandLandmark:
    """Hand landmark wrapper for hand_landmark_lite.hef (H8/8L/10H)."""

    def __init__(self, hef_path, vdevice=None):
        """Initialize hand landmark model.

        Args:
            hef_path: Path to hand_landmark_lite.hef.
            vdevice: Deprecated/ignored. Kept for backwards compatibility.
                HailoInfer manages its own VDevice in the shared scheduler
                group ("SHARED"), so the palm and hand models automatically
                share the physical device.
        """
        self.resolution = blaze_base.HAND_LANDMARK_RESOLUTION

        # UINT8 image input, FLOAT32 outputs.
        self.hailo_infer = HailoInfer(
            hef_path, batch_size=1, input_type="UINT8", output_type="FLOAT32")

        input_infos, self.output_vstream_infos = self.hailo_infer.get_vstream_info()
        self.input_vstream_info = input_infos[0]

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

    def _infer(self, frame):
        """Run a single async inference and block for the result.

        Args:
            frame: np.ndarray (H, W, 3) uint8 model input.

        Returns:
            dict mapping output layer name -> output buffer (np.ndarray).
        """
        holder = {}

        def _callback(completion_info, bindings_list):
            if completion_info.exception:
                holder["error"] = completion_info.exception
                return
            bindings = bindings_list[0]
            holder["outputs"] = {
                name: bindings.output(name).get_buffer()
                for name in bindings._output_names
            }

        job = self.hailo_infer.run([frame], _callback)
        job.wait(10000)
        if "error" in holder:
            raise RuntimeError(f"Hand landmark inference failed: {holder['error']}")
        return holder["outputs"]

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
            results = self._infer(img_uint8)

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

    def close(self):
        """Release the underlying Hailo inference resources."""
        self.hailo_infer.close()
