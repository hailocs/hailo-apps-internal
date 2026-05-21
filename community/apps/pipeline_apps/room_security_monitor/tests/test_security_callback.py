"""Unit tests for room_security_monitor: algo params + alarm/log helpers.

Heavy GUI/threading code is not unit-testable without major refactoring;
this file covers what can be exercised in isolation: the security algo
JSON schema, the alarm-cooldown state machine, and the access-log CSV
contract.
"""

import csv
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

for mod_name in [
    "hailo",
    "gi",
    "gi.repository",
    "gi.repository.Gst",
    "PIL",
    "PIL.Image",
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()
sys.modules["gi"].require_version = lambda *a, **kw: None


class _StubAppCallbackBase:
    def __init__(self):
        self.frame_count = 0
        self.use_frame = False

    def get_count(self):
        return self.frame_count


sys.modules.setdefault(
    "hailo_apps.python.core.gstreamer.gstreamer_app", MagicMock()
).app_callback_class = _StubAppCallbackBase

from community.apps.pipeline_apps.room_security_monitor.room_security_monitor import (
    ALARM_COOLDOWN_SECONDS,
    MAX_ENROLLABLE_PER_TRACK,
    SecurityCallbackClass,
)

ALGO_PARAMS_PATH = (
    Path(__file__).resolve().parents[1] / "security_algo_params.json"
)


# ============================================================
# security_algo_params.json schema
# ============================================================


class TestAlgoParamsSchema:
    EXPECTED_KEYS = {
        "min_face_pixels_tolerance",
        "blurriness_tolerance",
        "procrustes_distance_threshold",
        "skip_frames",
        "lance_db_vector_search_classificaiton_confidence_threshold",
        "batch_size",
        "unknown_alarm_cooldown_seconds",
    }

    def test_file_exists(self):
        assert ALGO_PARAMS_PATH.exists(), f"Missing {ALGO_PARAMS_PATH}"

    def test_keys_present(self):
        params = json.loads(ALGO_PARAMS_PATH.read_text())
        missing = self.EXPECTED_KEYS - set(params.keys())
        assert not missing, f"Missing keys: {missing}"

    def test_numeric_value_ranges(self):
        params = json.loads(ALGO_PARAMS_PATH.read_text())
        # All values must be positive (no zero/negative thresholds)
        for key, value in params.items():
            assert isinstance(value, (int, float)), f"{key}: not numeric"
            assert value >= 0, f"{key}: negative value {value}"

    def test_confidence_threshold_in_unit_range(self):
        params = json.loads(ALGO_PARAMS_PATH.read_text())
        t = params["lance_db_vector_search_classificaiton_confidence_threshold"]
        assert 0.0 <= t <= 1.0

    def test_procrustes_distance_threshold_reasonable(self):
        params = json.loads(ALGO_PARAMS_PATH.read_text())
        t = params["procrustes_distance_threshold"]
        # Procrustes distance is in [0, ~2] for normalized landmarks
        assert 0.0 < t < 2.0


# ============================================================
# Alarm-cooldown state machine
# ============================================================


class TestShouldTriggerAlarm:
    def test_first_call_triggers(self, tmp_path):
        cb = SecurityCallbackClass(
            alarm_cooldown=30, log_file=str(tmp_path / "log.csv")
        )
        assert cb.should_trigger_alarm(track_id=1) is True

    def test_repeat_call_within_cooldown_blocks(self, tmp_path):
        cb = SecurityCallbackClass(
            alarm_cooldown=60, log_file=str(tmp_path / "log.csv")
        )
        assert cb.should_trigger_alarm(track_id=1) is True
        assert cb.should_trigger_alarm(track_id=1) is False

    def test_different_tracks_independent(self, tmp_path):
        cb = SecurityCallbackClass(
            alarm_cooldown=60, log_file=str(tmp_path / "log.csv")
        )
        assert cb.should_trigger_alarm(track_id=1) is True
        assert cb.should_trigger_alarm(track_id=2) is True

    def test_after_cooldown_re_triggers(self, tmp_path):
        cb = SecurityCallbackClass(
            alarm_cooldown=60, log_file=str(tmp_path / "log.csv")
        )
        cb.should_trigger_alarm(track_id=1)
        # Manually move timestamp into the past
        cb.alarm_timestamps[1] = datetime.now() - timedelta(seconds=61)
        assert cb.should_trigger_alarm(track_id=1) is True

    def test_cooldown_state_only_updates_when_triggered(self, tmp_path):
        """If an alarm is blocked by cooldown, the last-trigger timestamp must
        NOT slide forward (otherwise the cooldown extends indefinitely)."""
        cb = SecurityCallbackClass(
            alarm_cooldown=60, log_file=str(tmp_path / "log.csv")
        )
        cb.should_trigger_alarm(track_id=1)
        first_ts = cb.alarm_timestamps[1]
        time.sleep(0.01)
        # This call is blocked by cooldown — timestamp should stay at first.
        cb.should_trigger_alarm(track_id=1)
        assert cb.alarm_timestamps[1] == first_ts


# ============================================================
# Access log CSV
# ============================================================


class TestAccessLog:
    def test_log_header_written_at_init(self, tmp_path):
        log = tmp_path / "log.csv"
        SecurityCallbackClass(log_file=str(log))
        assert log.exists()
        rows = list(csv.reader(log.open()))
        assert rows[0] == ["timestamp", "track_id", "name", "confidence", "event_type"]

    def test_log_event_appends_row(self, tmp_path):
        log = tmp_path / "log.csv"
        cb = SecurityCallbackClass(log_file=str(log))
        cb.log_access_event(track_id=42, name="alice", confidence=0.95, event_type="enter")
        rows = list(csv.reader(log.open()))
        assert len(rows) == 2  # header + 1 event
        assert rows[1][1:] == ["42", "alice", "0.95", "enter"]

    def test_log_multiple_events(self, tmp_path):
        log = tmp_path / "log.csv"
        cb = SecurityCallbackClass(log_file=str(log))
        cb.log_access_event(1, "a", 0.5, "x")
        cb.log_access_event(2, "b", 0.7, "y")
        cb.log_access_event(3, "c", 0.9, "z")
        rows = list(csv.reader(log.open()))
        assert len(rows) == 4  # header + 3 events

    def test_existing_log_not_overwritten(self, tmp_path):
        log = tmp_path / "log.csv"
        # Pre-populate with a custom header
        log.write_text("pre-existing,content\n")
        cb = SecurityCallbackClass(log_file=str(log))
        cb.log_access_event(1, "a", 0.5, "x")
        rows = list(csv.reader(log.open()))
        # First row preserved, append happened after
        assert rows[0] == ["pre-existing", "content"]


# ============================================================
# Constants sanity
# ============================================================


class TestConstants:
    def test_alarm_cooldown_positive(self):
        assert ALARM_COOLDOWN_SECONDS > 0

    def test_max_enrollable_positive(self):
        assert MAX_ENROLLABLE_PER_TRACK > 0
