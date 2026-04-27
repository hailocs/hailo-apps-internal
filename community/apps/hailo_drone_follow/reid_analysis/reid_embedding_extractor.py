"""
ReID Embedding Extractor
========================
Concrete implementation of ReIDBackend for OSNET and RepVGG models.
Uses HailoRT Python API (hailo_platform) for on-device inference.

Usage:
    extractor = OSNetExtractor(hef_path="/usr/local/hailo/resources/models/hailo8/osnet_x1_0.hef")
    embedding = extractor.extract_embedding(crop_bgr)   # single crop
    embeddings = extractor.extract_embeddings_batch([crop1, crop2, ...])  # batch
    extractor.release()
"""

import os

import cv2
import numpy as np
from hailo_platform import HEF, FormatType, HailoSchedulingAlgorithm, VDevice

from hailo_apps.python.core.common.defines import SHARED_VDEVICE_GROUP_ID
from hailo_apps.python.core.common.hailo_logger import get_logger

logger = get_logger(__name__)


class HailoReIDExtractor:
    """
    Base ReID embedding extractor using HailoRT async inference API.
    Handles: HEF loading, VDevice setup, preprocessing, inference, postprocessing.
    """

    def __init__(
        self,
        hef_path: str,
        batch_size: int = 1,
        input_type: str = "UINT8",
        output_type: str = "FLOAT32",
    ):
        self.hef_path = hef_path
        self.batch_size = batch_size

        # ── Load HEF & configure VDevice ──
        params = VDevice.create_params()
        params.scheduling_algorithm = HailoSchedulingAlgorithm.ROUND_ROBIN
        params.group_id = SHARED_VDEVICE_GROUP_ID
        self._vdevice = VDevice(params)

        self._hef = HEF(os.fspath(hef_path))
        self._infer_model = self._vdevice.create_infer_model(os.fspath(hef_path))
        self._infer_model.set_batch_size(batch_size)

        # Set input/output formats
        self._infer_model.input().set_format_type(getattr(FormatType, input_type))
        for out_info in self._hef.get_output_vstream_infos():
            self._infer_model.output(out_info.name).set_format_type(
                getattr(FormatType, output_type)
            )

        # Build output name -> dtype mapping
        output_infos = self._hef.get_output_vstream_infos()
        self._output_type = {
            info.name: output_type for info in output_infos
        }
        self._first_output_name = output_infos[0].name

        # Configure (enter context)
        self._config_ctx = self._infer_model.configure()
        self._configured_model = self._config_ctx.__enter__()

        # Cache input shape from HEF: (H, W, C) or (batch, H, W, C)
        vstream_info = self._hef.get_input_vstream_infos()[0]
        shape = vstream_info.shape
        if len(shape) == 4:
            self._input_h, self._input_w, self._input_c = shape[1], shape[2], shape[3]
        else:
            self._input_h, self._input_w, self._input_c = shape[0], shape[1], shape[2]

    # ── Properties ──

    @property
    def input_shape(self) -> tuple:
        """(H, W, C) expected by the model."""
        return (self._input_h, self._input_w, self._input_c)

    @property
    def embedding_dim(self) -> int:
        """Output embedding dimensionality (read from HEF)."""
        out_info = self._hef.get_output_vstream_infos()[0]
        # Shape is typically (batch, dim) or (batch, 1, 1, dim)
        return int(np.prod(out_info.shape[1:]))

    @property
    def model_name(self) -> str:
        return os.path.basename(self.hef_path).replace(".hef", "")

    # ── Preprocessing ──

    def preprocess(self, crop_bgr: np.ndarray) -> np.ndarray:
        """
        Resize BGR crop to model input size.
        HailoRT handles quantization internally when input_type=UINT8.

        Args:
            crop_bgr: (H, W, 3) uint8 BGR image.

        Returns:
            (input_h, input_w, 3) uint8 array ready for inference.
        """
        resized = cv2.resize(crop_bgr, (self._input_w, self._input_h))
        return resized.astype(np.uint8)

    # ── Postprocessing ──

    def postprocess(self, raw_output: np.ndarray) -> np.ndarray:
        """
        Flatten and L2-normalize the raw model output into an embedding vector.

        Args:
            raw_output: Raw output buffer from HailoRT.

        Returns:
            1D normalized embedding vector.
        """
        embedding = raw_output.flatten().astype(np.float32)
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm
        return embedding

    # ── Inference ──

    def extract_embedding(self, crop_bgr: np.ndarray) -> np.ndarray:
        """
        Full pipeline: preprocess -> infer -> postprocess.

        Args:
            crop_bgr: Single person crop in BGR format.

        Returns:
            Normalized embedding vector (1D float32 array).
        """
        preprocessed = self.preprocess(crop_bgr)
        raw = self._infer_single(preprocessed)
        return self.postprocess(raw)

    def extract_embeddings_batch(self, crops_bgr: list[np.ndarray]) -> list[np.ndarray]:
        """
        Batch extraction: preprocess all crops, infer as batch, postprocess.

        Args:
            crops_bgr: List of BGR person crops.

        Returns:
            List of normalized embedding vectors.
        """
        if not crops_bgr:
            return []

        preprocessed_batch = [self.preprocess(crop) for crop in crops_bgr]
        raw_outputs = self._infer_batch(preprocessed_batch)
        return [self.postprocess(raw) for raw in raw_outputs]

    def _infer_single(self, preprocessed: np.ndarray) -> np.ndarray:
        """Run inference on a single preprocessed frame."""
        results = self._infer_batch([preprocessed])
        return results[0]

    def _infer_batch(self, preprocessed_batch: list[np.ndarray]) -> list[np.ndarray]:
        """
        Run async inference on a batch of preprocessed frames.
        Uses the same pattern as hailo_apps HailoInfer.
        Chunks into batch_size to avoid overflowing HailoRT's internal queue.

        Returns:
            List of raw output arrays, one per input frame.
        """
        raw_outputs = []
        chunk_size = max(1, self.batch_size)

        for i in range(0, len(preprocessed_batch), chunk_size):
            chunk = preprocessed_batch[i : i + chunk_size]

            # Create bindings for each frame in this chunk
            bindings_list = []
            for frame in chunk:
                output_buffers = {
                    name: np.empty(
                        self._infer_model.output(name).shape,
                        dtype=getattr(np, self._output_type[name].lower()),
                    )
                    for name in self._output_type
                }
                binding = self._configured_model.create_bindings(output_buffers=output_buffers)
                binding.input().set_buffer(np.array(frame))
                bindings_list.append(binding)

            # Run async inference
            self._configured_model.wait_for_async_ready(timeout_ms=10000)
            job = self._configured_model.run_async(bindings_list, lambda *args, **kwargs: None)
            job.wait(timeout_ms=10000)

            # Collect outputs
            for binding in bindings_list:
                raw = binding.output(self._first_output_name).get_buffer()
                raw_outputs.append(raw)

        return raw_outputs

    # ── Cleanup ──

    def release(self):
        """Release HailoRT resources (config context first, then VDevice)."""
        if self._config_ctx:
            self._config_ctx.__exit__(None, None, None)
            self._config_ctx = None
        if self._vdevice:
            self._vdevice.release()
            self._vdevice = None


# ── Default HEF paths (overridable via constructor or env) ──

_HAILO_MODELS_DIR = os.environ.get(
    "HAILO_MODELS_DIR", "/usr/local/hailo/resources/models/hailo8"
)
_DEFAULT_OSNET_HEF = os.path.join(_HAILO_MODELS_DIR, "osnet_x1_0.hef")
_DEFAULT_REPVGG_HEF = os.path.join(_HAILO_MODELS_DIR, "repvgg_a0_person_reid_512.hef")


# ── Convenience subclasses ──

class OSNetExtractor(HailoReIDExtractor):
    """OSNET x1_0 extractor. 512-dim embeddings, 256x128 input, ~180 FPS."""

    def __init__(self, hef_path: str | None = None, **kwargs):
        super().__init__(hef_path=hef_path or _DEFAULT_OSNET_HEF, **kwargs)


class RepVGG512Extractor(HailoReIDExtractor):
    """RepVGG A0 512-dim extractor. 256x128 input, ~5200 FPS."""

    def __init__(self, hef_path: str | None = None, **kwargs):
        super().__init__(hef_path=hef_path or _DEFAULT_REPVGG_HEF, **kwargs)


# ── Cross-matching matrix ──
if __name__ == "__main__":
    import sys
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description="ReID cross-matching matrix between person images")
    parser.add_argument("--images-dir", type=str, default="reid-imgs", help="Directory with person images")
    args = parser.parse_args()

    # Load images
    images_dir = Path(args.images_dir)
    image_paths = sorted(
        p for p in images_dir.iterdir()
        if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp")
    )
    if not image_paths:
        logger.error("No images found in %s", images_dir)
        sys.exit(1)

    names = [p.stem for p in image_paths]
    crops = [cv2.imread(str(p)) for p in image_paths]
    for i, crop in enumerate(crops):
        if crop is None:
            logger.error("Failed to load %s", image_paths[i])
            sys.exit(1)

    logger.info("Loaded %d images: %s", len(crops), names)

    # Run both models
    extractors = [RepVGG512Extractor(), OSNetExtractor()]

    for extractor in extractors:
        logger.info("=== %s (dim=%d) ===", extractor.model_name, extractor.embedding_dim)

        embeddings = extractor.extract_embeddings_batch(crops)
        emb_matrix = np.stack(embeddings)  # (N, D)

        # Cosine similarity = dot product (embeddings are L2-normalized)
        sim_matrix = emb_matrix @ emb_matrix.T

        # Print table (user-facing output)
        col_width = max(len(n) for n in names) + 2
        header = " " * col_width + "".join(n.rjust(col_width) for n in names)
        print(header)
        for i, name in enumerate(names):
            row = name.ljust(col_width) + "".join(
                f"{sim_matrix[i, j]:.3f}".rjust(col_width) for j in range(len(names))
            )
            print(row)
        print()

        extractor.release()

    logger.info("Done.")