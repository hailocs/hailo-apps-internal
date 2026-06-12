"""Unit tests for PromptSuggester.nearest (fake encoder — no CLIP weights)."""

import numpy as np

from hailo_apps.python.pipeline_apps.yolo_world.prompt_suggester import PromptSuggester


class FakeEncoder:
    """Maps known phrases to fixed unit vectors so cosines are controllable."""
    VECS = {
        "potted plant": [1.0, 0.0, 0.0],
        "houseplant":   [0.95, 0.31, 0.0],   # close to potted plant
        "plant":        [0.9, 0.44, 0.0],     # a bit further
        "person":       [0.0, 0.0, 1.0],      # orthogonal
    }

    def encode_prompts(self, prompts):
        out = []
        for p in prompts:
            v = np.array(self.VECS.get(p, [0.0, 1.0, 0.0]), dtype=np.float32)
            v = v / (np.linalg.norm(v) + 1e-9)
            out.append(v)
        return np.stack(out).astype(np.float32)


def _suggester():
    return PromptSuggester(FakeEncoder(), vocabulary=list(FakeEncoder.VECS.keys()))


def test_nearest_returns_close_synonyms_not_self():
    s = _suggester()
    out = s.nearest("potted plant", k=4, min_sim=0.5)
    labels = [lbl for lbl, _ in out]
    assert "potted plant" not in labels          # excludes the word itself
    assert labels[0] == "houseplant"             # closest synonym first
    assert "plant" in labels


def test_orthogonal_label_excluded_by_min_sim():
    s = _suggester()
    out = s.nearest("potted plant", k=4, min_sim=0.5)
    assert "person" not in [lbl for lbl, _ in out]   # cosine 0 < min_sim


def test_sorted_by_descending_similarity():
    s = _suggester()
    out = s.nearest("potted plant", k=4, min_sim=0.0)
    sims = [sim for _, sim in out]
    assert sims == sorted(sims, reverse=True)


def test_k_limit():
    s = _suggester()
    assert len(s.nearest("potted plant", k=1, min_sim=0.0)) == 1
