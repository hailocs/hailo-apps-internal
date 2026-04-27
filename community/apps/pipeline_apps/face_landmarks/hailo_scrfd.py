"""SCRFD face detector running on Hailo via HailoRT InferVStreams.

Minimal Python port of the SCRFD postprocess (scrfd.cpp), using insightface's
decode pattern which is simpler than the xtensor-based C++ implementation.

Outputs per detected face:
    bbox (xmin, ymin, xmax, ymax) in original image pixels
    5 keypoints (right_eye, left_eye, nose, right_mouth, left_mouth) in original image pixels
    confidence score

References:
    insightface SCRFD: https://github.com/deepinsight/insightface/blob/master/detection/scrfd/tools/scrfd.py
    Hailo scrfd.cpp: hailo_apps/postprocess/cpp/scrfd.cpp
"""

from __future__ import annotations

import os

import cv2
import numpy as np
from hailo_platform import (
    HEF,
    VDevice,
    InferVStreams,
    InputVStreamParams,
    OutputVStreamParams,
    FormatType,
)

from hailo_apps.python.core.common.defines import SHARED_VDEVICE_GROUP_ID


class HailoScrfd:
    """SCRFD face detector on Hailo.

    The 10G variant uses 3 FPN levels at strides 8/16/32 with 2 anchors per
    spatial location. Input is 640x640 RGB uint8.

    Args:
        hef_path: Path to scrfd_10g.hef.
        score_threshold: Minimum face score (after sigmoid).
        iou_threshold: NMS IoU threshold.
    """

    INPUT_SIZE = 640
    FEAT_STRIDES = [8, 16, 32]
    NUM_ANCHORS = 2
    # Output tensor suffixes — model produces 3 groups (scores, boxes, kps) × 3 scales.
    # We detect them by tensor shape/size rather than name to stay robust.

    def __init__(
        self,
        hef_path: str,
        score_threshold: float = 0.4,
        iou_threshold: float = 0.4,
    ) -> None:
        self.score_threshold = score_threshold
        self.iou_threshold = iou_threshold

        self.hef = HEF(hef_path)
        params = VDevice.create_params()
        params.group_id = SHARED_VDEVICE_GROUP_ID
        self.vdevice = VDevice(params)

        self.network_group = self.vdevice.configure(self.hef)[0]
        self.network_group_params = self.network_group.create_params()

        self.input_vstreams_params = InputVStreamParams.make(
            self.network_group, format_type=FormatType.UINT8,
        )
        self.output_vstreams_params = OutputVStreamParams.make(
            self.network_group, format_type=FormatType.FLOAT32,
        )

        self.input_name = self.hef.get_input_vstream_infos()[0].name
        self.output_infos = self.hef.get_output_vstream_infos()

        # Map outputs: group by last-dim channel count (2=scores, 8=boxes, 20=kps)
        # and by spatial size (stride 8/16/32 => 80/40/20).
        self._output_names_by_stride = {}
        for info in self.output_infos:
            h, w, c = info.shape  # (H, W, C)
            if h not in (80, 40, 20):
                continue
            stride = self.INPUT_SIZE // h
            slot = self._output_names_by_stride.setdefault(
                stride, {"scores": None, "bboxes": None, "kpss": None},
            )
            if c == 2:
                slot["scores"] = info.name
            elif c == 8:
                slot["bboxes"] = info.name
            elif c == 20:
                slot["kpss"] = info.name

        # Precompute anchor centers for each stride
        self._center_cache = {}
        for stride in self.FEAT_STRIDES:
            h = w = self.INPUT_SIZE // stride
            # (H, W, 2) grid with (x, y) pixel coordinates at each cell
            ys, xs = np.mgrid[:h, :w]
            centers = np.stack([xs, ys], axis=-1).astype(np.float32)  # (H, W, 2) — (x, y)
            centers = (centers * stride).reshape(-1, 2)               # (H*W, 2)
            # Replicate for each anchor at the same location
            centers = np.stack([centers] * self.NUM_ANCHORS, axis=1).reshape(-1, 2)
            self._center_cache[stride] = centers

    # ------------------------------------------------------------------
    # Preprocess — letterbox to 640x640 preserving aspect ratio
    # ------------------------------------------------------------------

    def _preprocess(self, image_rgb: np.ndarray):
        """Resize + letterbox pad to 640x640. Returns (padded, scale, pad_x, pad_y)."""
        h, w = image_rgb.shape[:2]
        scale = self.INPUT_SIZE / max(h, w)
        new_w = int(round(w * scale))
        new_h = int(round(h * scale))
        resized = cv2.resize(image_rgb, (new_w, new_h))
        padded = np.zeros((self.INPUT_SIZE, self.INPUT_SIZE, 3), dtype=np.uint8)
        # Top-left placement (same as the C++ letterbox convention)
        padded[:new_h, :new_w] = resized
        return padded, scale, 0, 0

    # ------------------------------------------------------------------
    # Box / keypoint decoding (matches insightface)
    # ------------------------------------------------------------------

    @staticmethod
    def _distance2bbox(centers: np.ndarray, distance: np.ndarray) -> np.ndarray:
        """Convert center + (dl, dt, dr, db) offsets to (x1, y1, x2, y2)."""
        x1 = centers[:, 0] - distance[:, 0]
        y1 = centers[:, 1] - distance[:, 1]
        x2 = centers[:, 0] + distance[:, 2]
        y2 = centers[:, 1] + distance[:, 3]
        return np.stack([x1, y1, x2, y2], axis=-1)

    @staticmethod
    def _distance2kps(centers: np.ndarray, distance: np.ndarray) -> np.ndarray:
        """Convert center + (dx0, dy0, ..., dx4, dy4) to 5 (x, y) keypoints per anchor."""
        # distance shape (N, 10), output (N, 5, 2)
        out = np.empty((distance.shape[0], 5, 2), dtype=np.float32)
        for i in range(5):
            out[:, i, 0] = centers[:, 0] + distance[:, 2 * i]
            out[:, i, 1] = centers[:, 1] + distance[:, 2 * i + 1]
        return out

    # ------------------------------------------------------------------
    # NMS
    # ------------------------------------------------------------------

    @staticmethod
    def _nms(bboxes: np.ndarray, scores: np.ndarray, iou_threshold: float) -> np.ndarray:
        """Standard NMS. Returns indices of kept boxes, ordered by score descending."""
        if len(bboxes) == 0:
            return np.empty(0, dtype=np.int64)
        x1, y1, x2, y2 = bboxes[:, 0], bboxes[:, 1], bboxes[:, 2], bboxes[:, 3]
        areas = (x2 - x1) * (y2 - y1)
        order = scores.argsort()[::-1]
        keep = []
        while order.size > 0:
            i = order[0]
            keep.append(i)
            xx1 = np.maximum(x1[i], x1[order[1:]])
            yy1 = np.maximum(y1[i], y1[order[1:]])
            xx2 = np.minimum(x2[i], x2[order[1:]])
            yy2 = np.minimum(y2[i], y2[order[1:]])
            w = np.maximum(0.0, xx2 - xx1)
            h = np.maximum(0.0, yy2 - yy1)
            inter = w * h
            iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-8)
            order = order[1:][iou <= iou_threshold]
        return np.array(keep, dtype=np.int64)

    # ------------------------------------------------------------------
    # Full detect
    # ------------------------------------------------------------------

    def detect(self, image_bgr: np.ndarray) -> list[dict]:
        """Run face detection on a BGR image. Returns list of dicts with bbox + kps + score."""
        image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        padded, scale, pad_x, pad_y = self._preprocess(image_rgb)

        input_data = {self.input_name: np.expand_dims(padded, axis=0)}
        with self.network_group.activate(self.network_group_params):
            with InferVStreams(
                self.network_group,
                self.input_vstreams_params,
                self.output_vstreams_params,
            ) as pipeline:
                results = pipeline.infer(input_data)

        all_bboxes = []
        all_scores = []
        all_kpss = []

        for stride in self.FEAT_STRIDES:
            slot = self._output_names_by_stride[stride]
            # Flatten to (N, C) where N = H*W*A
            scores_raw = results[slot["scores"]].reshape(-1)
            bboxes_raw = results[slot["bboxes"]].reshape(-1, 4)
            kpss_raw = results[slot["kpss"]].reshape(-1, 10)

            # Predictions are in grid-cell units (need × stride for pixel distances)
            bboxes_raw = bboxes_raw * stride
            kpss_raw = kpss_raw * stride

            # Filter by score
            pos_inds = np.where(scores_raw >= self.score_threshold)[0]
            if pos_inds.size == 0:
                continue

            centers = self._center_cache[stride][pos_inds]
            bboxes = self._distance2bbox(centers, bboxes_raw[pos_inds])
            kpss = self._distance2kps(centers, kpss_raw[pos_inds])

            all_bboxes.append(bboxes)
            all_scores.append(scores_raw[pos_inds])
            all_kpss.append(kpss)

        if not all_bboxes:
            return []

        bboxes = np.concatenate(all_bboxes, axis=0)  # (N, 4) in 640x640 space
        scores = np.concatenate(all_scores, axis=0)  # (N,)
        kpss = np.concatenate(all_kpss, axis=0)      # (N, 5, 2)

        keep = self._nms(bboxes, scores, self.iou_threshold)
        bboxes, scores, kpss = bboxes[keep], scores[keep], kpss[keep]

        # Map back from 640x640 padded space to original image coords
        # (pad is top-left so only the scale inverse is needed)
        bboxes /= scale
        kpss /= scale

        # Build result dicts
        detections = []
        h, w = image_bgr.shape[:2]
        for i in range(len(bboxes)):
            x1, y1, x2, y2 = bboxes[i]
            x1 = max(0.0, min(x1, w - 1))
            y1 = max(0.0, min(y1, h - 1))
            x2 = max(0.0, min(x2, w - 1))
            y2 = max(0.0, min(y2, h - 1))
            detections.append({
                "bbox": (float(x1), float(y1), float(x2), float(y2)),
                "keypoints": kpss[i].tolist(),  # [[x, y], ...] × 5
                "score": float(scores[i]),
            })
        return detections


if __name__ == "__main__":
    import sys
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("image", help="Path to image")
    parser.add_argument("--arch", default="hailo8")
    parser.add_argument("--output", default="/tmp/scrfd_detections.jpg")
    args = parser.parse_args()

    hef_path = os.path.join(
        os.environ.get("HAILO_RESOURCES_PATH", "/usr/local/hailo/resources"),
        "models", args.arch, "scrfd_10g.hef",
    )
    detector = HailoScrfd(hef_path)

    image = cv2.imread(args.image)
    if image is None:
        print(f"Could not read {args.image}", file=sys.stderr)
        sys.exit(1)

    dets = detector.detect(image)
    print(f"Found {len(dets)} face(s)")

    for d in dets:
        x1, y1, x2, y2 = [int(v) for v in d["bbox"]]
        cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(
            image, f"{d['score']:.2f}", (x1, y1 - 5),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1,
        )
        kp_colors = [(0, 0, 255), (0, 255, 0), (255, 0, 0), (0, 255, 255), (255, 0, 255)]
        for i, (kx, ky) in enumerate(d["keypoints"]):
            cv2.circle(image, (int(kx), int(ky)), 3, kp_colors[i], -1)

    cv2.imwrite(args.output, image)
    print(f"Saved: {args.output}")
