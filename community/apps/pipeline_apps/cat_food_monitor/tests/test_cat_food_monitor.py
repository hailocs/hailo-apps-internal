"""Pure-Python unit tests for the Cat Food Monitor community app.

The app itself is database/embedding/GStreamer-heavy. These tests exercise
*only* the extractable, hardware-independent logic:

  * ``processed_names`` dict bookkeeping on the pipeline class
    (``is_name_processed`` / ``get_processed_names_by_name``) — the fix that
    replaced a ``set`` used like a ``dict``.
  * Loading and validating ``cat_food_algo_params.json`` (including the
    correctly-spelled ``...classification...`` threshold key).
  * The ``track_id is None`` guard in the vector-DB callback (tested via a
    predicate that mirrors the source branch).
  * The per-cat feeding-session / CSV-row formatting logic in
    ``CatFoodMonitorCallbackClass`` (cooldown, arrive/depart, durations).

No Hailo device, inference, LanceDB, or network access is required. Heavy
imports (``hailo``, ``gi``, GStreamer, the DB-backed pipeline module) are
stubbed with ``MagicMock`` before the app modules are imported, mirroring the
style of ``line_crossing_counter/tests``.
"""

import json
import os
import sys
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.community

# ---------------------------------------------------------------------------
# Stub the heavy / hardware-dependent modules BEFORE importing the app code.
# ---------------------------------------------------------------------------
for mod_name in [
    "hailo",
    "gi",
    "gi.repository",
    "gi.repository.Gst",
    "setproctitle",
    "numpy",
    "PIL",
    "PIL.Image",
    "hailo_apps.python.core.common.db_handler",
    "hailo_apps.python.core.common.core",
    "hailo_apps.python.core.common.buffer_utils",
    "hailo_apps.python.core.gstreamer.gstreamer_app",
    "hailo_apps.python.core.gstreamer.gstreamer_helper_pipelines",
    "hailo_apps.python.core.common.defines",
    "hailo_apps.python.core.common.hailo_logger",
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()
sys.modules["gi"].require_version = lambda *a, **kw: None
# get_logger(__name__) must return something with .info/.warning/.error
sys.modules["hailo_apps.python.core.common.hailo_logger"].get_logger = (
    lambda *a, **kw: MagicMock()
)
# The DatabaseHandler import line uses `from ... import DatabaseHandler, Record`
sys.modules["hailo_apps.python.core.common.db_handler"].DatabaseHandler = MagicMock()
sys.modules["hailo_apps.python.core.common.db_handler"].Record = MagicMock()


class _StubAppCallbackBase:
    """Minimal stand-in for ``app_callback_class``."""

    def __init__(self):
        self.frame_count = 0
        self.use_frame = False


sys.modules["hailo_apps.python.core.gstreamer.gstreamer_app"].app_callback_class = (
    _StubAppCallbackBase
)
sys.modules["hailo_apps.python.core.gstreamer.gstreamer_app"].GStreamerApp = object


# Now the app modules import cleanly (no device / DB / network touched at import).
from community.apps.pipeline_apps.cat_food_monitor.cat_food_monitor_pipeline import (  # noqa: E402
    GStreamerCatFoodMonitorApp,
)
from community.apps.pipeline_apps.cat_food_monitor import cat_food_monitor as cfm  # noqa: E402
from community.apps.pipeline_apps.cat_food_monitor.cat_food_monitor import (  # noqa: E402
    CatFoodMonitorCallbackClass,
    FEEDING_LOG_COOLDOWN_SECONDS,
)


# ---------------------------------------------------------------------------
# processed_names dict logic
#
# is_name_processed / get_processed_names_by_name are bound methods that touch
# ONLY self.processed_names. We invoke the real, unbound functions from the
# class against a tiny stub `self`, so the actual source code is under test
# without constructing the (DB-backed) app.
# ---------------------------------------------------------------------------
class _ProcessedNamesHost:
    """Carries just the attribute the two methods read."""

    def __init__(self, processed_names=None):
        self.processed_names = {} if processed_names is None else processed_names

    # Bind the *real* implementations from the app class.
    get_processed_names_by_name = (
        GStreamerCatFoodMonitorApp.get_processed_names_by_name
    )
    is_name_processed = GStreamerCatFoodMonitorApp.is_name_processed


class TestProcessedNames:
    def test_absent_name_is_not_processed(self):
        host = _ProcessedNamesHost()
        assert host.is_name_processed("Whiskers") is False

    def test_absent_name_lookup_returns_none(self):
        host = _ProcessedNamesHost()
        assert host.get_processed_names_by_name("Whiskers") is None

    def test_present_name_is_processed(self):
        host = _ProcessedNamesHost({"Whiskers": 7})
        assert host.is_name_processed("Whiskers") is True

    def test_lookup_returns_stored_global_id(self):
        host = _ProcessedNamesHost({"Whiskers": 7, "Tom": 42})
        assert host.get_processed_names_by_name("Whiskers") == 7
        assert host.get_processed_names_by_name("Tom") == 42

    def test_duplicate_name_keeps_last_global_id(self):
        # This is the core of the set-used-as-dict fix: assigning the same name
        # twice must overwrite, so a lookup returns the LAST global_id.
        host = _ProcessedNamesHost()
        host.processed_names["Whiskers"] = 1
        host.processed_names["Whiskers"] = 99
        assert host.is_name_processed("Whiskers") is True
        assert host.get_processed_names_by_name("Whiskers") == 99

    def test_global_id_zero_is_still_processed(self):
        # global_id 0 is falsy but a valid id; membership (not truthiness)
        # must decide "processed".
        host = _ProcessedNamesHost({"Mittens": 0})
        assert host.is_name_processed("Mittens") is True
        assert host.get_processed_names_by_name("Mittens") == 0

    def test_empty_string_name(self):
        host = _ProcessedNamesHost({"": 5})
        assert host.is_name_processed("") is True
        assert host.get_processed_names_by_name("") == 5

    def test_independent_names(self):
        host = _ProcessedNamesHost({"A": 1})
        assert host.is_name_processed("A") is True
        assert host.is_name_processed("B") is False
        assert host.get_processed_names_by_name("B") is None


# ---------------------------------------------------------------------------
# algo params JSON
# ---------------------------------------------------------------------------
ALGO_PARAMS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "cat_food_algo_params.json",
)

# The threshold key carries the correctly-spelled "classification"
# (renamed from "classificaiton").
THRESHOLD_KEY = "lance_db_vector_search_classification_confidence_threshold"


@pytest.fixture(scope="module")
def algo_params():
    with open(ALGO_PARAMS_PATH, "r") as f:
        return json.load(f)


class TestAlgoParams:
    def test_file_exists(self):
        assert os.path.isfile(ALGO_PARAMS_PATH)

    def test_loads_as_dict(self, algo_params):
        assert isinstance(algo_params, dict)

    def test_required_keys_present(self, algo_params):
        for key in ("skip_frames", THRESHOLD_KEY, "batch_size"):
            assert key in algo_params, f"missing key: {key}"

    def test_classification_key_is_correctly_spelled(self, algo_params):
        # Guard against a regression to the old misspelling "classificaiton".
        assert THRESHOLD_KEY in algo_params
        assert "classification" in THRESHOLD_KEY
        misspelled = THRESHOLD_KEY.replace("classification", "classificaiton")
        assert misspelled not in algo_params

    def test_threshold_value_type_and_range(self, algo_params):
        threshold = algo_params[THRESHOLD_KEY]
        assert isinstance(threshold, (int, float))
        assert not isinstance(threshold, bool)
        assert 0.0 <= threshold <= 1.0

    def test_skip_frames_is_positive_int(self, algo_params):
        skip = algo_params["skip_frames"]
        assert isinstance(skip, int)
        assert not isinstance(skip, bool)
        assert skip > 0

    def test_batch_size_is_positive_int(self, algo_params):
        batch = algo_params["batch_size"]
        assert isinstance(batch, int)
        assert not isinstance(batch, bool)
        assert batch >= 1

    def test_missing_key_raises_keyerror(self):
        # Mirrors how the app reads params (self.algo_params['skip_frames']);
        # absent keys must raise rather than silently return None.
        params = {"batch_size": 1}
        with pytest.raises(KeyError):
            _ = params["skip_frames"]


# ---------------------------------------------------------------------------
# None-track_id guard predicate
#
# The vector-DB callback computes track_id, then: `if track_id is None: continue`.
# That branch is inside a Hailo-object loop, so we test the predicate directly.
# ---------------------------------------------------------------------------
def _resolve_track_id(unique_id_objects):
    """Mirror of cat_food_monitor_pipeline.py:398-402.

    Returns the first unique-id's id, or None when there are no unique-id
    objects. The callback then skips (``continue``) on a None track id.
    """
    return unique_id_objects[0].get_id() if unique_id_objects else None


def _is_skipped_detection(unique_id_objects):
    """The guard: a detection with a None track id is skipped."""
    return _resolve_track_id(unique_id_objects) is None


class _FakeUniqueId:
    def __init__(self, value):
        self._value = value

    def get_id(self):
        return self._value


class TestTrackIdGuard:
    def test_no_unique_id_yields_none(self):
        assert _resolve_track_id([]) is None

    def test_present_unique_id_yields_value(self):
        assert _resolve_track_id([_FakeUniqueId(5)]) == 5

    def test_first_unique_id_wins(self):
        assert _resolve_track_id([_FakeUniqueId(11), _FakeUniqueId(22)]) == 11

    def test_detection_without_track_is_skipped(self):
        assert _is_skipped_detection([]) is True

    def test_detection_with_track_is_not_skipped(self):
        assert _is_skipped_detection([_FakeUniqueId(0)]) is False

    def test_track_id_zero_is_not_skipped(self):
        # track id 0 is a real id, not "missing".
        assert _resolve_track_id([_FakeUniqueId(0)]) == 0
        assert _is_skipped_detection([_FakeUniqueId(0)]) is False


# ---------------------------------------------------------------------------
# skip_frames re-processing counter logic
#
# Reproduce the integer-counter branch from the callback (lines 406-410, 445)
# in isolation: hold a track below skip_frames, then verify the periodic
# re-verification reset to -3 * skip_frames.
# ---------------------------------------------------------------------------
class TestSkipFrameCounter:
    def test_increments_until_threshold(self):
        skip_frames = 3
        counts = {}
        track_id = 1
        # While below skip_frames, the callback increments and continues.
        skipped = 0
        for _ in range(skip_frames):
            if counts.get(track_id, 0) < skip_frames:
                counts[track_id] = counts.get(track_id, 0) + 1
                skipped += 1
        assert skipped == skip_frames
        assert counts[track_id] == skip_frames
        # Now it is no longer below the threshold -> would process.
        assert not (counts[track_id] < skip_frames)

    def test_reprocess_reset_is_negative_multiple(self):
        skip_frames = 15
        counts = {7: skip_frames}
        # After processing, the callback sets the counter to -3 * skip_frames.
        counts[7] = -3 * skip_frames
        assert counts[7] == -45
        # It then takes (skip_frames + 3*skip_frames) frames to process again.
        frames_to_reprocess = 0
        while counts[7] < skip_frames:
            counts[7] += 1
            frames_to_reprocess += 1
        assert frames_to_reprocess == 4 * skip_frames


# ---------------------------------------------------------------------------
# Feeding-session / CSV logging logic (CatFoodMonitorCallbackClass)
#
# We construct the REAL callback class but redirect its CSV log file into a
# temp dir, so log_feeding_event / start_session / end_session / cooldown are
# all exercised against the real implementation.
# ---------------------------------------------------------------------------
@pytest.fixture
def cb(tmp_path, monkeypatch):
    """Real CatFoodMonitorCallbackClass with its log file inside tmp_path.

    The class derives its log path from ``os.path.dirname(__file__)`` of the
    app module, so we redirect the module's ``__file__`` into ``tmp_path``
    (rather than patching ``os.path`` globally, which would disturb pytest).
    """
    monkeypatch.setattr(cfm, "__file__", str(tmp_path / "cat_food_monitor.py"))
    instance = CatFoodMonitorCallbackClass()
    return instance


def _read_log(cb_instance):
    with open(cb_instance.log_file, "r", newline="") as f:
        return [line for line in f.read().splitlines() if line]


class TestLogFileInit:
    def test_log_file_created_with_header(self, cb):
        assert os.path.exists(cb.log_file)
        rows = _read_log(cb)
        assert rows[0] == (
            "timestamp,cat_name,event,track_id,confidence,duration_seconds"
        )

    def test_log_file_in_tmp(self, cb, tmp_path):
        assert os.path.dirname(cb.log_file) == str(tmp_path)


class TestFeedingSessions:
    def test_start_session_records_active_and_logs_arrived(self, cb):
        cb.start_session("Whiskers", track_id=3, confidence=0.91)
        assert "Whiskers" in cb.active_sessions
        assert cb.active_sessions["Whiskers"]["track_id"] == 3
        rows = _read_log(cb)
        # header + one "arrived" row
        assert len(rows) == 2
        fields = rows[1].split(",")
        assert fields[1] == "Whiskers"
        assert fields[2] == "arrived"
        assert fields[3] == "3"
        assert fields[4] == "0.91"  # confidence formatted to 2dp
        assert fields[5] == ""      # no duration on arrival

    def test_start_session_idempotent_while_active(self, cb):
        cb.start_session("Tom", track_id=1, confidence=0.8)
        first_start = cb.active_sessions["Tom"]["start"]
        # Second start while already active must NOT overwrite or re-log.
        cb.start_session("Tom", track_id=2, confidence=0.5)
        assert cb.active_sessions["Tom"]["start"] == first_start
        assert cb.active_sessions["Tom"]["track_id"] == 1
        rows = _read_log(cb)
        assert len(rows) == 2  # only the original "arrived"

    def test_end_session_logs_departed_with_duration(self, cb):
        cb.start_session("Tom", track_id=1, confidence=0.8)
        # Force the start time into the past so duration is well-defined and
        # bypass the per-cat cooldown so the departed row is written.
        cb.active_sessions["Tom"]["start"] = datetime.now() - timedelta(seconds=30)
        cb.last_log_time.clear()
        cb.end_session("Tom")
        assert "Tom" not in cb.active_sessions  # session popped
        rows = _read_log(cb)
        departed = [r for r in rows if ",departed," in r]
        assert len(departed) == 1
        fields = departed[0].split(",")
        assert fields[1] == "Tom"
        assert fields[2] == "departed"
        assert fields[4] == ""  # no confidence on departure
        assert float(fields[5]) >= 29.0  # ~30s duration

    def test_end_session_unknown_cat_is_noop(self, cb):
        # Popping a non-existent session must not raise or log.
        cb.end_session("NeverSeen")
        rows = _read_log(cb)
        assert len(rows) == 1  # header only


class TestCooldown:
    def test_cooldown_suppresses_repeated_logs(self, cb):
        cb.log_feeding_event("Felix", "arrived", track_id=1, confidence=0.7)
        # Immediate second event for same cat -> suppressed by cooldown.
        cb.log_feeding_event("Felix", "departed", track_id=1, confidence=None, duration=10)
        rows = _read_log(cb)
        assert len(rows) == 2  # header + first event only

    def test_cooldown_is_per_cat(self, cb):
        cb.log_feeding_event("Felix", "arrived", track_id=1, confidence=0.7)
        cb.log_feeding_event("Garfield", "arrived", track_id=2, confidence=0.6)
        rows = _read_log(cb)
        assert len(rows) == 3  # different cats are not throttled against each other

    def test_event_after_cooldown_elapsed_is_logged(self, cb):
        cb.log_feeding_event("Felix", "arrived", track_id=1, confidence=0.7)
        # Backdate last_log_time beyond the cooldown window.
        cb.last_log_time["Felix"] = datetime.now() - timedelta(
            seconds=FEEDING_LOG_COOLDOWN_SECONDS + 1
        )
        cb.log_feeding_event("Felix", "departed", track_id=1, confidence=None, duration=12)
        rows = _read_log(cb)
        assert len(rows) == 3


class TestRowFormatting:
    def test_none_confidence_renders_empty(self, cb):
        cb.log_feeding_event("X", "departed", track_id=1, confidence=None, duration=5.0)
        fields = _read_log(cb)[1].split(",")
        assert fields[4] == ""
        assert fields[5] == "5.0"

    def test_none_duration_renders_empty(self, cb):
        cb.log_feeding_event("X", "arrived", track_id=1, confidence=0.5, duration=None)
        fields = _read_log(cb)[1].split(",")
        assert fields[4] == "0.50"
        assert fields[5] == ""

    def test_confidence_rounded_to_two_dp(self, cb):
        cb.log_feeding_event("X", "arrived", track_id=1, confidence=0.123456)
        fields = _read_log(cb)[1].split(",")
        assert fields[4] == "0.12"

    def test_duration_rounded_to_one_dp(self, cb):
        cb.log_feeding_event("X", "departed", track_id=1, confidence=None, duration=12.345)
        fields = _read_log(cb)[1].split(",")
        assert fields[5] == "12.3"

    def test_timestamp_format(self, cb):
        cb.log_feeding_event("X", "arrived", track_id=1, confidence=0.5)
        ts = _read_log(cb)[1].split(",")[0]
        # Must parse back as the documented strftime format.
        datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
