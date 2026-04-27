"""Lightweight performance tracker — system metrics + frame timing.

Reusable across pipeline adapters. No Hailo or GStreamer imports.
"""

import logging
import os
import struct
import time
from collections import deque

LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Hailo monitor helpers
# ---------------------------------------------------------------------------

def _parse_device_utilization(data: bytes) -> float:
    """Extract device utilization (%) from a Hailo monitor protobuf file.

    The monitor file uses protobuf encoding. Field 4 is the device info
    message containing sub-field 2 as a fixed64 (double) with the device
    NN core utilization percentage.

    Returns 0.0 if the field cannot be found.
    """
    pos = 0
    while pos < len(data):
        if pos >= len(data):
            break
        # Read varint tag
        tag_byte = data[pos]
        pos += 1
        field_number = tag_byte >> 3
        wire_type = tag_byte & 0x7

        if wire_type == 0:  # varint
            while pos < len(data) and data[pos] & 0x80:
                pos += 1
            pos += 1
        elif wire_type == 1:  # fixed64
            pos += 8
        elif wire_type == 5:  # fixed32
            pos += 4
        elif wire_type == 2:  # length-delimited
            length = 0
            shift = 0
            while pos < len(data):
                b = data[pos]
                pos += 1
                length |= (b & 0x7F) << shift
                if not (b & 0x80):
                    break
                shift += 7
            if field_number == 4:
                # Parse sub-fields of the device info message
                end = pos + length
                sub_pos = pos
                while sub_pos < end:
                    sub_tag = data[sub_pos]
                    sub_pos += 1
                    sub_field = sub_tag >> 3
                    sub_wire = sub_tag & 0x7
                    if sub_wire == 1 and sub_field == 2:  # fixed64 = utilization
                        return struct.unpack("<d", data[sub_pos:sub_pos + 8])[0]
                    elif sub_wire == 0:
                        while sub_pos < end and data[sub_pos] & 0x80:
                            sub_pos += 1
                        sub_pos += 1
                    elif sub_wire == 1:
                        sub_pos += 8
                    elif sub_wire == 5:
                        sub_pos += 4
                    elif sub_wire == 2:
                        sub_len = 0
                        s = 0
                        while sub_pos < end:
                            b = data[sub_pos]
                            sub_pos += 1
                            sub_len |= (b & 0x7F) << s
                            if not (b & 0x80):
                                break
                            s += 7
                        sub_pos += sub_len
                    else:
                        break
            pos += length
        else:
            break
    return 0.0


# ---------------------------------------------------------------------------
# Performance tracker
# ---------------------------------------------------------------------------

class PerfTracker:
    """Lightweight performance tracker for pipeline callbacks."""

    def __init__(self):
        self._frame_times = deque(maxlen=60)
        self._latencies = deque(maxlen=60)
        # CPU sampling state
        self._last_cpu_total = 0
        self._last_cpu_idle = 0
        self._cpu_percent = 0.0
        # Hailo device handle (lazy)
        self._hailo_device = None
        self._hailo_init_tried = False
        # Cached values
        self._hailo_temp = 0.0
        self._hailo_utilization = 0.0
        self._memory_mb = 0.0
        self._last_system_sample = 0.0

    def frame_start(self):
        return time.monotonic()

    def frame_end(self, t0, ui_state):
        now = time.monotonic()
        self._frame_times.append(now)
        self._latencies.append((now - t0) * 1000)
        # Sample system metrics every ~2 seconds
        if now - self._last_system_sample > 2.0:
            self._last_system_sample = now
            self._sample_cpu()
            self._sample_memory()
            self._sample_hailo_temp()
            self._sample_hailo_utilization()
        # Push to UI every frame (values are cached between system samples)
        if ui_state is not None:
            ui_state.update_perf(self.get_stats())

    def get_stats(self):
        ft = self._frame_times
        if len(ft) > 1:
            fps = (len(ft) - 1) / (ft[-1] - ft[0])
        else:
            fps = 0.0
        lat = sum(self._latencies) / len(self._latencies) if self._latencies else 0.0
        return {
            "fps": round(fps, 1),
            "latency_ms": round(lat, 1),
            "cpu_percent": round(self._cpu_percent, 1),
            "memory_mb": round(self._memory_mb, 0),
            "hailo_temp_c": round(self._hailo_temp, 1),
            "hailo_util_percent": round(self._hailo_utilization, 1),
        }

    # -- System sampling helpers --

    def _sample_cpu(self):
        try:
            with open("/proc/stat", "r") as f:
                parts = f.readline().split()
            total = sum(int(x) for x in parts[1:8])
            idle = int(parts[4])
            d_total = total - self._last_cpu_total
            d_idle = idle - self._last_cpu_idle
            if d_total > 0:
                self._cpu_percent = 100.0 * (1.0 - d_idle / d_total)
            self._last_cpu_total = total
            self._last_cpu_idle = idle
        except (OSError, ValueError, IndexError):
            pass

    def _sample_memory(self):
        try:
            with open("/proc/self/status", "r") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        self._memory_mb = int(line.split()[1]) / 1024.0
                        return
        except (OSError, ValueError, IndexError):
            pass

    def _sample_hailo_temp(self):
        if not self._hailo_init_tried:
            self._hailo_init_tried = True
            try:
                from hailo_platform import Device
                self._hailo_device = Device()
            except (ImportError, OSError):
                pass
        if self._hailo_device is None:
            return
        try:
            temp = self._hailo_device.control.get_chip_temperature()
            self._hailo_temp = temp.ts0_temperature
        except (OSError, AttributeError):
            pass

    def _sample_hailo_utilization(self):
        """Read NN core utilization from the Hailo monitor protobuf file.

        Requires HAILO_MONITOR=1 in the process environment. The HailoRT
        runtime writes a protobuf file per process under /tmp/hmon_files/
        containing device utilization as a double in field 4.2.
        """
        try:
            hmon_dir = "/tmp/hmon_files"
            pid = str(os.getpid())
            for fname in os.listdir(hmon_dir):
                fpath = os.path.join(hmon_dir, fname)
                with open(fpath, "rb") as f:
                    data = f.read()
                # Quick check: file starts with field 1 (tag 0x0a) containing our PID
                if len(data) < 4:
                    continue
                # Protobuf field 1 (string): tag=0x0a, then varint length, then PID bytes
                tag = data[0]
                if tag != 0x0a:
                    continue
                pid_len = data[1]
                file_pid = data[2:2 + pid_len].decode("ascii", errors="ignore")
                if file_pid != pid:
                    continue
                # Found our file — extract device utilization from field 4
                self._hailo_utilization = _parse_device_utilization(data)
                return
        except (OSError, IndexError, ValueError):
            pass
