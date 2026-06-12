"""Unit tests for TextEmbeddingManager: caching, prompt parsing, padding.

Patches _generate_embeddings to avoid importing torch/transformers.
"""

import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from community.apps.pipeline_apps.yolo_world.text_embedding_manager import (
    EMBEDDING_DIM,
    MAX_CLASSES,
    TextEmbeddingManager,
)


def _fake_embeddings(prompt_list):
    """Deterministic stand-in for CLIP encoder: hash-style normalized vector."""
    n = len(prompt_list)
    embs = np.zeros((n, EMBEDDING_DIM), dtype=np.float32)
    for i, p in enumerate(prompt_list):
        # Spread a value across the vector deterministically by index
        embs[i, i % EMBEDDING_DIM] = 1.0
    return embs


class TestPromptFileParsing:
    def test_valid_json_list_loads(self, tmp_path):
        p = tmp_path / "prompts.json"
        p.write_text(json.dumps(["cat", "dog", "person"]))
        with patch.object(TextEmbeddingManager, "_generate_embeddings", staticmethod(_fake_embeddings)):
            mgr = TextEmbeddingManager(prompts_file=str(p))
        assert mgr.get_labels() == ["cat", "dog", "person"]
        assert mgr.get_num_classes() == 3

    def test_non_list_json_raises(self, tmp_path):
        p = tmp_path / "prompts.json"
        p.write_text(json.dumps({"classes": ["cat"]}))
        with patch.object(TextEmbeddingManager, "_generate_embeddings", staticmethod(_fake_embeddings)):
            with pytest.raises(ValueError):
                TextEmbeddingManager(prompts_file=str(p))

    def test_non_string_items_raises(self, tmp_path):
        p = tmp_path / "prompts.json"
        p.write_text(json.dumps(["cat", 42]))
        with patch.object(TextEmbeddingManager, "_generate_embeddings", staticmethod(_fake_embeddings)):
            with pytest.raises(ValueError):
                TextEmbeddingManager(prompts_file=str(p))

    def test_truncates_to_max_classes(self, tmp_path):
        big_list = [f"class_{i}" for i in range(MAX_CLASSES + 50)]
        p = tmp_path / "prompts.json"
        p.write_text(json.dumps(big_list))
        with patch.object(TextEmbeddingManager, "_generate_embeddings", staticmethod(_fake_embeddings)):
            mgr = TextEmbeddingManager(prompts_file=str(p))
        assert mgr.get_num_classes() == MAX_CLASSES


class TestCliPrompts:
    def test_cli_prompts_comma_separated(self, tmp_path):
        with patch.object(TextEmbeddingManager, "_generate_embeddings", staticmethod(_fake_embeddings)):
            mgr = TextEmbeddingManager(
                prompts="cat, dog ,person",
                embeddings_file=str(tmp_path / "embeds.json"),
            )
        # Whitespace stripped
        assert mgr.get_labels() == ["cat", "dog", "person"]


class TestPaddingAndShape:
    def test_embeddings_padded_to_max_classes(self, tmp_path):
        with patch.object(TextEmbeddingManager, "_generate_embeddings", staticmethod(_fake_embeddings)):
            mgr = TextEmbeddingManager(
                prompts="a,b,c",
                embeddings_file=str(tmp_path / "embeds.json"),
            )
        embeds = mgr.get_embeddings()
        assert embeds.shape == (1, MAX_CLASSES, EMBEDDING_DIM)
        # First 3 rows have content, rest is zero-padded
        assert np.any(embeds[0, :3, :] != 0)
        assert np.all(embeds[0, 3:, :] == 0)

    def test_embeddings_dtype_is_float32(self, tmp_path):
        with patch.object(TextEmbeddingManager, "_generate_embeddings", staticmethod(_fake_embeddings)):
            mgr = TextEmbeddingManager(
                prompts="a",
                embeddings_file=str(tmp_path / "embeds.json"),
            )
        assert mgr.get_embeddings().dtype == np.float32


class TestCacheRoundtrip:
    def test_save_load_roundtrip(self, tmp_path):
        cache = tmp_path / "embeds.json"
        # Save
        with patch.object(TextEmbeddingManager, "_generate_embeddings", staticmethod(_fake_embeddings)):
            mgr = TextEmbeddingManager(
                prompts="alpha,beta,gamma",
                embeddings_file=str(cache),
            )
        original_labels = mgr.get_labels()
        original_embeds = mgr.get_embeddings()
        del mgr

        # Load from cache (no prompts/prompts_file)
        mgr2 = TextEmbeddingManager(embeddings_file=str(cache))
        assert mgr2.get_labels() == original_labels
        np.testing.assert_array_equal(mgr2.get_embeddings(), original_embeds)

    def test_cache_file_format(self, tmp_path):
        cache = tmp_path / "embeds.json"
        with patch.object(TextEmbeddingManager, "_generate_embeddings", staticmethod(_fake_embeddings)):
            TextEmbeddingManager(prompts="x,y", embeddings_file=str(cache))
        data = json.loads(cache.read_text())
        assert "labels" in data
        assert "embeddings" in data
        assert data["labels"] == ["x", "y"]
        assert isinstance(data["embeddings"], list)


class TestUpdatePrompts:
    def test_update_replaces_labels(self, tmp_path):
        cache = tmp_path / "embeds.json"
        with patch.object(TextEmbeddingManager, "_generate_embeddings", staticmethod(_fake_embeddings)):
            mgr = TextEmbeddingManager(
                prompts="cat,dog",
                embeddings_file=str(cache),
            )
            mgr.update_prompts(["bird", "fish", "snake"])
        assert mgr.get_labels() == ["bird", "fish", "snake"]
        assert mgr.get_num_classes() == 3

    def test_update_truncates_oversized(self, tmp_path):
        big_list = [f"c_{i}" for i in range(MAX_CLASSES + 10)]
        with patch.object(TextEmbeddingManager, "_generate_embeddings", staticmethod(_fake_embeddings)):
            mgr = TextEmbeddingManager(
                prompts="cat",
                embeddings_file=str(tmp_path / "embeds.json"),
            )
            mgr.update_prompts(big_list)
        assert mgr.get_num_classes() == MAX_CLASSES


class TestDefaultPromptsExist:
    def test_default_prompts_file_loads_as_list(self):
        """default_prompts.json must exist and be a list of strings."""
        path = (
            Path(__file__).resolve().parents[1] / "default_prompts.json"
        )
        assert path.exists(), f"Missing {path}"
        data = json.loads(path.read_text())
        assert isinstance(data, list)
        assert all(isinstance(p, str) for p in data)
        # COCO-80
        assert 1 <= len(data) <= MAX_CLASSES
