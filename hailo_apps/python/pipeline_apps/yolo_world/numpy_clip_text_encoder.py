"""Pure-NumPy CLIP ViT-B/32 text encoder.

Runtime dependencies: numpy + tokenizers (lightweight, Rust-based; already a
repo dependency). No torch, no transformers.

Numerically identical to HuggingFace `CLIPTextModelWithProjection` + L2 norm
(validated at cosine 1.0 across COCO-80 + open-vocab prompts), so it produces
exactly the text embeddings YOLO World v2s was trained against — with none of
the quantization loss that made the on-device Hailo CLIP HEF unusable.

Weights:
- Transformer body (12 layers + positional embeddings + final LayerNorm) load
  from a packaged npz (`clip_text_vitb32_body_fp16.npz`, ~67 MB).
- The token-embedding LUT and the text-projection matrix are the repo's existing
  shared CLIP resources (`token_embedding_lut.npy`, `text_projection.npy`),
  both bit-exact to HF — so we don't duplicate ~50 MB of token embeddings.

Regenerate the body npz with `extract_clip_text_weights.py` (the only
place torch/transformers is needed, and only offline).
"""
import json
from pathlib import Path

import numpy as np

from hailo_apps.python.core.common.core import get_resource_path
from hailo_apps.python.core.common.defines import RESOURCES_NPY_DIR_NAME
from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.pipeline_apps.clip.clip_text_utils import (
    DEFAULT_TEXT_PROJECTION_PATH,
    load_clip_tokenizer,
    load_token_embeddings,
    tokenize_text,
)

logger = get_logger(__name__)

BODY_WEIGHTS_NAME = "clip_text_vitb32_body_fp16.npz"
META_NAME = "clip_text_vitb32_meta.json"
MAX_TOKENS = 77


def _layer_norm(x, w, b, eps):
    mu = x.mean(axis=-1, keepdims=True)
    var = x.var(axis=-1, keepdims=True)
    return (x - mu) / np.sqrt(var + eps) * w + b


def _quick_gelu(x):
    # sigmoid(1.702 x); clip the exponent to avoid overflow warnings on large
    # negative activations (sigmoid is saturated well before ±50).
    z = np.clip(1.702 * x, -50.0, 50.0)
    return x * (1.0 / (1.0 + np.exp(-z)))


def _softmax(x, axis=-1):
    x = x - x.max(axis=axis, keepdims=True)
    e = np.exp(x)
    return e / e.sum(axis=axis, keepdims=True)


class NumpyClipTextEncoder:
    """Pure-numpy CLIP text encoder producing L2-normalized 512-d embeddings."""

    def __init__(self, body_weights_path=None, meta_path=None):
        if body_weights_path is None:
            body_weights_path = get_resource_path(
                pipeline_name=None, resource_type=RESOURCES_NPY_DIR_NAME,
                arch=None, model=BODY_WEIGHTS_NAME,
            )
        if meta_path is None:
            # meta is tiny architecture config shipped in-package (not S3).
            meta_path = str(Path(__file__).parent / META_NAME)
        if body_weights_path is None or not Path(body_weights_path).exists():
            raise FileNotFoundError(
                f"CLIP text-encoder body weights not found ({BODY_WEIGHTS_NAME}). "
                f"Regenerate with extract_clip_text_weights.py."
            )

        meta = json.loads(Path(meta_path).read_text())
        self.n_layers = int(meta["n_layers"])
        self.hidden = int(meta["hidden"])
        self.heads = int(meta["heads"])
        self.head_dim = self.hidden // self.heads
        self.eps = float(meta["ln_eps"])
        self.scale = self.head_dim ** -0.5

        # Body weights (fp16 on disk → fp32 in memory for stable math).
        self.w = {k: np.asarray(v, dtype=np.float32)
                  for k, v in np.load(body_weights_path).items()}
        # Shared repo resources (bit-exact to HF).
        self.w["token_embedding"] = load_token_embeddings().astype(np.float32)
        # repo text_projection.npy == HF text_projection.weight.T, so we apply
        # it directly as `pooled @ proj` (no transpose).
        self.w["text_projection"] = np.load(DEFAULT_TEXT_PROJECTION_PATH).astype(np.float32)

        n = self.w["position_embedding"].shape[0]
        self._causal = np.triu(np.full((n, n), -np.inf, dtype=np.float32), k=1)
        self._tokenizer = load_clip_tokenizer()
        logger.info("NumpyClipTextEncoder ready (%d layers, hidden=%d)", self.n_layers, self.hidden)

    def _attn(self, x, li):
        w = self.w
        N, S, _ = x.shape
        q = (x @ w[f"l{li}.q_w"].T + w[f"l{li}.q_b"]) * self.scale
        k = x @ w[f"l{li}.k_w"].T + w[f"l{li}.k_b"]
        v = x @ w[f"l{li}.v_w"].T + w[f"l{li}.v_b"]

        def split(t):
            return t.reshape(N, S, self.heads, self.head_dim).transpose(0, 2, 1, 3)

        q, k, v = split(q), split(k), split(v)
        attn = q @ k.transpose(0, 1, 3, 2)
        attn = attn + self._causal[:S, :S]
        attn = _softmax(attn, axis=-1)
        ctx = (attn @ v).transpose(0, 2, 1, 3).reshape(N, S, self.hidden)
        return ctx @ w[f"l{li}.o_w"].T + w[f"l{li}.o_b"]

    def encode_prompts(self, prompts):
        """Encode a list of text prompts → (N, 512) float32, L2-normalized."""
        ids = np.asarray(
            [tokenize_text(p, self._tokenizer, max_length=MAX_TOKENS)["input_ids"][0] for p in prompts],
            dtype=np.int64,
        )
        return self._encode_ids(ids)

    def _encode_ids(self, ids):
        w = self.w
        eot = ids.argmax(axis=1)               # EOT (49407) is the highest token id
        S = int(eot.max()) + 1                 # trim to the longest meaningful prefix
        ids = ids[:, :S]
        N = ids.shape[0]
        x = w["token_embedding"][ids] + w["position_embedding"][:S]
        for li in range(self.n_layers):
            res = x
            h = _layer_norm(x, w[f"l{li}.ln1_w"], w[f"l{li}.ln1_b"], self.eps)
            x = res + self._attn(h, li)
            res = x
            h = _layer_norm(x, w[f"l{li}.ln2_w"], w[f"l{li}.ln2_b"], self.eps)
            h = _quick_gelu(h @ w[f"l{li}.fc1_w"].T + w[f"l{li}.fc1_b"])
            h = h @ w[f"l{li}.fc2_w"].T + w[f"l{li}.fc2_b"]
            x = res + h
        x = _layer_norm(x, w["final_ln_w"], w["final_ln_b"], self.eps)
        pooled = x[np.arange(N), eot]
        feat = pooled @ w["text_projection"]
        return (feat / (np.linalg.norm(feat, axis=-1, keepdims=True) + 1e-8)).astype(np.float32)
