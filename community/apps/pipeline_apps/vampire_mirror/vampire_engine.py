"""VampireEngine — decides whether a tracked person is a vampire, human, or pending.

Safe-entry rule: if a person enters the visible mirror area while still PENDING
(before being identified as a vampire), they are permanently marked HUMAN to
prevent sudden disappearance from the mirror when identification later happens.

Once a track is finalized (VAMPIRE or HUMAN) the state never changes.
"""
from enum import Enum


class TrackState(Enum):
    PENDING = "pending"
    VAMPIRE = "vampire"
    HUMAN = "human"


class VampireEngine:
    """Manages per-track vampire/human/pending state with safe-entry logic."""

    def __init__(self):
        self._states: dict[int, TrackState] = {}

    def decide(
        self,
        track_id: int,
        in_mirror: bool,
        face_match: tuple[str, float] | None,
        face_detected: bool = False,
    ) -> TrackState:
        """Return the current TrackState for *track_id*, updating it as needed.

        Rules (evaluated in order):
        1. If already finalized (VAMPIRE or HUMAN) → return cached state.
        2. If face_match is not None → VAMPIRE (confirmed vampire face).
        3. If face_detected but no match → HUMAN (known non-vampire face).
        4. If in_mirror while still PENDING → HUMAN (safe-entry rule).
        5. Otherwise → remain PENDING.
        """
        current = self._states.get(track_id, TrackState.PENDING)

        # Rule 1: finalized states are permanent
        if current != TrackState.PENDING:
            return current

        # Rule 2: vampire face matched
        if face_match is not None:
            self._states[track_id] = TrackState.VAMPIRE
            return TrackState.VAMPIRE

        # Rule 3: face detected, no vampire match → human
        if face_detected:
            self._states[track_id] = TrackState.HUMAN
            return TrackState.HUMAN

        # Rule 4: safe-entry — entered mirror without being flagged as vampire
        if in_mirror:
            self._states[track_id] = TrackState.HUMAN
            return TrackState.HUMAN

        # Rule 5: not enough information yet
        self._states[track_id] = TrackState.PENDING
        return TrackState.PENDING

    def get_state(self, track_id: int) -> TrackState:
        """Return the current state for *track_id* (PENDING if unknown)."""
        return self._states.get(track_id, TrackState.PENDING)

    def remove_track(self, track_id: int) -> None:
        """Remove all state for *track_id* so it is treated as new next time."""
        self._states.pop(track_id, None)

    @property
    def vampire_ids(self) -> set[int]:
        """Return the set of track IDs currently classified as VAMPIRE."""
        return {tid for tid, state in self._states.items()
                if state == TrackState.VAMPIRE}
