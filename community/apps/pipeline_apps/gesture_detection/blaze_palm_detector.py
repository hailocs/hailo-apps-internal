"""
Palm detection using MediaPipe palm_detection_lite HEF model.

Loads the model via the cross-platform HailoInfer engine (async
create_infer_model / run_async API with a shared ROUND_ROBIN scheduler) and
runs inference. This works on Hailo-8, Hailo-8L and Hailo-10H — unlike the
legacy synchronous InferVStreams API, which is Hailo-8/8L only
(VDevice.configure raises HAILO_NOT_IMPLEMENTED on Hailo-10H).

Output tensors are reshaped and concatenated into the format expected by
the blaze decoding pipeline (2016 anchors for 192x192 input).

Based on AlbertaBeef/blaze_app_python (https://github.com/AlbertaBeef/blaze_app_python).
"""

import numpy as np

from hailo_apps.python.core.common.hailo_inference import HailoInfer

from . import blaze_base


class BlazePalmDetector:
    """Palm detection wrapper for palm_detection_lite.hef (H8/8L/10H)."""

    def __init__(self, hef_path):
        """Initialize palm detector.

        Args:
            hef_path: Path to palm_detection_lite.hef.

        HailoInfer manages its own VDevice in the shared scheduler group
        ("SHARED"), so the palm and hand models automatically share the
        physical device.
        """
        self.config = blaze_base.PALM_MODEL_CONFIG
        self.anchors = blaze_base.generate_anchors(blaze_base.PALM_ANCHOR_OPTIONS)

        # UINT8 image input, FLOAT32 outputs (decoded by the blaze pipeline).
        self.hailo_infer = HailoInfer(
            hef_path, batch_size=1, input_type="UINT8", output_type="FLOAT32")

        input_infos, self.output_vstream_infos = self.hailo_infer.get_vstream_info()
        self.input_vstream_info = input_infos[0]

        # Sort outputs by name for deterministic mapping
        self._map_output_tensors()

    def _map_output_tensors(self):
        """Map output tensors to scores and boxes by shape.

        Palm detection lite outputs (192x192, 2016 anchors):
          - conv29: (24, 24, 2)  -> scores large  (1152 anchors)
          - conv24: (12, 12, 6)  -> scores small   (864 anchors)
          - conv30: (24, 24, 36) -> boxes large    (1152 * 18)
          - conv25: (12, 12, 108)-> boxes small     (864 * 18)

        Order: large (24x24) first, then small (12x12) to match anchor generation.
        """
        infos = self.output_vstream_infos

        # Classify by total size: scores have fewer elements than boxes
        score_tensors = []
        box_tensors = []
        for info in infos:
            shape = info.shape
            total = 1
            for s in shape:
                total *= s
            # 18 coords per anchor for boxes; 1 score per anchor
            # boxes total / 18 == scores total / 1
            if total < 2016:  # score tensors
                score_tensors.append((info, shape, total))
            else:
                box_tensors.append((info, shape, total))

        # Sort each group: larger total first (24x24 before 12x12)
        score_tensors.sort(key=lambda x: -x[2])
        box_tensors.sort(key=lambda x: -x[2])

        self._score_tensors = [(t[0].name, t[2]) for t in score_tensors]
        self._box_tensors = [(t[0].name, t[2]) for t in box_tensors]

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
            raise RuntimeError(f"Palm detection inference failed: {holder['error']}")
        return holder["outputs"]

    def detect(self, img):
        """Run palm detection on a preprocessed image.

        Args:
            img: np.ndarray (H, W, 3) uint8, already resized+padded to 192x192.

        Returns:
            List of detections, each (num_coords+1,) with [ymin, xmin, ymax, xmax, kps..., score].
            Coordinates are normalized [0,1] relative to model input.
        """
        # Ensure uint8
        if img.dtype != np.uint8:
            img = np.clip(img, 0, 255).astype(np.uint8)

        infer_results = self._infer(img)
        return self._postprocess(infer_results)

    def _postprocess(self, infer_results):
        """Reshape and decode raw inference output.

        Concatenates large+small feature map outputs into unified tensors,
        then runs anchor decoding + NMS.
        """
        # Assemble scores: (1, 2016, 1)
        score_parts = []
        for name, total in self._score_tensors:
            data = infer_results[name].reshape(1, total, 1)
            score_parts.append(data)
        scores = np.concatenate(score_parts, axis=1)

        # Assemble boxes: (1, 2016, 18)
        box_parts = []
        for name, total in self._box_tensors:
            n_anchors = total // self.config["num_coords"]
            data = infer_results[name].reshape(1, n_anchors, self.config["num_coords"])
            box_parts.append(data)
        boxes = np.concatenate(box_parts, axis=1)

        # Decode
        detections_batch = blaze_base.tensors_to_detections(
            boxes, scores, self.anchors, self.config)

        # NMS per image
        results = []
        for dets in detections_batch:
            nms_dets = blaze_base.weighted_non_max_suppression(
                dets, self.config["min_suppression_threshold"])
            results.extend(nms_dets)

        return results

    def predict_on_image(self, img):
        """Convenience: resize_pad + detect. For use with raw camera frames.

        Args:
            img: Original image (H, W, 3) uint8 BGR.

        Returns:
            (detections, scale, pad) where detections are in normalized coords.
        """
        target_h = int(self.config["y_scale"])
        target_w = int(self.config["x_scale"])
        padded, scale, pad = blaze_base.resize_pad(img, (target_h, target_w))
        detections = self.detect(padded)
        return detections, scale, pad

    def close(self):
        """Release the underlying Hailo inference resources."""
        self.hailo_infer.close()
