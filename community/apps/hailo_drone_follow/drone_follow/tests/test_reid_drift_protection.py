"""Drift-protection logic in ReIDManager.update_gallery().

The strategy under test rejects in-track embeddings that are too dissimilar
from the existing gallery (likely tracker drift) and skips near-duplicates
(periodic refresh keeps the gallery from going stale). Drift-rejection
triggers an immediate re-acquisition pass over the visible detections.

Tests inject a fake extractor onto an otherwise real ReIDManager so we
exercise the full decision logic without Hailo NPU calls.
"""

import numpy as np
import pytest

from drone_follow.pipeline_adapter.reid_manager import (
    ACTION_ADDED,
    ACTION_BOOTSTRAP,
    ACTION_NOOP,
    ACTION_REFRESHED,
    ACTION_SKIPPED_DRIFT,
    ACTION_SKIPPED_DUPLICATE,
    ReIDManager,
)
from reid_analysis.gallery_strategies import MultiEmbeddingStrategy


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

class _FakeExtractor:
    """Yields pre-canned unit vectors instead of running Hailo inference."""

    def __init__(self, vecs, raise_on_call=False):
        self._iter = iter(vecs)
        self._raise = raise_on_call
        self.embedding_dim = 8
        self.model_name = "fake"

    def extract_embedding(self, crop):
        if self._raise:
            raise RuntimeError("fake extractor failure")
        return next(self._iter)

    def extract_embeddings_batch(self, crops):
        if self._raise:
            raise RuntimeError("fake extractor failure")
        return [next(self._iter) for _ in crops]

    def release(self):
        pass


class _FakeBBox:
    """Stand-in for hailo_apps' bbox used by _crop_person."""

    def __init__(self, x=0.4, y=0.4, w=0.2, h=0.4):
        self._x, self._y, self._w, self._h = x, y, w, h

    def xmin(self):
        return self._x

    def ymin(self):
        return self._y

    def width(self):
        return self._w

    def height(self):
        return self._h


class _FakePerson:
    def __init__(self, bbox):
        self._bbox = bbox

    def get_bbox(self):
        return self._bbox


def _unit(*components):
    """Return a unit vector with the given prefix, padded out to 8-D."""
    v = np.zeros(8, dtype=np.float32)
    for i, c in enumerate(components):
        v[i] = float(c)
    n = np.linalg.norm(v)
    return v / n if n > 0 else v


def _frame():
    """Plausible 80x80 BGR frame so _crop_person yields a non-empty slice."""
    return np.full((80, 80, 3), 128, dtype=np.uint8)


def _make_manager(vecs, *, raise_on_call=False, drift_threshold=0.6,
                  duplicate_threshold=0.9, refresh_every=5,
                  min_gallery_for_drift_check=2,
                  reid_match_threshold=0.7):
    """Build a ReIDManager with extractor stubbed out (no Hailo init)."""
    mgr = ReIDManager(
        hef_path="/dev/null",
        update_interval=30,
        max_gallery_size=10,
        reid_match_threshold=reid_match_threshold,
        drift_threshold=drift_threshold,
        duplicate_threshold=duplicate_threshold,
        refresh_every=refresh_every,
        min_gallery_for_drift_check=min_gallery_for_drift_check,
    )
    mgr._extractor = _FakeExtractor(vecs, raise_on_call=raise_on_call)
    mgr._tracking_id = 1
    mgr._original_id = 1
    return mgr


# ---------------------------------------------------------------------------
# MultiEmbeddingStrategy helpers
# ---------------------------------------------------------------------------

def test_max_similarity_empty():
    g = MultiEmbeddingStrategy(max_k=5)
    assert g.max_similarity("absent", _unit(1)) == -1.0


def test_max_similarity_identical_and_orthogonal():
    g = MultiEmbeddingStrategy(max_k=5)
    g.add_person("a", _unit(1))
    g.update("a", _unit(0, 1), frame_count=1)
    assert pytest.approx(g.max_similarity("a", _unit(1)), abs=1e-6) == 1.0
    assert pytest.approx(g.max_similarity("a", _unit(0, 0, 1)), abs=1e-6) == 0.0


def test_replace_oldest_rotates_fifo():
    g = MultiEmbeddingStrategy(max_k=3)
    g.add_person("a", _unit(1))
    g.update("a", _unit(0, 1), frame_count=1)
    g.update("a", _unit(0, 0, 1), frame_count=2)
    assert g.embedding_count("a") == 3
    g.replace_oldest("a", _unit(0, 0, 0, 1))
    embs = np.stack(g._person_embeddings["a"])
    # Oldest (unit(1)) should be gone; newest (unit at index 3) present.
    assert embs.shape == (3, 8)
    assert pytest.approx(embs[-1] @ _unit(0, 0, 0, 1), abs=1e-6) == 1.0
    assert all(e @ _unit(1) < 0.5 for e in embs)


# ---------------------------------------------------------------------------
# update_gallery decision branches
# ---------------------------------------------------------------------------

def test_bootstrap_path_stores_first_embedding():
    mgr = _make_manager([_unit(1)])
    result = mgr.update_gallery(_frame(), _FakeBBox(), 80, 80, person_by_id={})
    assert result.action == ACTION_BOOTSTRAP
    assert result.gallery_size == 1
    assert mgr.has_gallery


def test_add_path_in_middle_band():
    # unit(1,1) vs unit(1) ≈ 0.707, vs unit(1,0,1) ≈ 0.707 — both in the
    # middle band for default thresholds (0.5 < sim < 0.9), so add.
    mgr = _make_manager([_unit(1, 1)])
    mgr._gallery.add_person("1", _unit(1))
    mgr._gallery.update("1", _unit(1, 0, 1), frame_count=1)

    result = mgr.update_gallery(_frame(), _FakeBBox(), 80, 80, person_by_id={})
    assert result.action == ACTION_ADDED
    assert result.gallery_size == 3
    assert 0.6 < result.similarity < 0.8


def test_skip_duplicate_path_increments_streak():
    mgr = _make_manager([_unit(1)])
    mgr._gallery.add_person("1", _unit(1))
    mgr._gallery.update("1", _unit(0, 1), frame_count=1)

    result = mgr.update_gallery(_frame(), _FakeBBox(), 80, 80, person_by_id={})
    assert result.action == ACTION_SKIPPED_DUPLICATE
    assert result.gallery_size == 2  # unchanged
    assert mgr._duplicate_streak == 1


def test_refresh_after_n_consecutive_duplicates():
    refresh_every = 3
    # Feed `refresh_every` duplicate vectors (all unit(1)).
    vecs = [_unit(1) for _ in range(refresh_every)]
    mgr = _make_manager(vecs, refresh_every=refresh_every)
    mgr._gallery.add_person("1", _unit(1))
    mgr._gallery.update("1", _unit(0, 1), frame_count=1)
    size_before = mgr._gallery.embedding_count("1")

    actions = []
    for _ in range(refresh_every):
        actions.append(mgr.update_gallery(
            _frame(), _FakeBBox(), 80, 80, person_by_id={}).action)

    assert actions[:-1] == [ACTION_SKIPPED_DUPLICATE] * (refresh_every - 1)
    assert actions[-1] == ACTION_REFRESHED
    assert mgr._gallery.embedding_count("1") == size_before  # size unchanged
    assert mgr._duplicate_streak == 0  # reset after refresh


def test_drift_path_no_visible_persons():
    # candidate orthogonal to seeded gallery → sim = 0 < drift_threshold.
    mgr = _make_manager([_unit(0, 0, 0, 1)])
    mgr._gallery.add_person("1", _unit(1))
    mgr._gallery.update("1", _unit(0, 1), frame_count=1)

    result = mgr.update_gallery(_frame(), _FakeBBox(), 80, 80, person_by_id={})
    assert result.action == ACTION_SKIPPED_DRIFT
    assert result.reacquired_track_id is None
    # Empty person_by_id ⇒ reacquire was not attempted.
    assert result.reacquire_attempted is False
    assert mgr._gallery.embedding_count("1") == 2  # unchanged


def test_drift_path_reacquires_to_different_id():
    # Sequence: in-track extract (drift vector) → batch with [drift, gallery-match].
    drift = _unit(0, 0, 0, 1)
    match = _unit(1)
    mgr = _make_manager([drift, drift, match])  # update_gallery, then batch x 2
    mgr._gallery.add_person("1", _unit(1))
    mgr._gallery.update("1", _unit(0.99, 0.14), frame_count=1)  # close to unit(1)

    persons = {7: _FakePerson(_FakeBBox()), 9: _FakePerson(_FakeBBox())}
    result = mgr.update_gallery(_frame(), _FakeBBox(), 80, 80, person_by_id=persons)

    assert result.action == ACTION_SKIPPED_DRIFT
    assert result.reacquire_attempted is True
    assert result.reacquired_track_id == 9  # the one whose batch vector matched
    # Embedding NOT stored.
    assert mgr._gallery.embedding_count("1") == 2


def test_drift_path_false_drift_same_id():
    # Reacquire returns the same track id we already hold ⇒ false drift.
    drift = _unit(0, 0, 0, 1)
    match = _unit(1)
    mgr = _make_manager([drift, match])  # update + batch (single person)
    mgr._gallery.add_person("1", _unit(1))
    mgr._gallery.update("1", _unit(0.99, 0.14), frame_count=1)

    persons = {1: _FakePerson(_FakeBBox())}  # only the currently-tracked id visible
    mgr._tracking_id = 1
    result = mgr.update_gallery(_frame(), _FakeBBox(), 80, 80, person_by_id=persons)

    assert result.action == ACTION_SKIPPED_DRIFT
    assert result.reacquired_track_id == 1
    # Still NOT stored — the user's spec says vectors unlike anything in the
    # gallery don't get added even if reID confirms.
    assert mgr._gallery.embedding_count("1") == 2


def test_min_gallery_guard_appends_below_threshold():
    # Gallery has only 1 vector and min_gallery_for_drift_check=2 → no drift check.
    mgr = _make_manager([_unit(0, 0, 0, 1)], min_gallery_for_drift_check=2)
    mgr._gallery.add_person("1", _unit(1))

    result = mgr.update_gallery(_frame(), _FakeBBox(), 80, 80, person_by_id={})
    assert result.action == ACTION_ADDED
    assert mgr._gallery.embedding_count("1") == 2


def test_extraction_failure_returns_noop():
    mgr = _make_manager([], raise_on_call=True)
    mgr._gallery.add_person("1", _unit(1))

    result = mgr.update_gallery(_frame(), _FakeBBox(), 80, 80, person_by_id={})
    assert result.action == ACTION_NOOP
    assert result.gallery_size == 1  # unchanged


def test_new_target_resets_streak():
    mgr = _make_manager([_unit(1)])
    mgr._gallery.add_person("1", _unit(1))
    mgr._duplicate_streak = 3

    mgr.on_target_selected(42)
    assert mgr._duplicate_streak == 0
    assert mgr._tracking_id == 42
    assert mgr._original_id == 42
    assert not mgr.has_gallery
