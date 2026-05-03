"""Sanity check: prove the ReID gallery coherence gate catches a swapped gallery.

The integration test ``test_2_persons_diagonal_keeps_initial_target`` asserts
that the dumped ReID gallery is internally coherent — pairwise cosine
similarity stays above ``REID_PAIR_MIN`` / ``REID_PAIR_MEAN``. The whole point
of that gate is to detect a tracker swap that would have silently injected the
wrong person's embedding into the gallery.

This file proves the gate would actually fail on that failure mode without
needing a 60 s sim run. We synthesize:

- a "clean" gallery: 15 embeddings from a single ReID-style cluster
  (mimicking one person across pose changes)
- a "swapped" gallery: 12 from cluster A then 3 from cluster B
  (the imprint of a brief swap during the diagonal cross — bigger persons
  bias the auto-select toward whichever was largest in frame at the moment)

Same gate, same code path. Clean must pass; swapped must fail. If someone
weakens the thresholds in test_sim_worlds.py to silence a flake, this test
breaks too.
"""

import numpy as np

from drone_follow.tests._reid_gate import REID_PAIR_MEAN, REID_PAIR_MIN


def _normalize(x):
    return x / np.linalg.norm(x, axis=-1, keepdims=True)


def _sample_cluster(rng, anchor, n, scatter):
    """N L2-normalized vectors close to ``anchor``."""
    perturb = rng.normal(size=(n, anchor.size))
    return _normalize(anchor[None, :] + scatter * perturb)


def _pair_stats(embs):
    """Min / mean pairwise cosine similarity over the upper triangle."""
    sim = embs @ embs.T
    iu = np.triu_indices(embs.shape[0], k=1)
    pairs = sim[iu]
    return float(pairs.min()), float(pairs.mean())


def test_clean_synthetic_gallery_passes_gate():
    """Single-cluster gallery (one person) should pass the integration test's gate."""
    rng = np.random.default_rng(seed=42)
    anchor = _normalize(rng.normal(size=512))
    embs = _sample_cluster(rng, anchor, n=15, scatter=0.02)

    min_sim, mean_sim = _pair_stats(embs)

    assert min_sim >= REID_PAIR_MIN, (
        f"clean single-person synthetic gallery should clear min gate "
        f"(>= {REID_PAIR_MIN}) but got {min_sim:.3f} — synthetic clusters "
        f"are too noisy or thresholds drifted"
    )
    assert mean_sim >= REID_PAIR_MEAN, (
        f"clean single-person synthetic gallery should clear mean gate "
        f"(>= {REID_PAIR_MEAN}) but got {mean_sim:.3f}"
    )


def test_swapped_synthetic_gallery_fails_gate():
    """Two-cluster gallery (tracker swap) should fail the integration test's gate.

    This is the proof that ``test_2_persons_diagonal_keeps_initial_target``'s
    assertions actually catch the failure mode they claim to. If this test
    ever passes, the gate is too loose and an incoherent gallery would slip
    through silently.
    """
    rng = np.random.default_rng(seed=42)
    anchor_a = _normalize(rng.normal(size=512))
    # Force cluster B to be near-orthogonal to A so cross-cluster sims sit
    # near zero — this is what real ReID embeddings of two different people
    # look like in practice (typically 0.2–0.4, sometimes lower).
    anchor_b = _normalize(rng.normal(size=512))
    embs = np.vstack([
        _sample_cluster(rng, anchor_a, n=12, scatter=0.02),
        _sample_cluster(rng, anchor_b, n=3, scatter=0.02),
    ])

    min_sim, mean_sim = _pair_stats(embs)

    assert min_sim < REID_PAIR_MIN or mean_sim < REID_PAIR_MEAN, (
        f"swapped two-person synthetic gallery slipped through the coherence "
        f"gate (min={min_sim:.3f}, mean={mean_sim:.3f}) — the integration "
        f"test would not catch a real ReID swap. Tighten "
        f"REID_PAIR_MIN/REID_PAIR_MEAN in test_sim_worlds.py."
    )
