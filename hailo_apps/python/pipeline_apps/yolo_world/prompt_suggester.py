""""Did you mean…" prompt suggestions for YOLO World.

Uses the CLIP text encoder to find vocabulary labels semantically close to a
user's prompt — useful when an out-of-distribution phrasing detects poorly and
a near-synonym ("potted plant" → "houseplant") works far better.

Two layers:
  - `nearest()` — pure CLIP text-cosine neighbours from a known-good vocabulary.
    Cheap (vocab embeddings precomputed once), good for live "did you mean" hints.
  - `rank_by_detection()` — re-rank candidates by how strongly they ACTUALLY
    detect on a set of frames. Text similarity alone can rank a dead prompt
    highly (e.g. "flower pot"); this grounds suggestions in real detector output.
"""
import json
from pathlib import Path

import numpy as np

from hailo_apps.python.core.common.hailo_logger import get_logger

logger = get_logger(__name__)

DEFAULT_VOCAB_PATH = Path(__file__).parent / "known_vocabulary.json"


class PromptSuggester:
    def __init__(self, encoder, vocabulary=None):
        """encoder: NumpyClipTextEncoder; vocabulary: list[str] or None (load default)."""
        if vocabulary is None:
            vocabulary = json.loads(DEFAULT_VOCAB_PATH.read_text())
        # de-dupe, preserve order
        self.vocab = list(dict.fromkeys(v.strip() for v in vocabulary if v.strip()))
        self._encoder = encoder
        self._emb = encoder.encode_prompts(self.vocab)   # (V, 512), L2-normalized

    def nearest(self, prompt, k=4, min_sim=0.80, same_word_sim=0.995):
        """Top-k vocabulary labels closest to `prompt` by CLIP cosine.

        Excludes labels essentially identical to the prompt (cosine >= same_word_sim)
        so we suggest alternatives, not the word itself.
        """
        q = self._encoder.encode_prompts([prompt])[0]
        sims = self._emb @ q
        out = []
        for i in np.argsort(-sims):
            s = float(sims[i])
            if s >= same_word_sim:          # the prompt itself / a trivial restatement
                continue
            if s < min_sim:
                break
            out.append((self.vocab[i], s))
            if len(out) >= k:
                break
        return out

    def rank_by_detection(self, prompt, frames, engine, engine_lock, restore_embeddings,
                          k=3, min_sim=0.80):
        """Generate candidates near `prompt`, then rank by real detection strength.

        Reuses the live detector `engine` (swapping its text embeddings per
        candidate) under `engine_lock`, because this hardware allows only one
        VDevice. The lock briefly blocks the live callback during the probe;
        `restore_embeddings` (the user's current (1,80,512) tensor) is put back
        afterward so live detection continues unchanged.

        Returns list of {label, text_sim, peak, mean} sorted by peak desc,
        including the user's own prompt for comparison.
        """
        neighbors = self.nearest(prompt, k=k, min_sim=min_sim)
        candidates = [prompt] + [lbl for lbl, _ in neighbors]
        text_sim = {prompt: 1.0}
        text_sim.update({lbl: s for lbl, s in neighbors})

        def padded(label):
            p = np.zeros((1, 80, 512), dtype=np.float32)
            p[0, 0] = self._encoder.encode_prompts([label])[0]
            return p

        results = []
        with engine_lock:
            try:
                for lbl in candidates:
                    engine.update_text_embeddings(padded(lbl))
                    peak = total = 0.0
                    for fr in frames:
                        outs = engine.run(fr)
                        fmax = 0.0
                        for t in outs.values():
                            t = t[0] if t.ndim == 4 else t
                            if t.shape[-1] == 80:
                                fmax = max(fmax, float(t[:, :, 0].max()))
                        peak = max(peak, fmax)
                        total += fmax
                    results.append({
                        "label": lbl,
                        "text_sim": round(text_sim.get(lbl, 0.0), 3),
                        "peak": round(peak, 3),
                        "mean": round(total / max(1, len(frames)), 3),
                    })
            finally:
                engine.update_text_embeddings(restore_embeddings)  # restore live prompts
        results.sort(key=lambda r: -r["peak"])
        return results
