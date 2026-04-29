"""Tests for `_dispatch_sot_or_mot` — the SOT/MOT dispatch helper.

Verifies the post-merge fix where MOT runs every frame so the operator sees
every visible track ID (including in SOT mode), and SOT only fires as a
fallback when MOT lost the locked target.
"""

import numpy as np

from drone_follow.pipeline_adapter.hailo_drone_detection_manager import (
    _dispatch_sot_or_mot,
)


# A minimal stand-in for a HailoDetection — only identity matters for the
# dispatch logic; bbox/confidence are irrelevant since the run_tracker /
# run_sot callables are stubbed.
class _FakePerson:
    def __init__(self, label):
        self.label = label

    def __repr__(self):
        return f"<P {self.label}>"


def _attach_noop(_person, _tid):
    """Attach hook used in tests — mutation-free; just records calls."""


def _make_run_tracker(mot_map, filtered_tlwh_by_id=None):
    """Build a fake run_tracker that returns ids drawn from mot_map.

    mot_map: {track_id -> person} — what MOT will return for the given persons.
    available_ids covers every key in mot_map plus any "stale" IDs the caller
    wants to inject (we keep it simple here: == set(mot_map.keys())).
    filtered_tlwh_by_id: optional override; defaults to {} (no filtered bboxes).
    """
    filtered = dict(filtered_tlwh_by_id or {})

    def _run_tracker(persons):
        person_by_id = dict(mot_map)
        person_to_id = {id(p): tid for tid, p in person_by_id.items()}
        available_ids = set(person_by_id.keys())
        return available_ids, person_by_id, person_to_id, dict(filtered)
    return _run_tracker


def _make_run_sot(matched_person):
    """Build a fake run_sot that returns matched_person (or None for lost)."""
    def _run_sot(persons, last_bbox):
        if matched_person is None:
            return None, None
        return matched_person, np.zeros(4, dtype=np.float32)
    return _run_sot


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_no_target_runs_only_mot():
    """No locked target → just MOT; available_ids covers everyone."""
    p1, p2 = _FakePerson("a"), _FakePerson("b")
    mot_map = {1: p1, 2: p2}

    avail, by_id, to_id, filt, recovered = _dispatch_sot_or_mot(
        persons=[p1, p2],
        target_id=None,
        sot_enabled=True,
        sot_active=False,
        sot_last_bbox=None,
        sot_target_id=None,
        run_tracker=_make_run_tracker(mot_map),
        run_sot=_make_run_sot(matched_person=p1),  # SOT shouldn't even be tried
        attach_track_id=_attach_noop,
    )
    assert avail == {1, 2}
    assert by_id == {1: p1, 2: p2}
    assert to_id == {id(p1): 1, id(p2): 2}
    assert filt == {}
    assert recovered is False


def test_mot_keeps_target_lock_no_sot_fallback():
    """MOT still has the locked target → SOT must not run; all IDs visible."""
    p1, p2, p3 = _FakePerson("a"), _FakePerson("b"), _FakePerson("c")
    mot_map = {7: p1, 8: p2, 9: p3}

    sot_calls = []

    def _run_sot_recording(persons, last_bbox):
        sot_calls.append("called")
        return None, None

    avail, by_id, to_id, filt, recovered = _dispatch_sot_or_mot(
        persons=[p1, p2, p3],
        target_id=8,                  # MOT has 8
        sot_enabled=True,
        sot_active=True,              # SOT was active last frame
        sot_last_bbox=np.zeros(4, dtype=np.float32),
        sot_target_id=8,
        run_tracker=_make_run_tracker(mot_map),
        run_sot=_run_sot_recording,
        attach_track_id=_attach_noop,
    )
    # Critical: every visible person's ID is exposed, *not* just {target_id}.
    assert avail == {7, 8, 9}
    assert set(by_id.keys()) == {7, 8, 9}
    assert filt == {}
    # SOT must not have been called — MOT had the target.
    assert sot_calls == []
    assert recovered is False


def test_mot_lost_target_sot_recovers():
    """MOT lost the locked target → SOT recovers it AND keeps other IDs visible."""
    p_target, p_other = _FakePerson("target"), _FakePerson("other")
    # MOT only sees the other person (target_id 5 is missing).
    mot_map = {2: p_other}

    attached = []

    def _attach(person, tid):
        attached.append((person, tid))

    avail, by_id, to_id, filt, recovered = _dispatch_sot_or_mot(
        persons=[p_target, p_other],
        target_id=5,
        sot_enabled=True,
        sot_active=True,
        sot_last_bbox=np.zeros(4, dtype=np.float32),
        sot_target_id=5,
        run_tracker=_make_run_tracker(mot_map),
        run_sot=_make_run_sot(matched_person=p_target),
        attach_track_id=_attach,
    )
    # Both the SOT-recovered target *and* the MOT-tracked other person are visible.
    assert avail == {2, 5}
    assert by_id == {2: p_other, 5: p_target}
    assert to_id == {id(p_other): 2, id(p_target): 5}
    # SOT-recovered tracks deliberately don't get a filtered_tlwh — the SOT
    # path bypasses the Kalman filter, so 5 must not be in `filt`.
    assert 5 not in filt
    assert recovered is True
    # The recovered person had its track ID attached for downstream consumers.
    assert attached == [(p_target, 5)]


def test_mot_lost_target_sot_also_lost():
    """MOT lost the target AND SOT can't IOU-match → other IDs still visible."""
    p_other = _FakePerson("other")
    mot_map = {2: p_other}

    avail, by_id, to_id, filt, recovered = _dispatch_sot_or_mot(
        persons=[p_other],
        target_id=5,
        sot_enabled=True,
        sot_active=True,
        sot_last_bbox=np.zeros(4, dtype=np.float32),
        sot_target_id=5,
        run_tracker=_make_run_tracker(mot_map),
        run_sot=_make_run_sot(matched_person=None),
        attach_track_id=_attach_noop,
    )
    # SOT lost the target — only MOT-tracked persons remain, but they are visible.
    assert avail == {2}
    assert by_id == {2: p_other}
    assert filt == {}
    assert recovered is False


def test_sot_disabled_means_pure_mot():
    """sot_enabled=False → SOT is never consulted; MOT is the only source."""
    p1 = _FakePerson("a")
    mot_map = {1: p1}  # MOT has no record of target_id=99

    sot_calls = []

    def _run_sot_recording(persons, last_bbox):
        sot_calls.append("called")
        return None, None

    avail, by_id, to_id, filt, recovered = _dispatch_sot_or_mot(
        persons=[p1],
        target_id=99,
        sot_enabled=False,
        sot_active=False,
        sot_last_bbox=None,
        sot_target_id=None,
        run_tracker=_make_run_tracker(mot_map),
        run_sot=_run_sot_recording,
        attach_track_id=_attach_noop,
    )
    assert sot_calls == []
    assert avail == {1}
    assert filt == {}
    assert recovered is False


def test_sot_target_id_mismatch_skips_fallback():
    """If sot_target_id doesn't match current target_id, SOT must not fire.

    Guards against a stale sot_last_bbox from a previous lock.
    """
    p_other = _FakePerson("other")
    mot_map = {2: p_other}

    sot_calls = []

    def _run_sot_recording(persons, last_bbox):
        sot_calls.append("called")
        return None, None

    avail, by_id, to_id, filt, recovered = _dispatch_sot_or_mot(
        persons=[p_other],
        target_id=5,                       # operator wants 5
        sot_enabled=True,
        sot_active=True,
        sot_last_bbox=np.zeros(4, dtype=np.float32),
        sot_target_id=99,                  # but SOT bbox is for 99 — mismatch
        run_tracker=_make_run_tracker(mot_map),
        run_sot=_run_sot_recording,
        attach_track_id=_attach_noop,
    )
    assert sot_calls == []
    assert avail == {2}
    assert filt == {}
    assert recovered is False
