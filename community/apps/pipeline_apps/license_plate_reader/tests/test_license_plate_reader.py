"""Pure-Python unit tests for the License Plate Reader (LPR) app.

Covers the pure-Python logic in ``PlateReaderCallbackData``:
  - CSV logging: header written once, one row per recorded plate, the
    on-disk format, and the lock-guarded / idempotent ``close()``.
  - Confidence-threshold filtering for plate detections (the same
    ``confidence > threshold`` rule the GStreamer callback applies).
  - Plate-string normalization (whitespace strip) and the per-frame /
    running-log bookkeeping.
  - Edge cases: empty/whitespace plate text, ``None`` confidence,
    threshold boundary, logging disabled, and concurrent writers
    exercising the ``_csv_lock`` (no lost or corrupted rows).

No Hailo device, GStreamer pipeline, or inference is exercised. The Hailo
C++ / GStreamer modules (``gi``, ``hailo``, ``cv2``,
``gstreamer_app``) plus this app's own pipeline module are stubbed in
``sys.modules`` *before* the app module is imported, so the suite runs
headless in its own process.
"""

import csv
import os
import sys
import threading
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.community


# ---------------------------------------------------------------------------
# Make the repo root importable so ``community.apps...`` resolves regardless
# of the directory pytest is launched from.
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..")
)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ---------------------------------------------------------------------------
# Stub the device / GStreamer / native dependencies BEFORE importing the app.
# ---------------------------------------------------------------------------
for _mod_name in [
    "gi",
    "gi.repository",
    "gi.repository.Gst",
    "cv2",
    "hailo",
    "setproctitle",
    "hailo_apps.python.core.common.buffer_utils",
    "hailo_apps.python.core.common.core",
    "hailo_apps.python.core.gstreamer.gstreamer_app",
    # The app's own pipeline module pulls in the full GStreamerApp stack; the
    # callback-data logic under test does not need it, so stub it out wholesale.
    "community.apps.pipeline_apps.license_plate_reader.license_plate_reader_pipeline",
]:
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = MagicMock()

# gi.require_version(...) must be a no-op rather than a MagicMock call that
# records args; the app calls it at import time.
sys.modules["gi"].require_version = lambda *a, **kw: None


class _StubAppCallbackBase:
    """Minimal stand-in for ``app_callback_class`` used as the LPR base class.

    Provides just the surface ``PlateReaderCallbackData`` relies on through
    ``super().__init__()`` and the few attributes the callback touches.
    """

    def __init__(self):
        self.frame_count = 0
        self.use_frame = False

    def get_count(self):
        return self.frame_count

    def increment(self):
        self.frame_count += 1

    def set_frame(self, frame):
        self._frame = frame


sys.modules[
    "hailo_apps.python.core.gstreamer.gstreamer_app"
].app_callback_class = _StubAppCallbackBase

# Give the stubbed pipeline module a real (no-op) class object so the
# ``from ... import GStreamerLicensePlateReaderApp`` line resolves to something
# importable rather than a MagicMock attribute (harmless either way).
sys.modules[
    "community.apps.pipeline_apps.license_plate_reader.license_plate_reader_pipeline"
].GStreamerLicensePlateReaderApp = MagicMock()


from community.apps.pipeline_apps.license_plate_reader.license_plate_reader import (  # noqa: E402
    PlateReaderCallbackData,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
class _FakeBBox:
    """A bbox is opaque to the CSV logic — it is only stored, never serialized."""

    def __init__(self, xmin=0.1, ymin=0.1, w=0.2, h=0.2):
        self._x, self._y, self._w, self._h = xmin, ymin, w, h

    def xmin(self):
        return self._x

    def ymin(self):
        return self._y

    def width(self):
        return self._w

    def height(self):
        return self._h


def _read_csv_rows(path):
    with open(path, newline="") as fh:
        return list(csv.reader(fh))


# Mirrors the confidence filter the GStreamer callback applies
# (license_plate_reader.py: ``confidence > user_data.confidence_threshold``).
def _passes_threshold(confidence, threshold):
    return confidence > threshold


# ---------------------------------------------------------------------------
# CSV header + basic row writing
# ---------------------------------------------------------------------------
class TestCsvLogging:
    def test_header_written_on_init(self, tmp_path):
        log = tmp_path / "plates.csv"
        cb = PlateReaderCallbackData(log_file=str(log))
        cb.close()
        rows = _read_csv_rows(log)
        assert rows[0] == ["timestamp", "plate_text", "confidence"]

    def test_header_written_exactly_once(self, tmp_path):
        log = tmp_path / "plates.csv"
        cb = PlateReaderCallbackData(log_file=str(log))
        cb.add_plate_result("ABC123", 0.9, _FakeBBox())
        cb.add_plate_result("XYZ789", 0.8, _FakeBBox())
        cb.close()
        rows = _read_csv_rows(log)
        # Exactly one header row.
        header_count = sum(
            1 for r in rows if r == ["timestamp", "plate_text", "confidence"]
        )
        assert header_count == 1

    def test_add_plate_writes_a_row(self, tmp_path):
        log = tmp_path / "plates.csv"
        cb = PlateReaderCallbackData(log_file=str(log))
        cb.add_plate_result("ABC123", 0.876, _FakeBBox())
        cb.close()
        rows = _read_csv_rows(log)
        assert len(rows) == 2  # header + 1 data row
        ts, text, conf = rows[1]
        assert text == "ABC123"
        # confidence formatted to 4 decimals by the app
        assert conf == "0.8760"
        assert ts  # non-empty ISO timestamp

    def test_multiple_rows_in_order(self, tmp_path):
        log = tmp_path / "plates.csv"
        cb = PlateReaderCallbackData(log_file=str(log))
        plates = [("AAA111", 0.91), ("BBB222", 0.55), ("CCC333", 0.42)]
        for text, conf in plates:
            cb.add_plate_result(text, conf, _FakeBBox())
        cb.close()
        rows = _read_csv_rows(log)
        data = rows[1:]
        assert [r[1] for r in data] == ["AAA111", "BBB222", "CCC333"]
        assert [r[2] for r in data] == ["0.9100", "0.5500", "0.4200"]

    def test_rows_flushed_before_close(self, tmp_path):
        # add_plate_result flushes each write, so rows are readable even
        # before close() (important for crash resilience / live tailing).
        log = tmp_path / "plates.csv"
        cb = PlateReaderCallbackData(log_file=str(log))
        cb.add_plate_result("LIVE01", 0.7, _FakeBBox())
        rows_before_close = _read_csv_rows(log)
        assert rows_before_close[1][1] == "LIVE01"
        cb.close()

    def test_data_row_count_matches_recorded_plates(self, tmp_path):
        log = tmp_path / "plates.csv"
        cb = PlateReaderCallbackData(log_file=str(log))
        for i in range(25):
            cb.add_plate_result(f"P{i:04d}", 0.5, _FakeBBox())
        cb.close()
        rows = _read_csv_rows(log)
        assert len(rows) == 25 + 1  # +1 header


# ---------------------------------------------------------------------------
# In-memory bookkeeping (plate_results vs plate_log)
# ---------------------------------------------------------------------------
class TestInMemoryLog:
    def test_add_appends_to_both_logs(self):
        cb = PlateReaderCallbackData(log_file=None)
        cb.add_plate_result("ABC123", 0.9, _FakeBBox())
        assert len(cb.get_plate_results()) == 1
        assert len(cb.get_plate_log()) == 1
        entry = cb.get_plate_results()[0]
        assert entry["plate_text"] == "ABC123"
        assert entry["confidence"] == 0.9
        assert "timestamp" in entry

    def test_clear_plate_results_keeps_running_log(self):
        cb = PlateReaderCallbackData(log_file=None)
        cb.add_plate_result("ABC123", 0.9, _FakeBBox())
        cb.add_plate_result("XYZ789", 0.8, _FakeBBox())
        cb.clear_plate_results()
        # Per-frame buffer cleared...
        assert cb.get_plate_results() == []
        # ...but the cumulative log persists.
        assert len(cb.get_plate_log()) == 2

    def test_running_log_accumulates_across_frames(self):
        cb = PlateReaderCallbackData(log_file=None)
        for frame in range(3):
            cb.clear_plate_results()
            cb.add_plate_result(f"FRAME{frame}", 0.6, _FakeBBox())
        assert len(cb.get_plate_log()) == 3
        assert len(cb.get_plate_results()) == 1  # only last frame's

    def test_bbox_is_stored_verbatim(self):
        cb = PlateReaderCallbackData(log_file=None)
        bbox = _FakeBBox(xmin=0.3)
        cb.add_plate_result("ABC123", 0.9, bbox)
        assert cb.get_plate_results()[0]["bbox"] is bbox


# ---------------------------------------------------------------------------
# Logging disabled (log_file=None)
# ---------------------------------------------------------------------------
class TestLoggingDisabled:
    def test_no_writer_when_log_file_none(self):
        cb = PlateReaderCallbackData(log_file=None)
        assert cb._csv_writer is None
        assert cb._csv_file is None

    def test_add_plate_without_logging_does_not_raise(self):
        cb = PlateReaderCallbackData(log_file=None)
        cb.add_plate_result("ABC123", 0.9, _FakeBBox())  # must not raise
        assert len(cb.get_plate_log()) == 1

    def test_close_without_logging_is_safe(self):
        cb = PlateReaderCallbackData(log_file=None)
        cb.close()  # must not raise
        cb.close()  # still safe twice


# ---------------------------------------------------------------------------
# close() — idempotent + lock-guarded
# ---------------------------------------------------------------------------
class TestClose:
    def test_close_is_idempotent(self, tmp_path):
        log = tmp_path / "plates.csv"
        cb = PlateReaderCallbackData(log_file=str(log))
        cb.add_plate_result("ABC123", 0.9, _FakeBBox())
        cb.close()
        assert cb._csv_file is None
        assert cb._csv_writer is None
        # Second close must be a no-op, not an error.
        cb.close()
        cb.close()

    def test_close_finalizes_file_handle(self, tmp_path):
        log = tmp_path / "plates.csv"
        cb = PlateReaderCallbackData(log_file=str(log))
        cb.add_plate_result("ABC123", 0.9, _FakeBBox())
        cb.close()
        # File is fully written and re-readable after close.
        rows = _read_csv_rows(log)
        assert rows[1][1] == "ABC123"

    def test_add_after_close_does_not_write_or_crash(self, tmp_path):
        log = tmp_path / "plates.csv"
        cb = PlateReaderCallbackData(log_file=str(log))
        cb.close()
        # After close the writer is None, so this only touches the in-memory
        # log and must not raise (lock guards the None-writer branch).
        cb.add_plate_result("AFTER", 0.9, _FakeBBox())
        rows = _read_csv_rows(log)
        assert len(rows) == 1  # header only; no data row written post-close
        assert len(cb.get_plate_log()) == 1


# ---------------------------------------------------------------------------
# Confidence-threshold filtering
# ---------------------------------------------------------------------------
class TestConfidenceThreshold:
    def test_default_threshold(self):
        cb = PlateReaderCallbackData(log_file=None)
        assert cb.confidence_threshold == pytest.approx(0.12)

    def test_configurable_threshold(self):
        cb = PlateReaderCallbackData(log_file=None, confidence_threshold=0.5)
        assert cb.confidence_threshold == pytest.approx(0.5)

    def test_below_threshold_filtered_out(self):
        cb = PlateReaderCallbackData(log_file=None, confidence_threshold=0.5)
        assert _passes_threshold(0.49, cb.confidence_threshold) is False

    def test_above_threshold_passes(self):
        cb = PlateReaderCallbackData(log_file=None, confidence_threshold=0.5)
        assert _passes_threshold(0.51, cb.confidence_threshold) is True

    def test_at_threshold_is_filtered(self):
        # The app uses strict ``>``, so a value exactly at the threshold does
        # NOT pass (boundary behavior).
        cb = PlateReaderCallbackData(log_file=None, confidence_threshold=0.5)
        assert _passes_threshold(0.5, cb.confidence_threshold) is False

    def test_default_low_threshold_passes_noisy_detections(self):
        cb = PlateReaderCallbackData(log_file=None)  # 0.12
        assert _passes_threshold(0.13, cb.confidence_threshold) is True
        assert _passes_threshold(0.11, cb.confidence_threshold) is False

    def test_filtered_detection_is_not_logged(self, tmp_path):
        # Simulate the callback's filter: only pass-through detections get
        # recorded via add_plate_result.
        log = tmp_path / "plates.csv"
        cb = PlateReaderCallbackData(log_file=str(log), confidence_threshold=0.5)
        candidates = [("LOW", 0.4), ("EDGE", 0.5), ("HIGH", 0.95)]
        for text, conf in candidates:
            if _passes_threshold(conf, cb.confidence_threshold):
                cb.add_plate_result(text, conf, _FakeBBox())
        cb.close()
        rows = _read_csv_rows(log)
        logged = [r[1] for r in rows[1:]]
        assert logged == ["HIGH"]  # LOW filtered, EDGE at-boundary filtered


# ---------------------------------------------------------------------------
# Plate-string normalization
# ---------------------------------------------------------------------------
class TestPlateNormalization:
    def test_whitespace_stripped_before_logging(self, tmp_path):
        # The callback records plate_text.strip(); emulate that contract.
        log = tmp_path / "plates.csv"
        cb = PlateReaderCallbackData(log_file=str(log))
        raw = "  ABC 123  "
        cb.add_plate_result(raw.strip(), 0.9, _FakeBBox())
        cb.close()
        rows = _read_csv_rows(log)
        assert rows[1][1] == "ABC 123"

    def test_empty_after_strip_is_skipped_by_caller(self, tmp_path):
        # The callback guards ``if plate_text and plate_text.strip()`` before
        # recording — emulate that an all-whitespace plate is never logged.
        log = tmp_path / "plates.csv"
        cb = PlateReaderCallbackData(log_file=str(log))
        for raw in ["   ", "", "\t\n", "REAL01"]:
            if raw and raw.strip():
                cb.add_plate_result(raw.strip(), 0.9, _FakeBBox())
        cb.close()
        rows = _read_csv_rows(log)
        assert [r[1] for r in rows[1:]] == ["REAL01"]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------
class TestEdgeCases:
    def test_empty_plate_text_written_verbatim_if_forced(self, tmp_path):
        # add_plate_result itself does not re-validate; if an empty string is
        # passed it is written as an empty field (the caller is responsible
        # for the non-empty guard).
        log = tmp_path / "plates.csv"
        cb = PlateReaderCallbackData(log_file=str(log))
        cb.add_plate_result("", 0.9, _FakeBBox())
        cb.close()
        rows = _read_csv_rows(log)
        assert rows[1][1] == ""

    def test_none_confidence_stored_when_logging_disabled(self):
        # With logging disabled the CSV format branch is skipped, so a None
        # confidence is simply stored on the in-memory entry without error.
        cb = PlateReaderCallbackData(log_file=None)
        cb.add_plate_result("ABC123", None, _FakeBBox())
        assert cb.get_plate_log()[0]["confidence"] is None

    def test_none_confidence_raises_when_logging(self, tmp_path):
        log = tmp_path / "plates.csv"
        cb = PlateReaderCallbackData(log_file=str(log))
        with pytest.raises(TypeError):
            cb.add_plate_result("ABC123", None, _FakeBBox())
        cb.close()

    def test_zero_confidence_formats(self, tmp_path):
        log = tmp_path / "plates.csv"
        cb = PlateReaderCallbackData(log_file=str(log))
        cb.add_plate_result("ZERO", 0.0, _FakeBBox())
        cb.close()
        rows = _read_csv_rows(log)
        assert rows[1][2] == "0.0000"

    def test_plate_with_comma_is_quoted_in_csv(self, tmp_path):
        # csv.writer must quote a field containing the delimiter so the row
        # round-trips back to a single field.
        log = tmp_path / "plates.csv"
        cb = PlateReaderCallbackData(log_file=str(log))
        cb.add_plate_result("AB,CD", 0.9, _FakeBBox())
        cb.close()
        rows = _read_csv_rows(log)
        assert rows[1][1] == "AB,CD"
        assert len(rows[1]) == 3  # still exactly 3 fields after parsing

    def test_failed_log_open_degrades_gracefully(self, tmp_path):
        # Pointing the log at a path inside a non-existent directory triggers
        # the OSError branch in __init__: logging disables itself rather than
        # crashing the app.
        bad_path = tmp_path / "no_such_dir" / "plates.csv"
        cb = PlateReaderCallbackData(log_file=str(bad_path))
        assert cb._csv_writer is None
        assert cb._csv_file is None
        # And recording still works (in-memory only).
        cb.add_plate_result("ABC123", 0.9, _FakeBBox())
        assert len(cb.get_plate_log()) == 1
        cb.close()


# ---------------------------------------------------------------------------
# Concurrency: the _csv_lock must serialize writers so no row is lost or
# corrupted, and close() racing with writes stays safe.
# ---------------------------------------------------------------------------
class TestConcurrency:
    def test_concurrent_writers_no_lost_or_corrupt_rows(self, tmp_path):
        log = tmp_path / "plates.csv"
        cb = PlateReaderCallbackData(log_file=str(log))

        n_threads = 8
        per_thread = 50
        barrier = threading.Barrier(n_threads)

        def worker(tid):
            barrier.wait()
            for i in range(per_thread):
                cb.add_plate_result(f"T{tid:02d}-{i:03d}", 0.5, _FakeBBox())

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        cb.close()

        rows = _read_csv_rows(log)
        data = rows[1:]
        # No lost rows.
        assert len(data) == n_threads * per_thread
        # Every row is well-formed (exactly 3 fields, no interleaved/torn
        # writes) and every expected plate id appears exactly once.
        for r in data:
            assert len(r) == 3
        ids = sorted(r[1] for r in data)
        expected = sorted(
            f"T{t:02d}-{i:03d}" for t in range(n_threads) for i in range(per_thread)
        )
        assert ids == expected

    def test_close_racing_with_writes_is_safe(self, tmp_path):
        # A writer thread keeps adding while the main thread closes; the lock
        # must prevent writing to a closed handle. No exception may escape.
        log = tmp_path / "plates.csv"
        cb = PlateReaderCallbackData(log_file=str(log))

        errors = []
        stop = threading.Event()

        def writer():
            i = 0
            while not stop.is_set():
                try:
                    cb.add_plate_result(f"R{i:05d}", 0.5, _FakeBBox())
                    i += 1
                except Exception as exc:  # pragma: no cover - failure path
                    errors.append(exc)
                    break

        t = threading.Thread(target=writer)
        t.start()
        # Let a few writes land, then close underneath the writer.
        for _ in range(1000):
            if len(cb.get_plate_log()) > 5:
                break
        cb.close()
        stop.set()
        t.join(timeout=5)

        assert not t.is_alive()
        assert errors == []  # writing after close must be a guarded no-op
        # File is intact and parseable.
        rows = _read_csv_rows(log)
        assert rows[0] == ["timestamp", "plate_text", "confidence"]
        for r in rows[1:]:
            assert len(r) == 3
