"""Thread-safe shared state — no third-party dependencies."""

import threading
import time
from typing import Optional

from .types import Detection


class SharedDetectionState:
    """Thread-safe state for passing detections from the pipeline callback to the control loop."""

    def __init__(self):
        self._lock = threading.Lock()
        self._detection: Optional[Detection] = None
        self._frame_count: int = 0
        self._available_ids: set = set()

    def update(self, detection: Optional[Detection], available_ids: set = None):
        with self._lock:
            self._detection = detection
            self._frame_count += 1
            if available_ids is not None:
                self._available_ids = available_ids

    def get_latest(self):
        with self._lock:
            return self._detection, self._frame_count

    def get_available_ids(self):
        """Get the set of currently visible detection IDs."""
        with self._lock:
            return self._available_ids.copy()


class FollowTargetState:
    """Thread-safe state for which detection ID to follow."""

    def __init__(self):
        self._lock = threading.Lock()
        self._target_id: Optional[int] = None
        self._last_seen: Optional[float] = None
        self._paused: bool = False
        self._explicit_lock: bool = False

    def set_paused(self, paused: bool):
        """Pause or resume drone follow. When paused the control loop holds position."""
        with self._lock:
            self._paused = paused

    def is_paused(self) -> bool:
        """Return True if drone follow is paused (IDLE mode)."""
        with self._lock:
            return self._paused

    def set_explicit_lock(self, locked: bool):
        """Mark whether the current target was explicitly chosen by the operator."""
        with self._lock:
            self._explicit_lock = locked

    def is_explicit_lock(self) -> bool:
        """Return True if the current target was explicitly locked by the operator."""
        with self._lock:
            return self._explicit_lock

    def enter_auto_mode(self):
        """Atomically reset to AUTO mode: no target, not paused, not locked."""
        with self._lock:
            self._target_id = None
            self._paused = False
            self._explicit_lock = False

    def set_target(self, detection_id: Optional[int]):
        """Set the target detection ID to follow."""
        with self._lock:
            self._target_id = detection_id
            if detection_id is not None:
                self._last_seen = time.monotonic()

    def get_target(self) -> Optional[int]:
        """Get the current target detection ID."""
        with self._lock:
            return self._target_id

    def update_last_seen(self):
        """Update the last seen timestamp for the current target."""
        with self._lock:
            if self._target_id is not None:
                self._last_seen = time.monotonic()

    def get_last_seen(self) -> Optional[float]:
        """Get the last seen timestamp (monotonic) for the current target."""
        with self._lock:
            return self._last_seen

    def get_status(self):
        """Get current status as a dict."""
        with self._lock:
            return {
                "following_id": self._target_id,
                "last_seen": self._last_seen
            }
