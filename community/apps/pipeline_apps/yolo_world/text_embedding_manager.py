import json
import os
import threading
import time
from pathlib import Path

import numpy as np

from hailo_apps.python.core.common.hailo_logger import get_logger

logger = get_logger(__name__)

MAX_CLASSES = 80
EMBEDDING_DIM = 512
CLIP_MODEL_NAME = "openai/clip-vit-base-patch32"


class TextEmbeddingManager:
    """Manages CLIP text embeddings for YOLO World zero-shot detection.

    Generates embeddings from text prompts using HuggingFace CLIPTextModelWithProjection,
    caches them to disk, and supports runtime updates via file watching.
    """

    def __init__(self, prompts=None, prompts_file=None, embeddings_file=None,
                 watch=False, default_prompts_path=None):
        self._lock = threading.Lock()
        self._embeddings = None  # shape: (1, 80, 512) float32
        self._labels = []
        self._watch = watch
        self._watch_thread = None
        self._stop_event = threading.Event()
        self._prompts_file = prompts_file

        if default_prompts_path is None:
            default_prompts_path = str(Path(__file__).parent / "default_prompts.json")
        self._default_prompts_path = default_prompts_path

        if embeddings_file is None:
            embeddings_file = str(Path(__file__).parent / "embeddings.json")
        self._embeddings_file = embeddings_file

        # Resolve prompts and generate/load embeddings
        self._initialize(prompts, prompts_file)

        # Start file watcher if requested
        if watch and prompts_file:
            self._start_watcher()

    def _initialize(self, prompts, prompts_file):
        """Determine prompt source and load/generate embeddings."""
        if prompts:
            # CLI --prompts "cat,dog,person"
            prompt_list = [p.strip() for p in prompts.split(",")]
            logger.info("Using CLI prompts: %s", prompt_list)
            self._encode_and_cache(prompt_list)
        elif prompts_file:
            # --prompts-file my_classes.json
            prompt_list = self._load_prompts_file(prompts_file)
            logger.info("Using prompts from file: %s (%d classes)", prompts_file, len(prompt_list))
            self._encode_and_cache(prompt_list)
        elif os.path.isfile(self._embeddings_file):
            # Cached embeddings exist
            logger.info("Loading cached embeddings from %s", self._embeddings_file)
            self._load_cached()
        else:
            # Default COCO-80
            prompt_list = self._load_prompts_file(self._default_prompts_path)
            logger.info("Using default COCO-80 prompts (%d classes)", len(prompt_list))
            self._encode_and_cache(prompt_list)

    def _load_prompts_file(self, path):
        """Load a JSON array of class name strings."""
        with open(path, "r") as f:
            prompts = json.load(f)
        if not isinstance(prompts, list) or not all(isinstance(p, str) for p in prompts):
            raise ValueError(f"Prompts file must be a JSON array of strings: {path}")
        if len(prompts) > MAX_CLASSES:
            logger.warning("Truncating prompts to %d (max for YOLO World HEF)", MAX_CLASSES)
            prompts = prompts[:MAX_CLASSES]
        return prompts

    def _encode_and_cache(self, prompt_list):
        """Generate CLIP embeddings for prompts and cache to disk."""
        embeddings = self._generate_embeddings(prompt_list)
        self._set_embeddings(embeddings, prompt_list)
        self._save_cached(prompt_list, embeddings)

    @staticmethod
    def _generate_embeddings(prompt_list):
        """Run CLIP text encoder on CPU to produce L2-normalized embeddings.

        Returns ndarray of shape (N, 512) where N = len(prompt_list).
        """
        try:
            import torch
            from transformers import AutoTokenizer, CLIPTextModelWithProjection
        except ImportError:
            raise ImportError(
                "Text encoding requires 'transformers' and 'torch' packages. "
                "Install with: pip install transformers torch\n"
                "Alternatively, provide pre-cached embeddings via --embeddings-file"
            )

        logger.info("Loading CLIP text encoder: %s", CLIP_MODEL_NAME)
        tokenizer = AutoTokenizer.from_pretrained(CLIP_MODEL_NAME)
        model = CLIPTextModelWithProjection.from_pretrained(CLIP_MODEL_NAME)
        model.eval()

        logger.info("Encoding %d prompts...", len(prompt_list))
        with torch.no_grad():
            inputs = tokenizer(prompt_list, return_tensors="pt", padding=True)
            outputs = model(**inputs)
            text_embeds = outputs.text_embeds  # (N, 512)
            # L2 normalize — matches model zoo reference
            text_embeds = text_embeds / text_embeds.norm(p=2, dim=-1, keepdim=True)

        embeddings = text_embeds.cpu().numpy().astype(np.float32)
        logger.info("Generated embeddings shape: %s", embeddings.shape)
        return embeddings

    def _set_embeddings(self, embeddings, labels):
        """Assemble into (1, 80, 512) tensor and set atomically."""
        n = embeddings.shape[0]
        padded = np.zeros((1, MAX_CLASSES, EMBEDDING_DIM), dtype=np.float32)
        padded[0, :n, :] = embeddings
        with self._lock:
            self._embeddings = padded
            self._labels = list(labels)

    def _save_cached(self, labels, embeddings):
        """Cache embeddings + labels to JSON file."""
        data = {
            "labels": labels,
            "embeddings": embeddings.tolist(),
        }
        with open(self._embeddings_file, "w") as f:
            json.dump(data, f)
        logger.info("Cached embeddings to %s", self._embeddings_file)

    def _load_cached(self):
        """Load embeddings + labels from cached JSON file."""
        with open(self._embeddings_file, "r") as f:
            data = json.load(f)
        labels = data["labels"]
        embeddings = np.array(data["embeddings"], dtype=np.float32)
        self._set_embeddings(embeddings, labels)
        logger.info("Loaded %d cached embeddings", len(labels))

    def get_embeddings(self):
        """Return current (1, 80, 512) embedding tensor. Thread-safe."""
        return self._embeddings

    def get_labels(self):
        """Return current label list. Thread-safe."""
        with self._lock:
            return list(self._labels)

    def get_num_classes(self):
        """Return number of active classes (not padded)."""
        with self._lock:
            return len(self._labels)

    def update_prompts(self, prompt_list):
        """Re-encode prompts and swap embeddings atomically."""
        if len(prompt_list) > MAX_CLASSES:
            logger.warning("Truncating to %d classes", MAX_CLASSES)
            prompt_list = prompt_list[:MAX_CLASSES]
        logger.info("Updating prompts: %s", prompt_list)
        embeddings = self._generate_embeddings(prompt_list)
        self._set_embeddings(embeddings, prompt_list)
        self._save_cached(prompt_list, embeddings)
        logger.info("Prompts updated successfully")

    def _start_watcher(self):
        """Watch prompts file for modifications and reload."""
        self._watch_thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._watch_thread.start()
        logger.info("Watching %s for changes", self._prompts_file)

    def _watch_loop(self):
        """Poll prompts file mtime every 2 seconds."""
        last_mtime = os.path.getmtime(self._prompts_file)
        while not self._stop_event.is_set():
            self._stop_event.wait(2.0)
            try:
                current_mtime = os.path.getmtime(self._prompts_file)
                if current_mtime != last_mtime:
                    last_mtime = current_mtime
                    logger.info("Prompts file changed, reloading...")
                    prompt_list = self._load_prompts_file(self._prompts_file)
                    self.update_prompts(prompt_list)
            except Exception as e:
                logger.error("Error watching prompts file: %s", e)

    def stop(self):
        """Stop the file watcher thread."""
        self._stop_event.set()
        if self._watch_thread:
            self._watch_thread.join(timeout=5)
