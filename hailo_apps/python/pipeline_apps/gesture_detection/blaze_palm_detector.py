"""
Palm detection using MediaPipe palm_detection_lite HEF model on Hailo-8.

Loads the model via a shared VDevice and runs inference with InferVStreams.
Output tensors are reshaped and concatenated into the format expected by
the blaze decoding pipeline (2016 anchors for 192x192 input).

Based on AlbertaBeef/blaze_app_python (https://github.com/AlbertaBeef/blaze_app_python).
"""

import numpy as np
from hailo_platform import (HEF, VDevice, HailoStreamInterface,
                            InferVStreams, ConfigureParams,
                            InputVStreamParams, OutputVStreamParams,
                            FormatType)

from hailo_apps.python.pipeline_apps.gesture_detection import blaze_base


class BlazePalmDetector:
    """Palm detection wrapper for palm_detection_lite.hef on Hailo-8."""

    def __init__(self, hef_path, vdevice=None):
        """Initialize palm detector.

        Args:
            hef_path: Path to palm_detection_lite.hef.
            vdevice: Optional shared VDevice. Created if not provided.
        """
        self.config = blaze_base.PALM_MODEL_CONFIG
        self.anchors = blaze_base.generate_anchors(blaze_base.PALM_ANCHOR_OPTIONS)

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

        input_data = {self.input_vstream_info.name: np.expand_dims(img, axis=0)}

        with self.network_group.activate(self.network_group_params):
            with InferVStreams(self.network_group, self.input_vstreams_params,
                              self.output_vstreams_params) as pipeline:
                infer_results = pipeline.infer(input_data)

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
