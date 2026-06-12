"""Tests for VampireEngine — safe-entry logic and auto-alternation."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from vampire_engine import TrackState, VampireEngine


class TestNewTrackInBufferZone:
    """Tests for tracks with face recognition (auto_alternate=False)."""

    def test_vampire_identified_in_buffer(self):
        """face_match provided outside mirror → VAMPIRE."""
        engine = VampireEngine(auto_alternate=False)
        result = engine.decide(track_id=1, in_mirror=False,
                               face_match=("dracula", 0.9),
                               face_detected=True)
        assert result == TrackState.VAMPIRE

    def test_no_match_stays_pending(self):
        """No face detected, no match, outside mirror → PENDING."""
        engine = VampireEngine(auto_alternate=False)
        result = engine.decide(track_id=1, in_mirror=False,
                               face_match=None,
                               face_detected=False)
        assert result == TrackState.PENDING

    def test_face_detected_not_vampire(self):
        """Face detected but no vampire match → HUMAN."""
        engine = VampireEngine(auto_alternate=False)
        result = engine.decide(track_id=1, in_mirror=False,
                               face_match=None,
                               face_detected=True)
        assert result == TrackState.HUMAN


class TestSafeEntry:
    """Tests for the safe-entry rule (auto_alternate=False)."""

    def test_pending_enters_mirror_becomes_human(self):
        """Track pending outside mirror, then enters mirror → HUMAN."""
        engine = VampireEngine(auto_alternate=False)
        state1 = engine.decide(track_id=1, in_mirror=False,
                               face_match=None, face_detected=False)
        assert state1 == TrackState.PENDING

        state2 = engine.decide(track_id=1, in_mirror=True,
                               face_match=None, face_detected=False)
        assert state2 == TrackState.HUMAN

    def test_safe_entry_is_permanent(self):
        """After safe entry, even a vampire face_match cannot change to VAMPIRE."""
        engine = VampireEngine(auto_alternate=False)
        engine.decide(track_id=1, in_mirror=False,
                      face_match=None, face_detected=False)
        engine.decide(track_id=1, in_mirror=True,
                      face_match=None, face_detected=False)

        state = engine.decide(track_id=1, in_mirror=True,
                              face_match=("dracula", 0.95),
                              face_detected=True)
        assert state == TrackState.HUMAN


class TestCachedDecisions:
    """Tests that finalized states are cached and never change."""

    def test_vampire_stays_vampire(self):
        """Once VAMPIRE, all subsequent calls return VAMPIRE."""
        engine = VampireEngine(auto_alternate=False)
        engine.decide(track_id=1, in_mirror=False,
                      face_match=("dracula", 0.9), face_detected=True)

        state = engine.decide(track_id=1, in_mirror=True,
                              face_match=None, face_detected=False)
        assert state == TrackState.VAMPIRE

    def test_human_stays_human(self):
        """Once HUMAN (via safe entry), all subsequent calls return HUMAN."""
        engine = VampireEngine(auto_alternate=False)
        engine.decide(track_id=1, in_mirror=False,
                      face_match=None, face_detected=False)
        engine.decide(track_id=1, in_mirror=True,
                      face_match=None, face_detected=False)

        state = engine.decide(track_id=1, in_mirror=False,
                              face_match=None, face_detected=False)
        assert state == TrackState.HUMAN


class TestTrackCleanup:
    """Tests for track removal."""

    def test_remove_lost_track(self):
        """After remove_track(), same ID is treated as new."""
        engine = VampireEngine(auto_alternate=False)
        engine.decide(track_id=1, in_mirror=False,
                      face_match=("dracula", 0.9), face_detected=True)
        assert engine.get_state(1) == TrackState.VAMPIRE

        engine.remove_track(1)

        state = engine.decide(track_id=1, in_mirror=False,
                              face_match=None, face_detected=False)
        assert state == TrackState.PENDING


class TestVampireIds:
    """Tests for the vampire_ids property."""

    def test_vampire_ids_property(self):
        engine = VampireEngine(auto_alternate=False)
        engine.decide(track_id=1, in_mirror=False,
                      face_match=("dracula", 0.9), face_detected=True)
        engine.decide(track_id=2, in_mirror=False,
                      face_match=None, face_detected=False)
        engine.decide(track_id=2, in_mirror=True,
                      face_match=None, face_detected=False)

        assert engine.vampire_ids == {1}


class TestAutoAlternate:
    """Tests for auto_alternate mode (default, no face recognition)."""

    def test_first_track_is_human(self):
        engine = VampireEngine(auto_alternate=True)
        result = engine.decide(track_id=10, in_mirror=False,
                               face_match=None, face_detected=False)
        assert result == TrackState.HUMAN

    def test_second_track_is_vampire(self):
        engine = VampireEngine(auto_alternate=True)
        engine.decide(track_id=10, in_mirror=False,
                      face_match=None, face_detected=False)
        result = engine.decide(track_id=20, in_mirror=False,
                               face_match=None, face_detected=False)
        assert result == TrackState.VAMPIRE

    def test_alternation_pattern(self):
        """Tracks arrive in order → H, V, H, V, ..."""
        engine = VampireEngine(auto_alternate=True)
        results = []
        for tid in [1, 2, 3, 4, 5]:
            results.append(engine.decide(track_id=tid, in_mirror=False,
                                         face_match=None, face_detected=False))
        assert results == [
            TrackState.HUMAN, TrackState.VAMPIRE,
            TrackState.HUMAN, TrackState.VAMPIRE,
            TrackState.HUMAN,
        ]

    def test_auto_alternate_is_permanent(self):
        """Once auto-assigned, state doesn't change on subsequent calls."""
        engine = VampireEngine(auto_alternate=True)
        engine.decide(track_id=1, in_mirror=False,
                      face_match=None, face_detected=False)  # HUMAN
        engine.decide(track_id=2, in_mirror=False,
                      face_match=None, face_detected=False)  # VAMPIRE

        # Repeated calls return same state
        assert engine.decide(track_id=1, in_mirror=True,
                             face_match=None, face_detected=False) == TrackState.HUMAN
        assert engine.decide(track_id=2, in_mirror=True,
                             face_match=None, face_detected=False) == TrackState.VAMPIRE

    def test_face_match_overrides_auto(self):
        """face_match takes priority over auto-alternation."""
        engine = VampireEngine(auto_alternate=True)
        # First track would be HUMAN by auto, but face_match says VAMPIRE
        result = engine.decide(track_id=1, in_mirror=False,
                               face_match=("dracula", 0.9), face_detected=True)
        assert result == TrackState.VAMPIRE

    def test_default_is_auto_alternate(self):
        """VampireEngine() defaults to auto_alternate=True."""
        engine = VampireEngine()
        r1 = engine.decide(track_id=1, in_mirror=False,
                           face_match=None, face_detected=False)
        r2 = engine.decide(track_id=2, in_mirror=False,
                           face_match=None, face_detected=False)
        assert r1 == TrackState.HUMAN
        assert r2 == TrackState.VAMPIRE
