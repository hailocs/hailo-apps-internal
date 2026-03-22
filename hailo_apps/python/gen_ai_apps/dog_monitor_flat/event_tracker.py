"""Event tracking, classification, and statistics for the Dog Monitor app."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List

from hailo_apps.python.core.common.core import get_logger

logger = get_logger(__name__)


class EventType(Enum):
    """Categories of detected dog activities."""
    DRINKING = "DRINKING"
    EATING = "EATING"
    SLEEPING = "SLEEPING"
    PLAYING = "PLAYING"
    BARKING = "BARKING"
    AT_DOOR = "AT_DOOR"
    IDLE = "IDLE"
    NO_DOG = "NO_DOG"


# Keyword mapping for classification (checked in order; first match wins)
_KEYWORD_MAP: List[tuple[EventType, List[str]]] = [
    (EventType.DRINKING, ["drink", "water", "bowl of water", "lapping", "hydrat"]),
    (EventType.EATING, ["eat", "food", "kibble", "chew", "munch", "feeding"]),
    (EventType.SLEEPING, ["sleep", "rest", "nap", "lying down", "dozing", "curled up", "snooze", "asleep"]),
    (EventType.PLAYING, ["play", "toy", "fetch", "run", "jump", "chase", "tug", "romp"]),
    (EventType.BARKING, ["bark", "alert", "growl", "howl", "vocal", "whine", "woof"]),
    (EventType.AT_DOOR, ["door", "entrance", "waiting at", "doorway", "exit"]),
    (EventType.NO_DOG, ["no dog", "not visible", "empty", "no animal", "cannot see"]),
]


@dataclass
class Event:
    """A single detected dog activity event."""
    timestamp: str
    event_type: EventType
    description: str


@dataclass
class EventTracker:
    """Tracks, classifies, and summarises dog activity events."""

    events: List[Event] = field(default_factory=list)
    counts: Dict[str, int] = field(default_factory=lambda: {e.value: 0 for e in EventType})
    start_time: float = field(default_factory=time.time)
    last_event_type: EventType = EventType.NO_DOG
    last_description: str = ""

    # ---- public API --------------------------------------------------------

    def classify_response(self, response: str) -> EventType:
        """Classify a VLM response string into an EventType via keyword matching."""
        lower = response.lower()
        for event_type, keywords in _KEYWORD_MAP:
            if any(kw in lower for kw in keywords):
                return event_type
        return EventType.IDLE

    def log_event(self, event_type: EventType, description: str) -> Event:
        """Record a new event and update running counts."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        event = Event(timestamp=timestamp, event_type=event_type, description=description)
        self.events.append(event)
        self.counts[event_type.value] += 1
        self.last_event_type = event_type
        self.last_description = description
        logger.info(f"[{timestamp}] {event_type.value}: {description}")
        return event

    def get_summary(self) -> Dict:
        """Return a summary dict with elapsed time, total events, and per-type counts."""
        elapsed = time.time() - self.start_time
        hours, remainder = divmod(int(elapsed), 3600)
        minutes, seconds = divmod(remainder, 60)
        return {
            "elapsed": f"{hours:02d}:{minutes:02d}:{seconds:02d}",
            "total_events": len(self.events),
            "counts": {k: v for k, v in self.counts.items() if v > 0},
            "events": self.events,
        }

    def print_summary(self) -> None:
        """Print a formatted session summary report to stdout."""
        summary = self.get_summary()
        print("\n" + "=" * 60)
        print("  DOG MONITOR — Session Summary")
        print("=" * 60)
        print(f"  Duration:       {summary['elapsed']}")
        print(f"  Total events:   {summary['total_events']}")
        print("-" * 60)
        print("  Activity Counts:")
        if summary["counts"]:
            for activity, count in sorted(summary["counts"].items(), key=lambda x: -x[1]):
                print(f"    {activity:<12s}  {count}")
        else:
            print("    (none)")
        print("-" * 60)
        if summary["events"]:
            print("  Event Log (last 20):")
            for ev in summary["events"][-20:]:
                print(f"    [{ev.timestamp}] {ev.event_type.value:<12s} {ev.description}")
        print("=" * 60)

    def save_frame(self, frame, events_dir: str, event_type: EventType) -> None:
        """Save a frame to disk when an interesting event is detected."""
        try:
            import cv2
            os.makedirs(events_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = os.path.join(events_dir, f"{event_type.value}_{ts}.jpg")
            cv2.imwrite(filename, frame)
            logger.info(f"Saved event frame: {filename}")
        except Exception as e:
            logger.error(f"Failed to save event frame: {e}")
