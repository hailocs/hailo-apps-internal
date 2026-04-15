# Hailo Low-Power Mode PoC (C++)

C++ implementation of the low-power mode benchmark using the HailoRT C++ API directly.
Benchmarks a Hailo-8 M.2 module's sleep mode by measuring power consumption,
transition times, and FPS recovery across three states:

1. **Active inference** (baseline)
2. **Sleep mode** (low power)
3. **Active inference** (post-wake validation)

## Test Plan

| Phase | Description | Measurements |
|-------|-------------|-------------|
| **1. Pre-flight** | `Device::create()` + `device->identify()` to get HW/FW info, single power measurement | Device ID, architecture, FW version, idle power (W) |
| **2. Baseline inference** | Launch detection_simple subprocess, measure power periodically | FPS (frame-count / elapsed), power (avg/min/max W) |
| **3. Sleep entry** | `device->set_sleep_state(HAILO_SLEEP_STATE_SLEEPING)` with `steady_clock` timing | Entry latency (ms) |
| **4. Sleep power** | 3s stabilization, then 1-second periodic power samples for remaining duration | Power (avg/min/max W), sample count |
| **5. Wake exit** | `device->set_sleep_state(HAILO_SLEEP_STATE_AWAKE)` with `steady_clock` timing | Exit latency (ms) |
| **6. Post-wake inference** | Same as Phase 2 — validate device recovers to baseline FPS | FPS, power |
| **7. Report** | `device->identify()` to verify device alive, compute FPS delta, power reduction | PASS/FAIL verdict |

### Pass Criteria

- **FPS delta** between baseline and post-wake < 5% (configurable via `--fps-threshold`)
- **Device alive** after full sleep/wake cycle

## HailoRT C++ API Usage

All device control uses `hailort::Device` methods from `<hailo/device.hpp>`:

```cpp
// Device creation & identification
auto device = Device::create().release();
auto identity = device->identify();  // → hailo_device_identity_t

// Sleep state control
device->set_sleep_state(HAILO_SLEEP_STATE_SLEEPING);
device->set_sleep_state(HAILO_SLEEP_STATE_AWAKE);

// Single power measurement
device->power_measurement(HAILO_DVM_OPTIONS_AUTO, HAILO_POWER_MEASUREMENT_TYPES__AUTO);

// Periodic power measurement
device->set_power_measurement(HAILO_MEASUREMENT_BUFFER_INDEX_0, HAILO_DVM_OPTIONS_AUTO, HAILO_POWER_MEASUREMENT_TYPES__AUTO);
device->start_power_measurement(HAILO_AVERAGE_FACTOR_1, HAILO_SAMPLING_PERIOD_1100US);
auto data = device->get_power_measurement(HAILO_MEASUREMENT_BUFFER_INDEX_0, true);
// data->average_value, data->min_value, data->max_value
device->stop_power_measurement();
```

## Requirements

- Hailo-8 or Hailo-8L M.2 module (sleep API not supported on Hailo-10H)
- HailoRT 4.23+ (headers + shared library)
- CMake 3.16+
- `ffmpeg` / `ffprobe` (for video looping)
- hailo-apps repo with Python venv (for inference subprocess)

## Build

```bash
cd hailo_apps/cpp/low_power_poc
bash build.sh
```

This creates `build/low_power_poc`.

## Usage

```bash
# From repo root (so the inference subprocess can find the Python module)
cd /path/to/hailo-apps-internal

# Run with defaults (15s inference, 40s sleep)
./hailo_apps/cpp/low_power_poc/build/low_power_poc

# Custom durations
./hailo_apps/cpp/low_power_poc/build/low_power_poc \
    --inference-duration 20 \
    --sleep-duration 30 \
    --fps-threshold 3.0 \
    --output-json my_report.json
```

### CLI Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--inference-duration` | 15 | Duration of each inference phase (seconds) |
| `--sleep-duration` | 40 | Duration of sleep mode (seconds) |
| `--fps-threshold` | 5.0 | Max allowed FPS delta % for PASS |
| `--output-json` | `low_power_report.json` | Output JSON report file path |
| `--inference-cmd` | auto-detected | Custom inference command (overrides default detection_simple) |

## Example Output

```
============================================================
       HAILO LOW-POWER MODE PoC REPORT (C++)
============================================================
 Device              : HAILO8 (M.2, PCIe)
 Device ID           : 0000:04:00.0
 Firmware            : 4.23.0
 Model               : yolov6n (640x640)
 Inference duration  : 15s per phase
 Sleep duration      : 40s
------------------------------------------------------------
 PHASE                |     FPS | Power (avg/min/max)
------------------------------------------------------------
 Idle (startup)       |       — | 1.412 W
 Baseline infer       |   304.3 | 2.692 / 2.574 / 2.814 W
 Sleep mode           |       — | 1.022 / 0.957 / 1.109 W
 Post-wake infer      |   303.8 | 2.685 / 2.561 / 2.754 W
------------------------------------------------------------
 TRANSITIONS          |  Time (ms)
------------------------------------------------------------
 Sleep entry          |       3.01
 Wake exit            |       3.68
------------------------------------------------------------
 VALIDATION           | Result
------------------------------------------------------------
 FPS delta            | 0.2% -> PASS (<5.0%)
 Power reduction      | 62.0% (sleep vs active)
 Device alive         | YES
============================================================
```

## Architecture

```
low_power_poc.cpp
├── Device control (C++ HailoRT API)
│   ├── Device::create() / identify()
│   ├── set_sleep_state()
│   └── power_measurement() / set/start/get/stop_power_measurement()
├── Inference subprocess (fork + exec)
│   ├── Launches detection_simple via bash (source setup_env.sh && python3 -m ...)
│   ├── stdout/stderr → temp files (avoids pipe buffer overflow at 300+ FPS)
│   └── SIGTERM → SIGINT → SIGKILL graceful shutdown
├── Video preparation
│   └── ffmpeg concat loop (frame-count based, not wall-clock)
└── Report
    ├── Structured text table to stdout
    └── JSON report to file
```

## Notes

- The inference subprocess still uses Python (detection_simple) — the C++ part handles
  all device control (sleep, power, identity) via the HailoRT C++ API
- The overcurrent protection DVM warning is expected on M.2 modules
- Sleep mode powers down the NN core only; management CPU and PCIe link stay active
- The binary auto-discovers the repo root by walking up from its location to find `setup_env.sh`
