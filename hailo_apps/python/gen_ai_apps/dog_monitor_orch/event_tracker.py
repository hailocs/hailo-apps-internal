"""
Dog Monitor Event Tracker — classifies VLM responses into dog activity events.
"""

from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from hailo_apps.python.core.common.hailo_logger import get_logger

logger = get_logger(__name__)


class EventType(Enum):
    """Dog activity event types."""
    DRINKING = "drinking"
    EATING = "eating"
    SLEEPING = "sleeping"
    PLAYING = "playing"
    BARKING = "barking"
    AT_DOOR = "at_door"
    IDLE = "idle"
    NO_DOG = "no_dog"


@dataclass
class Event:
    """A single dog activity event."""
    timestamp: datetime
    event_type: EventType
    description: str
    frame_path: Optional[str] = None


# Keyword mapping for VLM response classification
_KEYWORD_MAP: dict[EventType, list[str]] = {
    EventType.DRINKING: ["drink", "water", "bowl"],
    EventType.EATING: ["eat", "food", "kibble", "chew"],
    EventType.SLEEPING: ["sleep", "rest", "nap", "lying", "lay"],
    EventType.PLAYING: ["play", "toy", "fetch", "run", "jump"],
    EventType.BARKING: ["bark", "alert", "growl", "whine"],
    EventType.AT_DOOR: ["door", "wait", "entrance", "exit"],
    EventType.NO_DOG: ["no dog", "empty", "not visible"],
}


class EventTracker:
    """Tracks and classifies dog activity events from VLM responses."""

    def __init__(self) -> None:
        self._events: list[Event] = []
        self._counts: dict[EventType, int] = {et: 0 for et in EventType}
        logger.info("EventTracker initialized")

    def classify_response(self, vlm_response: str) -> EventType:
        """Classify a VLM response string into an EventType using keyword matching."""
        response_lower = vlm_response.lower()

        # Check NO_DOG first (higher priority — multi-word match)
        for keyword in _KEYWORD_MAP[EventType.NO_DOG]:
            if keyword in response_lower:
                return EventType.NO_DOG

        # Check remaining event types
        for event_type, keywords in _KEYWORD_MAP.items():
            if event_type == EventType.NO_DOG:
                continue
            for keyword in keywords:
                if keyword in response_lower:
                    return event_type

        return EventType.IDLE

    def add_event(self, event_type: EventType, description: str,
                  frame_path: Optional[str] = None) -> Event:
        """Create and store a new event."""
        event = Event(
            timestamp=datetime.now(),
            event_type=event_type,
            description=description,
            frame_path=frame_path,
        )
        self._events.append(event)
        self._counts[event_type] = self._counts.get(event_type, 0) + 1
        logger.debug(f"Event added: {event_type.value} — {description[:60]}")
        return event

    def get_counts(self) -> dict[EventType, int]:
        """Return event counts by type."""
        return dict(self._counts)

    def get_summary(self) -> str:
        """Generate a formatted summary report of all events."""
        if not self._events:
            return "No events recorded during this session."

        lines = [
            "",
            "=" * 60,
            "  DOG MONITOR — Session Summary",
            "=" * 60,
            f"  Total events: {len(self._events)}",
            f"  First event:  {self._events[0].timestamp.strftime('%H:%M:%S')}",
            f"  Last event:   {self._events[-1].timestamp.strftime('%H:%M:%S')}",
            "",
            "  Activity Breakdown:",
        ]
        for et in EventType:
            count = self._counts.get(et, 0)
            if count > 0:
                lines.append(f"    {et.value:<12s} : {count}")
        lines.append("")
        lines.append("  Recent Events (last 5):")
        for event in self._events[-5:]:
            ts = event.timestamp.strftime('%H:%M:%S')
            lines.append(f"    [{ts}] {event.event_type.value:<12s} — {event.description[:50]}")
        lines.append("=" * 60)
        return "\n".join(lines)

    def get_events(self) -> list[Event]:
        """Return all recorded events."""
        return list(self._events)

    def last_event(self) -> Optional[Event]:
        """Return the most recent event, or None if no events recorded."""
        return self._events[-1] if self._events else None
