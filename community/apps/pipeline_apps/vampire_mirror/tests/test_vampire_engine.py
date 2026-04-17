"""Tests for VampireEngine — safe-entry logic."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from vampire_engine import TrackState, VampireEngine


class TestNewTrackInBufferZone:
    """Tests for tracks that are outside the mirror area (buffer zone)."""

    def test_vampire_identified_in_buffer(self):
        """face_match provided outside mirror → VAMPIRE."""
        engine = VampireEngine()
        result = engine.decide(track_id=1, in_mirror=False,
                               face_match=("dracula", 0.9),
                               face_detected=True)
        assert result == TrackState.VAMPIRE

    def test_no_match_stays_pending(self):
        """No face detected, no match, outside mirror → PENDING."""
        engine = VampireEngine()
        result = engine.decide(track_id=1, in_mirror=False,
                               face_match=None,
                               face_detected=False)
        assert result == TrackState.PENDING

    def test_face_detected_not_vampire(self):
        """Face detected but no vampire match → HUMAN."""
        engine = VampireEngine()
        result = engine.decide(track_id=1, in_mirror=False,
                               face_match=None,
                               face_detected=True)
        assert result == TrackState.HUMAN


class TestSafeEntry:
    """Tests for the safe-entry rule."""

    def test_pending_enters_mirror_becomes_human(self):
        """Track pending outside mirror, then enters mirror → HUMAN."""
        engine = VampireEngine()
        # First call: outside mirror, no info → PENDING
        state1 = engine.decide(track_id=1, in_mirror=False,
                               face_match=None, face_detected=False)
        assert state1 == TrackState.PENDING

        # Second call: enters mirror still pending → safe entry → HUMAN
        state2 = engine.decide(track_id=1, in_mirror=True,
                               face_match=None, face_detected=False)
        assert state2 == TrackState.HUMAN

    def test_safe_entry_is_permanent(self):
        """After safe entry, even a vampire face_match cannot change to VAMPIRE."""
        engine = VampireEngine()
        # Trigger safe entry
        engine.decide(track_id=1, in_mirror=False,
                      face_match=None, face_detected=False)
        engine.decide(track_id=1, in_mirror=True,
                      face_match=None, face_detected=False)

        # Now try to match as vampire
        state = engine.decide(track_id=1, in_mirror=True,
                              face_match=("dracula", 0.95),
                              face_detected=True)
        assert state == TrackState.HUMAN


class TestCachedDecisions:
    """Tests that finalized states are cached and never change."""

    def test_vampire_stays_vampire(self):
        """Once VAMPIRE, all subsequent calls return VAMPIRE."""
        engine = VampireEngine()
        engine.decide(track_id=1, in_mirror=False,
                      face_match=("dracula", 0.9), face_detected=True)

        # Call again with no match, even entering mirror
        state = engine.decide(track_id=1, in_mirror=True,
                              face_match=None, face_detected=False)
        assert state == TrackState.VAMPIRE

    def test_human_stays_human(self):
        """Once HUMAN (via safe entry), all subsequent calls return HUMAN."""
        engine = VampireEngine()
        # Force safe entry
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
        """After remove_track(), same ID is treated as new (PENDING)."""
        engine = VampireEngine()
        engine.decide(track_id=1, in_mirror=False,
                      face_match=("dracula", 0.9), face_detected=True)
        assert engine.get_state(1) == TrackState.VAMPIRE

        engine.remove_track(1)

        # Should start fresh as PENDING (no face info)
        state = engine.decide(track_id=1, in_mirror=False,
                              face_match=None, face_detected=False)
        assert state == TrackState.PENDING


class TestVampireIds:
    """Tests for the vampire_ids property."""

    def test_vampire_ids_property(self):
        """After marking track 1 as vampire and track 2 as human, vampire_ids == {1}."""
        engine = VampireEngine()
        # Track 1 → VAMPIRE
        engine.decide(track_id=1, in_mirror=False,
                      face_match=("dracula", 0.9), face_detected=True)
        # Track 2 → HUMAN (safe entry)
        engine.decide(track_id=2, in_mirror=False,
                      face_match=None, face_detected=False)
        engine.decide(track_id=2, in_mirror=True,
                      face_match=None, face_detected=False)

        assert engine.vampire_ids == {1}
