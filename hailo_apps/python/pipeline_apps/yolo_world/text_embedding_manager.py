"""Manages CLIP text embeddings for YOLO World zero-shot detection.

YOLO World v2s was trained against HuggingFace `openai/clip-vit-base-patch32`
text embeddings. We reproduce those embeddings with a **pure-NumPy CLIP text
encoder** ([numpy_clip_text_encoder.py]) — numerically identical to HF
(validated at cosine 1.0), but with no `torch`/`transformers` runtime
dependency. This also avoids the on-device Hailo CLIP HEF, whose 8-bit output
quantization distorted the embedding geometry enough to break YOLO World's
class head (~16% detection match vs HF; see tests/test_clip_equivalence.py / test_e2e_parity.py).

Embeddings are computed once at startup, cached to disk, and re-encoded on
prompts-file change. Runtime deps: numpy + tokenizers (both lightweight).
"""
import json
import os
import threading
from pathlib import Path

import numpy as np

from hailo_apps.python.core.common.defines import (
    YOLO_WORLD_EMBEDDING_DIM,
    YOLO_WORLD_MAX_CLASSES,
)
from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.pipeline_apps.yolo_world.numpy_clip_text_encoder import (
    NumpyClipTextEncoder,
)

logger = get_logger(__name__)

MAX_CLASSES = YOLO_WORLD_MAX_CLASSES
EMBEDDING_DIM = YOLO_WORLD_EMBEDDING_DIM
_WATCH_POLL_SECONDS = 2.0


class TextEmbeddingManager:
    """Encodes prompts via the pure-NumPy CLIP text encoder.

    Public API:
        get_embeddings()  -> np.ndarray (1, 80, 512) float32, L2-normalized
        get_labels()      -> list[str]
        get_num_classes() -> int
        update_prompts(list[str])
        stop()
    """

    def __init__(self, prompts=None, prompts_file=None, embeddings_file=None,
                 watch=False, default_prompts_path=None):
        self._lock = threading.Lock()
        self._embeddings = None  # (1, 80, 512) float32
        self._labels = []
        self._watch = watch
        self._watch_thread = None
        self._stop_event = threading.Event()
        self._prompts_file = prompts_file
        self._encoder = None  # lazy — only built if we actually need to encode

        if default_prompts_path is None:
            default_prompts_path = str(Path(__file__).parent / "default_prompts.json")
        self._default_prompts_path = default_prompts_path

        if embeddings_file is None:
            embeddings_file = str(Path(__file__).parent / "embeddings.json")
        self._embeddings_file = embeddings_file

        self._initialize(prompts, prompts_file)

        if watch and prompts_file:
            self._start_watcher()

    def _initialize(self, prompts, prompts_file):
        if prompts:
            prompt_list = [p.strip() for p in prompts.split(",") if p.strip()]
            logger.info("Using CLI prompts: %s", prompt_list)
            self._encode_and_cache(prompt_list)
        elif prompts_file:
            prompt_list = self._load_prompts_file(prompts_file)
            logger.info("Using prompts from file: %s (%d classes)", prompts_file, len(prompt_list))
            self._encode_and_cache(prompt_list)
        elif os.path.isfile(self._embeddings_file):
            logger.info("Loading cached embeddings from %s", self._embeddings_file)
            self._load_cached()
        else:
            prompt_list = self._load_prompts_file(self._default_prompts_path)
            logger.info("Using default COCO-80 prompts (%d classes)", len(prompt_list))
            self._encode_and_cache(prompt_list)

    def _load_prompts_file(self, path):
        with open(path, "r") as f:
            prompts = json.load(f)
        if not isinstance(prompts, list) or not all(isinstance(p, str) for p in prompts):
            raise ValueError(f"Prompts file must be a JSON array of strings: {path}")
        if len(prompts) > MAX_CLASSES:
            logger.warning("Truncating prompts to %d (max for YOLO World HEF)", MAX_CLASSES)
            prompts = prompts[:MAX_CLASSES]
        return prompts

    def _encode_and_cache(self, prompt_list):
        embeddings = self._generate_embeddings(prompt_list)
        self._set_embeddings(embeddings, prompt_list)
        self._save_cached(prompt_list, embeddings)

    @property
    def encoder(self):
        """The shared NumPy CLIP encoder (built on first use). Lets other
        components (e.g. PromptSuggester) reuse it instead of loading weights twice."""
        if self._encoder is None:
            self._encoder = NumpyClipTextEncoder()
        return self._encoder

    def _generate_embeddings(self, prompt_list):
        """Run the pure-NumPy CLIP text encoder. Returns (N, 512) L2-normalized."""
        if self._encoder is None:
            self._encoder = NumpyClipTextEncoder()
        logger.info("Encoding %d prompts (numpy CLIP)...", len(prompt_list))
        embeddings = self._encoder.encode_prompts(prompt_list)
        logger.info("Generated embeddings shape: %s", embeddings.shape)
        return embeddings

    def _set_embeddings(self, embeddings, labels):
        n = embeddings.shape[0]
        padded = np.zeros((1, MAX_CLASSES, EMBEDDING_DIM), dtype=np.float32)
        padded[0, :n, :] = embeddings
        with self._lock:
            self._embeddings = padded
            self._labels = list(labels)

    def _save_cached(self, labels, embeddings):
        data = {"labels": labels, "embeddings": embeddings.tolist()}
        with open(self._embeddings_file, "w") as f:
            json.dump(data, f)
        logger.info("Cached embeddings to %s", self._embeddings_file)

    def _load_cached(self):
        with open(self._embeddings_file, "r") as f:
            data = json.load(f)
        labels = data["labels"]
        embeddings = np.array(data["embeddings"], dtype=np.float32)
        self._set_embeddings(embeddings, labels)
        logger.info("Loaded %d cached embeddings", len(labels))

    def get_embeddings(self):
        return self._embeddings

    def get_labels(self):
        with self._lock:
            return list(self._labels)

    def get_num_classes(self):
        with self._lock:
            return len(self._labels)

    def update_prompts(self, prompt_list):
        if len(prompt_list) > MAX_CLASSES:
            logger.warning("Truncating to %d classes", MAX_CLASSES)
            prompt_list = prompt_list[:MAX_CLASSES]
        logger.info("Updating prompts: %s", prompt_list)
        embeddings = self._generate_embeddings(prompt_list)
        self._set_embeddings(embeddings, prompt_list)
        self._save_cached(prompt_list, embeddings)
        logger.info("Prompts updated successfully")

    def _start_watcher(self):
        self._watch_thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._watch_thread.start()
        logger.info("Watching %s for changes", self._prompts_file)

    def _watch_loop(self):
        last_mtime = os.path.getmtime(self._prompts_file)
        while not self._stop_event.is_set():
            self._stop_event.wait(_WATCH_POLL_SECONDS)
            try:
                current_mtime = os.path.getmtime(self._prompts_file)
                if current_mtime != last_mtime:
                    last_mtime = current_mtime
                    logger.info("Prompts file changed, reloading...")
                    prompt_list = self._load_prompts_file(self._prompts_file)
                    self.update_prompts(prompt_list)
            except Exception as e:  # noqa: BLE001 — watcher must not crash the app
                logger.error("Error watching prompts file: %s", e)

    def stop(self):
        self._stop_event.set()
        if self._watch_thread:
            self._watch_thread.join(timeout=5)
