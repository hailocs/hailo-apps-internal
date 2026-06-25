"""Schema tests for hotdog_not_hotdog cached embeddings.

The pipeline at startup reads embeddings.json and verifies the cached
prompts match the expected list. If the file is corrupted or the prompt
list changes, the pipeline regenerates them (slow, requires CLIP text
encoder on Hailo). These tests catch schema drift early.
"""

import json
from pathlib import Path

import pytest


EXPECTED_PROMPTS = ["hotdog", "food", "person", "animal", "object", "room"]
EMBEDDINGS_PATH = (
    Path(__file__).resolve().parents[1] / "embeddings.json"
)


@pytest.fixture(scope="module")
def embeddings_data():
    if not EMBEDDINGS_PATH.exists():
        pytest.skip(f"embeddings.json not present at {EMBEDDINGS_PATH}")
    return json.loads(EMBEDDINGS_PATH.read_text())


class TestEmbeddingsSchema:
    def test_top_level_keys(self, embeddings_data):
        assert "threshold" in embeddings_data
        assert "entries" in embeddings_data

    def test_prompts_match_pipeline_default(self, embeddings_data):
        texts = [e["text"] for e in embeddings_data["entries"]]
        assert texts == EXPECTED_PROMPTS

    def test_every_entry_has_embedding(self, embeddings_data):
        for entry in embeddings_data["entries"]:
            assert "text" in entry
            assert "embedding" in entry
            assert isinstance(entry["embedding"], list)
            assert len(entry["embedding"]) > 0
            assert all(isinstance(v, (int, float)) for v in entry["embedding"])

    def test_all_embeddings_same_dimension(self, embeddings_data):
        dims = {len(e["embedding"]) for e in embeddings_data["entries"]}
        assert len(dims) == 1, f"inconsistent embedding dimensions: {dims}"

    def test_threshold_in_unit_range(self, embeddings_data):
        threshold = embeddings_data["threshold"]
        assert 0.0 <= threshold <= 1.0

    def test_hotdog_is_first_prompt(self, embeddings_data):
        # The verdict logic matches on the label name ("hotdog"), not on entry
        # order, so this is a sanity check that the hotdog prompt is still
        # present and conventionally listed first.
        assert embeddings_data["entries"][0]["text"] == "hotdog"
