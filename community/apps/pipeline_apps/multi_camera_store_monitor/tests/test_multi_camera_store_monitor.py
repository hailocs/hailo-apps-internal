"""Pure-Python unit tests for the multi-camera store monitor.

These tests exercise the *real* app logic (no Hailo device, no GStreamer
pipeline, no inference) by:

  1. Stubbing the ``hailo``, ``gi`` and ``gstreamer_app`` modules (plus the
     ``gstreamer_helper_pipelines`` helpers the pipeline module imports at
     import time) so the app modules import cleanly off-device, then importing
     the *real* ``app_callback`` / ``StoreMonitorCallback`` and the real module
     constants.
  2. Driving ``app_callback`` with hand-built fake ROI / detection /
     unique-id objects to cover per-camera person counting, the
     ``person_threshold`` filter, the zone-alert state machine and the periodic
     (lock-guarded) summary gate.

Behaviour under test:
  * Person counting: only detections labelled ``person`` whose confidence is
    ``>= person_threshold`` are counted; current/max/total/frame stats update
    per stream id; multiple streams are tracked independently.
  * ``person_threshold`` filtering: sub-threshold and non-person detections are
    excluded; the boundary (``confidence == threshold``) counts.
  * Periodic summary gate: the check-then-write on ``last_summary_time`` is
    guarded by ``summary_lock`` and fires exactly once per ``SUMMARY_INTERVAL``.
  * Thread-safety / TOCTOU fix: running the real callback from many threads that
    all cross one interval boundary at once yields exactly one summary print
    (no duplicate / garbled output).
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


def _build_hailo_stub():
    mod = types.ModuleType("hailo")
    mod.HAILO_DETECTION = _HAILO_DETECTION
    mod.HAILO_UNIQUE_ID = _HAILO_UNIQUE_ID
    # get_roi_from_buffer is monkeypatched per-test to return our fake ROI.
    mod.get_roi_from_buffer = lambda buffer: buffer
    return mod


class _StubAppCallbackBase:
    """Mimics the real app_callback_class enough for StoreMonitorCallback."""

    def __init__(self):
        self.frame_count = 0
        self.use_frame = False

    def increment(self):
        self.frame_count += 1


class _StubGStreamerApp:
    """Real (non-Mock) base so GStreamerStoreMonitorApp stays a real subclass
    and keeps its own method definitions (a MagicMock base swallows them)."""

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
    "get_source_type",
    "USER_CALLBACK_PIPELINE",
    "TRACKER_PIPELINE",
    "QUEUE",
    "SOURCE_PIPELINE",
    "INFERENCE_PIPELINE",
    "DISPLAY_PIPELINE",
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


# Now import the real app module. This gives us the real person-counting,
# threshold-filter, zone-alert and lock-guarded summary logic.
from community.apps.pipeline_apps.multi_camera_store_monitor.multi_camera_store_monitor import (  # noqa: E402
    PERSON_LABEL,
    SUMMARY_INTERVAL,
    ZONE_ALERT_THRESHOLDS,
    StoreMonitorCallback,
    app_callback,
)
from community.apps.pipeline_apps.multi_camera_store_monitor.multi_camera_store_monitor_pipeline import (  # noqa: E402
    CAMERA_NAMES,
)


# ---------------------------------------------------------------------------
# Fake Hailo object graph for driving the real app_callback.
# ---------------------------------------------------------------------------


class _FakeUniqueId:
    def __init__(self, track_id):
        self._id = track_id

    def get_id(self):
        return self._id


class _FakeDetection:
    """A detection with a label/confidence and optional typed child objects."""

    def __init__(self, label, confidence, track_ids=None):
        self._label = label
        self._confidence = confidence
        self._objects = {
            _HAILO_UNIQUE_ID: [_FakeUniqueId(t) for t in (track_ids or [])],
        }

    def get_label(self):
        return self._label

    def get_confidence(self):
        return self._confidence

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
    """Return a helper that wires a fake ROI into hailo.get_roi_from_buffer.

    The helper returns a non-None buffer sentinel so app_callback proceeds.
    """

    def _set(roi):
        monkeypatch.setattr(
            sys.modules["hailo"], "get_roi_from_buffer", lambda buffer: roi
        )
        return object()

    return _set


def _person(confidence, track_ids=None):
    return _FakeDetection(PERSON_LABEL, confidence, track_ids=track_ids)


def _run(patch_roi, user_data, stream_id, detections):
    buffer = patch_roi(_FakeRoi(stream_id, detections))
    app_callback(element=None, buffer=buffer, user_data=user_data)


def _ud(threshold=0.5, *, never_summary=True):
    """Build a StoreMonitorCallback. By default push last_summary_time far into
    the future so the summary gate never fires during counting tests (keeps the
    counting assertions independent of wall-clock timing)."""
    ud = StoreMonitorCallback(person_threshold=threshold)
    if never_summary:
        # 1 hour in the future => `now - last_summary_time` stays negative.
        ud.last_summary_time += 3600.0
    return ud


# ===========================================================================
# None-buffer guard
# ===========================================================================


class TestNoneBuffer:
    def test_none_buffer_is_noop(self):
        ud = _ud()
        app_callback(element=None, buffer=None, user_data=ud)
        assert dict(ud.current_counts) == {}
        assert dict(ud.max_counts) == {}
        assert dict(ud.total_counts) == {}


# ===========================================================================
# Person counting
# ===========================================================================


class TestPersonCounting:
    def test_counts_persons_above_threshold(self, patch_roi):
        ud = _ud(threshold=0.5)
        dets = [_person(0.9), _person(0.6), _person(0.7)]
        _run(patch_roi, ud, "src_0", dets)
        assert ud.current_counts["src_0"] == 3
        assert ud.max_counts["src_0"] == 3
        assert ud.total_counts["src_0"] == 3
        assert ud.frame_counts_per_camera["src_0"] == 1

    def test_zero_detections(self, patch_roi):
        ud = _ud()
        _run(patch_roi, ud, "src_0", [])
        assert ud.current_counts["src_0"] == 0
        assert ud.max_counts["src_0"] == 0
        assert ud.total_counts["src_0"] == 0
        # Frame still counted even with no persons.
        assert ud.frame_counts_per_camera["src_0"] == 1

    def test_current_count_reflects_latest_frame(self, patch_roi):
        ud = _ud()
        _run(patch_roi, ud, "src_0", [_person(0.9), _person(0.9), _person(0.9)])
        assert ud.current_counts["src_0"] == 3
        # Next frame has fewer people: current drops, max stays at the peak.
        _run(patch_roi, ud, "src_0", [_person(0.9)])
        assert ud.current_counts["src_0"] == 1
        assert ud.max_counts["src_0"] == 3

    def test_max_count_tracks_peak(self, patch_roi):
        ud = _ud()
        _run(patch_roi, ud, "src_0", [_person(0.9)])
        _run(patch_roi, ud, "src_0", [_person(0.9), _person(0.9)])
        _run(patch_roi, ud, "src_0", [])
        assert ud.max_counts["src_0"] == 2

    def test_total_and_frame_counts_accumulate(self, patch_roi):
        ud = _ud()
        _run(patch_roi, ud, "src_0", [_person(0.9), _person(0.9)])  # +2
        _run(patch_roi, ud, "src_0", [_person(0.9)])               # +1
        _run(patch_roi, ud, "src_0", [])                           # +0
        assert ud.total_counts["src_0"] == 3
        assert ud.frame_counts_per_camera["src_0"] == 3
        # Average over frames = 3 / 3 = 1.0 (the value the summary prints).
        assert ud.total_counts["src_0"] / ud.frame_counts_per_camera["src_0"] == 1.0

    def test_detection_with_track_id_still_counts(self, patch_roi):
        # The track-id branch only logs; it must not change the count.
        ud = _ud()
        _run(patch_roi, ud, "src_0", [_person(0.9, track_ids=[7])])
        assert ud.current_counts["src_0"] == 1


# ===========================================================================
# person_threshold filtering
# ===========================================================================


class TestThresholdFiltering:
    def test_below_threshold_not_counted(self, patch_roi):
        ud = _ud(threshold=0.5)
        _run(patch_roi, ud, "src_0", [_person(0.4), _person(0.49)])
        assert ud.current_counts["src_0"] == 0

    def test_at_threshold_boundary_counts(self, patch_roi):
        # confidence >= threshold => the exact boundary value counts.
        ud = _ud(threshold=0.5)
        _run(patch_roi, ud, "src_0", [_person(0.5)])
        assert ud.current_counts["src_0"] == 1

    def test_just_above_threshold_counts(self, patch_roi):
        ud = _ud(threshold=0.5)
        _run(patch_roi, ud, "src_0", [_person(0.5001)])
        assert ud.current_counts["src_0"] == 1

    def test_mixed_above_and_below(self, patch_roi):
        ud = _ud(threshold=0.6)
        dets = [_person(0.9), _person(0.5), _person(0.61), _person(0.59)]
        _run(patch_roi, ud, "src_0", dets)
        # Only 0.9 and 0.61 are >= 0.6.
        assert ud.current_counts["src_0"] == 2

    def test_non_person_labels_excluded(self, patch_roi):
        ud = _ud(threshold=0.5)
        dets = [
            _FakeDetection("car", 0.99),
            _FakeDetection("dog", 0.99),
            _person(0.99),
        ]
        _run(patch_roi, ud, "src_0", dets)
        assert ud.current_counts["src_0"] == 1

    def test_higher_threshold_filters_more(self, patch_roi):
        dets = [_person(0.55), _person(0.75), _person(0.95)]
        ud_low = _ud(threshold=0.5)
        ud_high = _ud(threshold=0.8)
        _run(patch_roi, ud_low, "src_0", list(dets))
        _run(patch_roi, ud_high, "src_0", list(dets))
        assert ud_low.current_counts["src_0"] == 3
        assert ud_high.current_counts["src_0"] == 1

    def test_threshold_default_is_half(self):
        assert StoreMonitorCallback().person_threshold == 0.5


# ===========================================================================
# Multiple streams tracked independently
# ===========================================================================


class TestMultipleStreams:
    def test_streams_counted_independently(self, patch_roi):
        ud = _ud()
        _run(patch_roi, ud, "src_0", [_person(0.9)])
        _run(patch_roi, ud, "src_1", [_person(0.9), _person(0.9)])
        _run(patch_roi, ud, "src_2", [])
        assert ud.current_counts["src_0"] == 1
        assert ud.current_counts["src_1"] == 2
        assert ud.current_counts["src_2"] == 0
        assert ud.frame_counts_per_camera["src_0"] == 1
        assert ud.frame_counts_per_camera["src_1"] == 1
        assert ud.frame_counts_per_camera["src_2"] == 1

    def test_max_per_stream_isolated(self, patch_roi):
        ud = _ud()
        _run(patch_roi, ud, "src_0", [_person(0.9), _person(0.9), _person(0.9)])
        _run(patch_roi, ud, "src_1", [_person(0.9)])
        assert ud.max_counts["src_0"] == 3
        assert ud.max_counts["src_1"] == 1

    def test_unknown_stream_id_still_tracked(self, patch_roi):
        # A stream id not in CAMERA_NAMES is still counted (camera_name falls
        # back to the raw stream id, but counting is unaffected).
        ud = _ud()
        _run(patch_roi, ud, "src_99", [_person(0.9)])
        assert ud.current_counts["src_99"] == 1
        assert "src_99" not in CAMERA_NAMES


# ===========================================================================
# Zone-alert state machine
# ===========================================================================


class TestZoneAlerts:
    def test_alert_activates_at_threshold(self, patch_roi):
        ud = _ud()
        thr = ZONE_ALERT_THRESHOLDS["src_1"]  # checkout -> 5
        _run(patch_roi, ud, "src_1", [_person(0.9) for _ in range(thr)])
        assert ud.alert_active["src_1"] is True

    def test_alert_not_active_below_threshold(self, patch_roi):
        ud = _ud()
        thr = ZONE_ALERT_THRESHOLDS["src_1"]  # 5
        _run(patch_roi, ud, "src_1", [_person(0.9) for _ in range(thr - 1)])
        assert ud.alert_active["src_1"] is False

    def test_alert_clears_when_count_drops(self, patch_roi):
        ud = _ud()
        thr = ZONE_ALERT_THRESHOLDS["src_2"]  # stockroom -> 3
        _run(patch_roi, ud, "src_2", [_person(0.9) for _ in range(thr)])
        assert ud.alert_active["src_2"] is True
        _run(patch_roi, ud, "src_2", [_person(0.9)])  # below threshold
        assert ud.alert_active["src_2"] is False

    def test_unknown_stream_uses_default_threshold(self, patch_roi):
        # ZONE_ALERT_THRESHOLDS.get(stream_id, 10) => default 10.
        ud = _ud()
        _run(patch_roi, ud, "src_99", [_person(0.9) for _ in range(9)])
        assert ud.alert_active["src_99"] is False
        _run(patch_roi, ud, "src_99", [_person(0.9) for _ in range(10)])
        assert ud.alert_active["src_99"] is True


# ===========================================================================
# Periodic summary gate (single-threaded timing semantics)
# ===========================================================================


class TestSummaryGate:
    def test_summary_does_not_fire_before_interval(self, patch_roi, capsys):
        ud = _ud()  # last_summary_time pushed 1h into the future
        _run(patch_roi, ud, "src_0", [_person(0.9)])
        out = capsys.readouterr().out
        assert "Store Monitor Summary" not in out

    def test_summary_fires_once_when_interval_elapsed(self, patch_roi, capsys):
        ud = StoreMonitorCallback()
        # Force the interval to have already elapsed.
        ud.last_summary_time -= SUMMARY_INTERVAL + 1.0
        _run(patch_roi, ud, "src_0", [_person(0.9)])
        out = capsys.readouterr().out
        assert out.count("Store Monitor Summary") == 1

    def test_summary_resets_timer_so_next_frame_silent(self, patch_roi, capsys):
        ud = StoreMonitorCallback()
        ud.last_summary_time -= SUMMARY_INTERVAL + 1.0
        _run(patch_roi, ud, "src_0", [_person(0.9)])   # fires, resets timer
        capsys.readouterr()                            # drain
        _run(patch_roi, ud, "src_0", [_person(0.9)])   # too soon -> silent
        out = capsys.readouterr().out
        assert "Store Monitor Summary" not in out

    def test_summary_lists_each_camera_once(self, patch_roi, capsys):
        ud = StoreMonitorCallback()
        # Populate three streams without triggering the summary yet.
        ud.last_summary_time += 3600.0
        _run(patch_roi, ud, "src_0", [_person(0.9)])
        _run(patch_roi, ud, "src_1", [_person(0.9), _person(0.9)])
        _run(patch_roi, ud, "src_2", [])
        capsys.readouterr()
        # Now force the gate open on the next frame.
        ud.last_summary_time = ud.last_summary_time - 3600.0 - SUMMARY_INTERVAL - 1.0
        _run(patch_roi, ud, "src_0", [_person(0.9)])
        out = capsys.readouterr().out
        assert out.count("Store Monitor Summary") == 1
        for cam in ("Entrance", "Checkout", "Stockroom"):
            assert out.count(cam) == 1


# ===========================================================================
# Thread-safety: the TOCTOU fix on the summary gate (summary_lock).
#
# Many stream threads call the real app_callback simultaneously, all crossing
# the same interval boundary. The lock guards the check-then-write on
# last_summary_time so EXACTLY ONE thread prints the summary — no duplicate or
# interleaved/garbled output.
# ===========================================================================


class TestSummaryThreadSafety:
    def test_single_summary_under_concurrent_threads(self, monkeypatch, capsys):
        n_threads = 32
        ud = StoreMonitorCallback()
        # The interval has already elapsed for every thread.
        ud.last_summary_time -= SUMMARY_INTERVAL + 1.0

        # Each thread sees its own ROI (distinct stream id) but a shared ud.
        # get_roi_from_buffer must be thread-safe: derive the ROI from the
        # buffer object the thread passes in (no shared monkeypatched closure).
        def _roi_from_buffer(buffer):
            return buffer

        monkeypatch.setattr(
            sys.modules["hailo"], "get_roi_from_buffer", _roi_from_buffer
        )

        start = threading.Barrier(n_threads)

        def worker(i):
            roi = _FakeRoi(f"src_{i}", [_person(0.9)])
            start.wait()  # maximize the chance all threads race the gate together
            app_callback(element=None, buffer=roi, user_data=ud)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        out = capsys.readouterr().out
        # Exactly one summary block, despite all threads crossing the boundary.
        assert out.count("Store Monitor Summary") == 1
        # The single banner line appears intact (not interleaved with another).
        assert out.count("-----------------------------") == 1

    def test_all_threads_counted_no_lost_updates(self, monkeypatch):
        # Independent of the summary: each thread updates its own stream id, so
        # every per-stream count must be recorded (defaultdict writes to distinct
        # keys do not race destructively here).
        n_threads = 16
        ud = StoreMonitorCallback()
        ud.last_summary_time += 3600.0  # keep summary quiet

        monkeypatch.setattr(
            sys.modules["hailo"], "get_roi_from_buffer", lambda buffer: buffer
        )
        start = threading.Barrier(n_threads)

        def worker(i):
            roi = _FakeRoi(f"src_{i}", [_person(0.9), _person(0.9)])
            start.wait()
            app_callback(element=None, buffer=roi, user_data=ud)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(ud.current_counts) == n_threads
        assert all(v == 2 for v in ud.current_counts.values())
        assert len(ud.frame_counts_per_camera) == n_threads
