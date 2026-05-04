"""Unit tests for drone_follow.perf_tracker (pure-logic surface)."""

import io
import logging
import struct

import pytest

from drone_follow.perf_tracker import PerfTracker, _parse_device_utilization


def _encode_hmon_blob(pid: str, utilization: float) -> bytes:
    """Build a minimal HailoRT monitor protobuf blob.

    Layout: field 1 (string) = PID, field 4 (message) {sub-field 2 (fixed64) = utilization}.
    Matches what the real parser walks in _parse_device_utilization.
    """
    pid_bytes = pid.encode("ascii")
    field1 = bytes([0x0A, len(pid_bytes)]) + pid_bytes
    sub2 = bytes([0x11]) + struct.pack("<d", utilization)  # tag (field 2, fixed64)
    field4 = bytes([0x22, len(sub2)]) + sub2  # tag (field 4, length-delimited)
    return field1 + field4


class TestParseDeviceUtilization:
    def test_returns_zero_on_empty(self):
        assert _parse_device_utilization(b"") == 0.0

    def test_returns_zero_on_unrelated_bytes(self):
        # Field 1 string only, no field 4 → no utilization to find.
        assert _parse_device_utilization(b"\x0a\x03abc") == 0.0

    def test_extracts_utilization_double(self):
        blob = _encode_hmon_blob("1234", 73.5)
        assert _parse_device_utilization(blob) == pytest.approx(73.5)

    def test_handles_zero_utilization(self):
        blob = _encode_hmon_blob("1", 0.0)
        assert _parse_device_utilization(blob) == 0.0

    def test_does_not_crash_on_truncated_payload(self):
        blob = _encode_hmon_blob("1234", 50.0)
        # Truncate mid-double — parser must not raise.
        result = _parse_device_utilization(blob[:-3])
        assert isinstance(result, float)


class TestGetStatsInitial:
    def test_zero_when_no_frames(self):
        stats = PerfTracker().get_stats()
        assert stats == {
            "fps": 0.0,
            "latency_ms": 0.0,
            "cpu_percent": 0.0,
            "memory_mb": 0.0,
            "hailo_temp_c": 0.0,
            "hailo_util_percent": 0.0,
        }


class TestFrameTiming:
    def test_latency_recorded(self, monkeypatch):
        pt = PerfTracker()
        # Freeze monotonic so the system-sample branch doesn't fire.
        now = [100.0]
        monkeypatch.setattr("drone_follow.perf_tracker.time.monotonic", lambda: now[0])

        t0 = pt.frame_start()
        now[0] = 100.025  # 25 ms later
        pt.frame_end(t0, ui_state=None)

        stats = pt.get_stats()
        assert stats["latency_ms"] == pytest.approx(25.0, abs=0.1)

    def test_fps_from_frame_spacing(self, monkeypatch):
        pt = PerfTracker()
        now = [0.0]
        monkeypatch.setattr("drone_follow.perf_tracker.time.monotonic", lambda: now[0])

        # 10 frames, 100 ms apart → 9 intervals over 0.9 s = 10 fps.
        for i in range(10):
            now[0] = i * 0.1
            t0 = pt.frame_start()
            pt.frame_end(t0, ui_state=None)

        assert pt.get_stats()["fps"] == pytest.approx(10.0, abs=0.1)

    def test_ui_state_receives_perf_update(self, monkeypatch):
        monkeypatch.setattr("drone_follow.perf_tracker.time.monotonic", lambda: 5.0)
        pt = PerfTracker()
        captured = {}

        class FakeUI:
            def update_perf(self, stats):
                captured.update(stats)

        pt.frame_end(pt.frame_start(), ui_state=FakeUI())
        assert "fps" in captured and "latency_ms" in captured


class TestSystemSamplers:
    def test_sample_cpu_from_proc_stat(self, monkeypatch):
        pt = PerfTracker()
        # First read: idle=100, total sum = 200. Second read: idle=110, total sum = 300.
        # delta_idle = 10, delta_total = 100 → cpu = 100*(1 - 0.1) = 90%.
        readings = iter([
            "cpu  50 0 50 100 0 0 0 0 0 0\n",
            "cpu  100 0 90 110 0 0 0 0 0 0\n",
        ])
        monkeypatch.setattr("builtins.open", lambda *a, **kw: io.StringIO(next(readings)))

        pt._sample_cpu()  # primes baseline
        pt._sample_cpu()  # produces the percentage
        assert pt._cpu_percent == pytest.approx(90.0)

    def test_sample_cpu_swallows_oserror(self, monkeypatch):
        pt = PerfTracker()

        def boom(*_a, **_kw):
            raise OSError("nope")
        monkeypatch.setattr("builtins.open", boom)
        pt._sample_cpu()  # must not raise
        assert pt._cpu_percent == 0.0

    def test_sample_memory_from_proc_status(self, monkeypatch):
        pt = PerfTracker()
        contents = "Name:\tdrone\nVmRSS:\t102400 kB\nVmSize:\t999 kB\n"
        monkeypatch.setattr("builtins.open", lambda *a, **kw: io.StringIO(contents))

        pt._sample_memory()
        assert pt._memory_mb == pytest.approx(100.0)  # 102400 KB / 1024


class TestPeriodicLogging:
    def test_log_perf_emits_after_interval(self, monkeypatch, caplog):
        pt = PerfTracker(log_perf=True)
        now = [0.0]
        monkeypatch.setattr("drone_follow.perf_tracker.time.monotonic", lambda: now[0])

        # Suppress system samplers so we don't touch /proc.
        monkeypatch.setattr(pt, "_sample_cpu", lambda: None)
        monkeypatch.setattr(pt, "_sample_memory", lambda: None)
        monkeypatch.setattr(pt, "_sample_hailo_temp", lambda: None)
        monkeypatch.setattr(pt, "_sample_hailo_utilization", lambda: None)

        with caplog.at_level(logging.INFO, logger="drone_follow.perf_tracker"):
            for i in range(7):  # span >5 s so the periodic log fires
                now[0] = i * 1.0
                pt.frame_end(pt.frame_start(), ui_state=None)

        assert any("[PERF]" in rec.message for rec in caplog.records)
