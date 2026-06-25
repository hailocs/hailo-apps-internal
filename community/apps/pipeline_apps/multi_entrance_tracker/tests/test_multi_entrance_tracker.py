"""Pure-Python unit tests for the multi-entrance face re-identification tracker.

These tests exercise the real app logic (no Hailo device, no GStreamer pipeline,
no inference) by:

  1. Stubbing the ``hailo``, ``gi`` and ``gstreamer_app`` modules so the app
     modules import cleanly off-device, then importing the *real*
     ``app_callback`` / ``MultiEntranceCallbackClass`` and the *real* pipeline
     log helpers.
  2. Driving ``app_callback`` with hand-built fake ROI / detection /
     classification / unique-id objects to cover the bounded per-entrance LRU
     and the cross-camera-match counting.
  3. Binding the unbound pipeline log-helper methods
     (``_append_event`` / ``_log_event`` / ``_log_entrance_change``) onto a
     lightweight fake ``self`` so we test the real entry/exit transition logic
     without running the heavy ``MultiEntranceTrackerApp.__init__``.

Behaviour under test:
  * ``per_entrance_counts`` is a bounded LRU (``OrderedDict`` capped at
    ``MAX_TRACKED_IDS_PER_ENTRANCE``): adding > cap evicts the oldest id;
    unique ids counted per entrance; re-seeing an id does not double-count and
    refreshes its recency.
  * cross-camera match counting: ``confidence > 0`` => re-identified (counted),
    ``confidence == 0`` => brand-new (not counted).
  * entry/exit event logging + ``person_last_entrance`` transitions: moving the
    same person to a different entrance records an exit (old) + entry (new);
    staying at the same entrance records nothing.
"""

import sys
import threading
import types
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.community


# ---------------------------------------------------------------------------
# Module stubs: make the app importable with no Hailo device / GStreamer.
# ---------------------------------------------------------------------------

# Sentinel type-key objects used by roi.get_objects_typed(...). Identity is all
# that matters; the fake ROI/detection match against these exact objects.
_HAILO_DETECTION = object()
_HAILO_UNIQUE_ID = object()
_HAILO_CLASSIFICATION = object()
_HAILO_MATRIX = object()


def _build_hailo_stub():
    mod = types.ModuleType("hailo")
    mod.HAILO_DETECTION = _HAILO_DETECTION
    mod.HAILO_UNIQUE_ID = _HAILO_UNIQUE_ID
    mod.HAILO_CLASSIFICATION = _HAILO_CLASSIFICATION
    mod.HAILO_MATRIX = _HAILO_MATRIX
    # get_roi_from_buffer is monkeypatched per-test to return our fake ROI.
    mod.get_roi_from_buffer = lambda buffer: buffer
    # HailoTracker / HailoClassification are referenced at import time by the
    # pipeline module; only their presence matters for these pure-Python tests.
    mod.HailoTracker = MagicMock()
    mod.HailoClassification = MagicMock()
    return mod


class _StubAppCallbackBase:
    """Mimics the real app_callback_class enough for MultiEntranceCallbackClass."""

    def __init__(self):
        self.frame_count = 0
        self.use_frame = False

    def increment(self):
        self.frame_count += 1


class _StubGStreamerApp:
    """Real (non-Mock) base so MultiEntranceTrackerApp stays a real subclass and
    keeps its own method definitions (a MagicMock base swallows them)."""

    def __init__(self, *args, **kwargs):
        pass


def _build_gstreamer_app_stub():
    mod = types.ModuleType("hailo_apps.python.core.gstreamer.gstreamer_app")
    mod.app_callback_class = _StubAppCallbackBase
    mod.GStreamerApp = _StubGStreamerApp
    mod.dummy_callback = lambda *a, **kw: None
    return mod


# Names the pipeline module pulls from gstreamer_helper_pipelines at import time.
_HELPER_PIPELINE_NAMES = [
    "CROPPER_PIPELINE",
    "DISPLAY_PIPELINE",
    "INFERENCE_PIPELINE",
    "INFERENCE_PIPELINE_WRAPPER",
    "QUEUE",
    "SOURCE_PIPELINE",
    "TRACKER_PIPELINE",
    "USER_CALLBACK_PIPELINE",
    "get_source_type",
]


def _build_helper_pipelines_stub():
    mod = types.ModuleType(
        "hailo_apps.python.core.gstreamer.gstreamer_helper_pipelines"
    )
    for name in _HELPER_PIPELINE_NAMES:
        setattr(mod, name, lambda *a, **kw: "")
    return mod


for mod_name, factory in [
    ("hailo", _build_hailo_stub),
    ("gi", lambda: MagicMock()),
    ("gi.repository", lambda: MagicMock()),
    ("gi.repository.Gst", lambda: MagicMock()),
    ("hailo_apps.python.core.gstreamer.gstreamer_app", _build_gstreamer_app_stub),
    (
        "hailo_apps.python.core.gstreamer.gstreamer_helper_pipelines",
        _build_helper_pipelines_stub,
    ),
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = factory()

# gi.require_version must be a callable no-op.
sys.modules["gi"].require_version = lambda *a, **kw: None


# Now import the real app modules. The entry point gives us the cross-camera
# match + bounded-LRU logic; the pipeline module gives us the real entry/exit
# log-helper methods (tested via MethodType binding, without running __init__).
from community.apps.pipeline_apps.multi_entrance_tracker.multi_entrance_tracker import (  # noqa: E402
    MAX_TRACKED_IDS_PER_ENTRANCE,
    MultiEntranceCallbackClass,
    app_callback,
)
from community.apps.pipeline_apps.multi_entrance_tracker.multi_entrance_tracker_pipeline import (  # noqa: E402
    MultiEntranceTrackerApp,
)


# ---------------------------------------------------------------------------
# Fake Hailo object graph for driving the real app_callback.
# ---------------------------------------------------------------------------


class _FakeUniqueId:
    def __init__(self, track_id):
        self._id = track_id

    def get_id(self):
        return self._id


class _FakeClassification:
    def __init__(self, label, confidence):
        self._label = label
        self._confidence = confidence

    def get_label(self):
        return self._label

    def get_confidence(self):
        return self._confidence


class _FakeDetection:
    """A detection holding typed child objects, keyed by the sentinel type."""

    def __init__(self, track_ids=None, classifications=None):
        self._objects = {
            _HAILO_UNIQUE_ID: [_FakeUniqueId(t) for t in (track_ids or [])],
            _HAILO_CLASSIFICATION: list(classifications or []),
        }

    def get_objects_typed(self, type_key):
        return self._objects.get(type_key, [])


class _FakeRoi:
    def __init__(self, stream_id, detections):
        self._stream_id = stream_id
        self._detections = list(detections)

    def get_stream_id(self):
        return self._stream_id

    def get_objects_typed(self, type_key):
        if type_key is _HAILO_DETECTION:
            return self._detections
        return []


@pytest.fixture
def patch_roi(monkeypatch):
    """Return a helper that wires a given fake ROI into hailo.get_roi_from_buffer."""

    def _set(roi):
        monkeypatch.setattr(
            sys.modules["hailo"], "get_roi_from_buffer", lambda buffer: roi
        )
        # app_callback requires a non-None buffer to proceed.
        return object()

    return _set


def _run_callback(patch_roi, user_data, stream_id, detections):
    buffer = patch_roi(_FakeRoi(stream_id, detections))
    app_callback(element=None, buffer=buffer, user_data=user_data)


# ===========================================================================
# Cross-camera match counting (confidence > 0 => re-identified)
# ===========================================================================


class TestCrossCameraMatchCounting:
    def test_new_identity_confidence_zero_not_counted(self, patch_roi):
        ud = MultiEntranceCallbackClass()
        det = _FakeDetection(
            track_ids=[1],
            classifications=[_FakeClassification("entrance_0_person_abc", 0)],
        )
        _run_callback(patch_roi, ud, "src_0", [det])
        assert ud.cross_camera_matches == 0

    def test_reidentified_confidence_positive_counted(self, patch_roi):
        ud = MultiEntranceCallbackClass()
        det = _FakeDetection(
            track_ids=[1],
            classifications=[_FakeClassification("src_0,entrance_0_person_abc", 0.9)],
        )
        _run_callback(patch_roi, ud, "src_1", [det])
        assert ud.cross_camera_matches == 1

    def test_multiple_classifications_each_counted(self, patch_roi):
        ud = MultiEntranceCallbackClass()
        det = _FakeDetection(
            track_ids=[1],
            classifications=[
                _FakeClassification("a", 0.5),
                _FakeClassification("b", 0.0),  # new -> not counted
                _FakeClassification("c", 0.1),
            ],
        )
        _run_callback(patch_roi, ud, "src_0", [det])
        assert ud.cross_camera_matches == 2

    def test_detection_without_unique_id_skipped(self, patch_roi):
        ud = MultiEntranceCallbackClass()
        # No track id => `if not ids: continue` before classifications are read.
        det = _FakeDetection(
            track_ids=[],
            classifications=[_FakeClassification("x", 0.9)],
        )
        _run_callback(patch_roi, ud, "src_0", [det])
        assert ud.cross_camera_matches == 0
        assert ud.per_entrance_counts == {}

    def test_none_buffer_is_noop(self):
        ud = MultiEntranceCallbackClass()
        # No exception, no state change.
        app_callback(element=None, buffer=None, user_data=ud)
        assert ud.cross_camera_matches == 0
        assert ud.per_entrance_counts == {}


# ===========================================================================
# Per-entrance bounded LRU counting (the fix)
# ===========================================================================


class TestPerEntranceLRU:
    def test_unique_ids_counted_per_entrance(self, patch_roi):
        ud = MultiEntranceCallbackClass()
        for tid in (10, 11, 12):
            det = _FakeDetection(track_ids=[tid], classifications=[])
            _run_callback(patch_roi, ud, "src_0", [det])
        assert list(ud.per_entrance_counts.keys()) == ["src_0"]
        assert len(ud.per_entrance_counts["src_0"]) == 3
        assert set(ud.per_entrance_counts["src_0"].keys()) == {10, 11, 12}

    def test_reseeing_id_does_not_double_count(self, patch_roi):
        ud = MultiEntranceCallbackClass()
        for _ in range(5):
            det = _FakeDetection(track_ids=[42], classifications=[])
            _run_callback(patch_roi, ud, "src_0", [det])
        assert len(ud.per_entrance_counts["src_0"]) == 1

    def test_reseeing_id_refreshes_recency(self, patch_roi):
        ud = MultiEntranceCallbackClass()
        for tid in (1, 2, 3):
            _run_callback(
                patch_roi, ud, "src_0", [_FakeDetection(track_ids=[tid])]
            )
        # Re-see id 1 -> it should move to the most-recent (end) position.
        _run_callback(patch_roi, ud, "src_0", [_FakeDetection(track_ids=[1])])
        assert list(ud.per_entrance_counts["src_0"].keys()) == [2, 3, 1]

    def test_separate_entrances_have_independent_counts(self, patch_roi):
        ud = MultiEntranceCallbackClass()
        _run_callback(patch_roi, ud, "src_0", [_FakeDetection(track_ids=[1])])
        _run_callback(patch_roi, ud, "src_1", [_FakeDetection(track_ids=[1])])
        assert len(ud.per_entrance_counts["src_0"]) == 1
        assert len(ud.per_entrance_counts["src_1"]) == 1
        # Same id at two entrances counts once per entrance (not merged).
        assert set(ud.per_entrance_counts.keys()) == {"src_0", "src_1"}

    def test_stream_id_quotes_stripped(self, patch_roi):
        ud = MultiEntranceCallbackClass()
        _run_callback(patch_roi, ud, "'src_0'", [_FakeDetection(track_ids=[1])])
        assert list(ud.per_entrance_counts.keys()) == ["src_0"]

    def test_cap_evicts_oldest(self, patch_roi):
        ud = MultiEntranceCallbackClass()
        # Insert exactly one over the cap; oldest (id 0) must be evicted.
        for tid in range(MAX_TRACKED_IDS_PER_ENTRANCE + 1):
            _run_callback(patch_roi, ud, "src_0", [_FakeDetection(track_ids=[tid])])
        tracks = ud.per_entrance_counts["src_0"]
        assert len(tracks) == MAX_TRACKED_IDS_PER_ENTRANCE
        assert 0 not in tracks  # oldest evicted
        assert MAX_TRACKED_IDS_PER_ENTRANCE in tracks  # newest retained

    def test_cap_exact_boundary_no_eviction(self, patch_roi):
        ud = MultiEntranceCallbackClass()
        # Exactly MAX distinct ids => no eviction.
        for tid in range(MAX_TRACKED_IDS_PER_ENTRANCE):
            _run_callback(patch_roi, ud, "src_0", [_FakeDetection(track_ids=[tid])])
        tracks = ud.per_entrance_counts["src_0"]
        assert len(tracks) == MAX_TRACKED_IDS_PER_ENTRANCE
        assert 0 in tracks  # nothing evicted yet

    def test_cap_evicts_lru_not_recently_seen(self, patch_roi):
        ud = MultiEntranceCallbackClass()
        # Fill to cap.
        for tid in range(MAX_TRACKED_IDS_PER_ENTRANCE):
            _run_callback(patch_roi, ud, "src_0", [_FakeDetection(track_ids=[tid])])
        # Re-see id 0 so it is most-recent, then push one new id over the cap.
        _run_callback(patch_roi, ud, "src_0", [_FakeDetection(track_ids=[0])])
        _run_callback(
            patch_roi, ud, "src_0", [_FakeDetection(track_ids=[999999])]
        )
        tracks = ud.per_entrance_counts["src_0"]
        assert len(tracks) == MAX_TRACKED_IDS_PER_ENTRANCE
        # id 0 was refreshed so it survives; id 1 was the true LRU and is evicted.
        assert 0 in tracks
        assert 1 not in tracks
        assert 999999 in tracks

    def test_none_track_id_handled(self, patch_roi):
        # A unique-id object whose get_id() returns None still has ids non-empty,
        # so it is processed: None becomes a valid (single) dict key.
        ud = MultiEntranceCallbackClass()
        _run_callback(patch_roi, ud, "src_0", [_FakeDetection(track_ids=[None])])
        tracks = ud.per_entrance_counts["src_0"]
        assert list(tracks.keys()) == [None]
        # Re-seeing None must not double count.
        _run_callback(patch_roi, ud, "src_0", [_FakeDetection(track_ids=[None])])
        assert len(ud.per_entrance_counts["src_0"]) == 1

    def test_multiple_detections_one_frame(self, patch_roi):
        ud = MultiEntranceCallbackClass()
        dets = [_FakeDetection(track_ids=[i]) for i in (1, 2, 3)]
        _run_callback(patch_roi, ud, "src_0", dets)
        assert set(ud.per_entrance_counts["src_0"].keys()) == {1, 2, 3}


# ===========================================================================
# Entry/exit logging + person_last_entrance transitions
#
# _append_event / _log_event / _log_entrance_change are real methods on
# MultiEntranceTrackerApp. They only touch self.entry_exit_log,
# self.person_last_entrance and self._log_lock, so we bind them onto a tiny
# fake `self` (built without running the heavy __init__) and call them directly.
# ===========================================================================


class _LogState:
    """Minimal stand-in for the parts of MultiEntranceTrackerApp the log
    helpers touch. The real methods are bound onto it via __get__ (MethodType)."""

    def __init__(self):
        self._log_lock = threading.Lock()
        self.entry_exit_log = []
        self.person_last_entrance = {}
        # Bind the *real* unbound methods to this instance.
        self._append_event = MultiEntranceTrackerApp._append_event.__get__(self)
        self._log_event = MultiEntranceTrackerApp._log_event.__get__(self)
        self._log_entrance_change = (
            MultiEntranceTrackerApp._log_entrance_change.__get__(self)
        )


class TestLogEvent:
    def test_append_event_records_fields(self):
        s = _LogState()
        s._log_event("person_x", 0, "entry")
        assert len(s.entry_exit_log) == 1
        ev = s.entry_exit_log[0]
        assert ev["person_id"] == "person_x"
        assert ev["entrance_id"] == 0
        assert ev["event_type"] == "entry"
        assert "timestamp" in ev

    def test_log_event_does_not_touch_last_entrance(self):
        # _log_event is the raw entry/exit logger used for brand-new identities;
        # it must not mutate person_last_entrance (that is _log_entrance_change's job).
        s = _LogState()
        s._log_event("person_x", 2, "entry")
        assert s.person_last_entrance == {}

    def test_empty_log_initial(self):
        s = _LogState()
        assert s.entry_exit_log == []
        assert s.person_last_entrance == {}


class TestEntranceChange:
    def test_first_sighting_records_no_event(self):
        s = _LogState()
        s._log_entrance_change("person_a", 0)
        # First time we see this person: only remember where, no exit/entry.
        assert s.entry_exit_log == []
        assert s.person_last_entrance == {"person_a": 0}

    def test_same_entrance_again_no_event(self):
        s = _LogState()
        s._log_entrance_change("person_a", 0)
        s._log_entrance_change("person_a", 0)
        assert s.entry_exit_log == []
        assert s.person_last_entrance == {"person_a": 0}

    def test_cross_entrance_records_exit_then_entry(self):
        s = _LogState()
        s._log_entrance_change("person_a", 0)  # arrives at entrance 0
        s._log_entrance_change("person_a", 1)  # moves to entrance 1
        assert len(s.entry_exit_log) == 2
        exit_ev, entry_ev = s.entry_exit_log
        assert exit_ev["event_type"] == "exit"
        assert exit_ev["entrance_id"] == 0
        assert exit_ev["person_id"] == "person_a"
        assert entry_ev["event_type"] == "entry"
        assert entry_ev["entrance_id"] == 1
        assert entry_ev["person_id"] == "person_a"
        assert s.person_last_entrance == {"person_a": 1}

    def test_back_and_forth_movements(self):
        s = _LogState()
        s._log_entrance_change("p", 0)
        s._log_entrance_change("p", 1)  # 0 -> 1: exit0, entry1
        s._log_entrance_change("p", 0)  # 1 -> 0: exit1, entry0
        types_seq = [(e["event_type"], e["entrance_id"]) for e in s.entry_exit_log]
        assert types_seq == [
            ("exit", 0),
            ("entry", 1),
            ("exit", 1),
            ("entry", 0),
        ]
        assert s.person_last_entrance == {"p": 0}

    def test_same_person_two_entrances_independent_people(self):
        s = _LogState()
        s._log_entrance_change("alice", 0)
        s._log_entrance_change("bob", 1)
        # Independent people, each first-seen, no events.
        assert s.entry_exit_log == []
        assert s.person_last_entrance == {"alice": 0, "bob": 1}
        # Now alice moves to bob's entrance -> only alice gets exit/entry.
        s._log_entrance_change("alice", 1)
        assert len(s.entry_exit_log) == 2
        assert all(e["person_id"] == "alice" for e in s.entry_exit_log)

    def test_entrance_id_zero_is_not_treated_as_missing(self):
        # entrance 0 is falsy; the code must use `is not None`, not truthiness.
        s = _LogState()
        s._log_entrance_change("p", 0)  # last = 0
        s._log_entrance_change("p", 2)  # 0 -> 2 must still record exit/entry
        assert [e["event_type"] for e in s.entry_exit_log] == ["exit", "entry"]
        assert s.entry_exit_log[0]["entrance_id"] == 0


class TestConcurrentLogging:
    """The log helpers mutate shared state under self._log_lock. Exercise that
    lock under real thread contention and assert no appends are lost."""

    def test_concurrent_appends_no_lost_updates(self):
        s = _LogState()
        n_threads = 8
        per_thread = 200

        def worker(tid):
            for i in range(per_thread):
                s._log_event(f"person_{tid}_{i}", tid, "entry")

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(s.entry_exit_log) == n_threads * per_thread
        # Every event is unique => no overwrites/lost updates.
        ids = {e["person_id"] for e in s.entry_exit_log}
        assert len(ids) == n_threads * per_thread

    def test_concurrent_entrance_changes_consistent(self):
        s = _LogState()
        n_threads = 8
        moves = 100

        def worker(tid):
            person = f"p{tid}"
            for i in range(moves):
                s._log_entrance_change(person, i % 3)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Each thread's person ends at last-written entrance; map is fully populated.
        assert len(s.person_last_entrance) == n_threads
        # exit/entry events come in pairs, so the log length is even.
        assert len(s.entry_exit_log) % 2 == 0
