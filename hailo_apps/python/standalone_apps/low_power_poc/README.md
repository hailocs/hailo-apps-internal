# Hailo Low-Power Mode PoC (Python)

Benchmarks a Hailo-8 M.2 module's sleep mode by measuring power consumption,
transition times, and FPS recovery across three states:

1. **Active inference** (baseline)
2. **Sleep mode** (low power)
3. **Active inference** (post-wake validation)

## Test Plan

| Phase | Description | Measurements |
|-------|-------------|-------------|
| **1. Pre-flight** | Verify device presence, identify HW/FW, measure idle power | Device ID, architecture, FW version, idle power (W) |
| **2. Baseline inference** | Run detection_simple (yolov6n, 640×640) with `--disable-sync --show-fps` for N seconds | FPS (frame-count / elapsed), power (avg/min/max W) |
| **3. Sleep entry** | Call `set_sleep_state(SLEEP_STATE_SLEEPING)` and time it | Entry latency (ms) |
| **4. Sleep power** | Wait 3s for stabilization, then sample power every 1s for the remaining sleep duration | Power (avg/min/max W), sample count |
| **5. Wake exit** | Call `set_sleep_state(SLEEP_STATE_AWAKE)` and time it | Exit latency (ms) |
| **6. Post-wake inference** | Same as Phase 2 — validate device recovers to baseline FPS | FPS, power |
| **7. Report** | Verify device is alive, compute FPS delta, power reduction | PASS/FAIL verdict |

### Pass Criteria

- **FPS delta** between baseline and post-wake < 5% (configurable via `--fps-threshold`)
- **Device alive** after full sleep/wake cycle

## Requirements

- Hailo-8 or Hailo-8L M.2 module (sleep API not supported on Hailo-10H)
- HailoRT 4.23+ with Python bindings (`hailo_platform`)
- `ffmpeg` / `ffprobe` (for video looping)
- hailo-apps repo installed (`pip install -e .`)

## Usage

```bash
# From repo root, with venv active
source setup_env.sh

# Run with defaults (15s inference, 40s sleep)
python3 -m hailo_apps.python.standalone_apps.low_power_poc.low_power_poc

# Custom durations
python3 -m hailo_apps.python.standalone_apps.low_power_poc.low_power_poc \
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

## Example Output

```
============================================================
       HAILO LOW-POWER MODE PoC REPORT
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
 Baseline infer       |   319.5 | 2.803 / 2.571 / 2.870 W
 Sleep mode           |       — | 1.080 / 0.963 / 1.131 W
 Post-wake infer      |   310.7 | 2.761 / 2.571 / 2.853 W
------------------------------------------------------------
 TRANSITIONS          |  Time (ms)
------------------------------------------------------------
 Sleep entry          |       3.41
 Wake exit            |       4.12
------------------------------------------------------------
 VALIDATION           | Result
------------------------------------------------------------
 FPS delta            | 2.8% -> PASS (<5.0%)
 Power reduction      | 27.6% (sleep vs idle)
 Device alive         | YES
============================================================
```

## Key Implementation Details

- **Subprocess I/O**: stdout/stderr redirected to temp files (not PIPEs) to prevent
  64KB pipe buffer overflow at 300+ FPS
- **Video looping**: Source video (336 frames) is looped via ffmpeg concat to produce
  enough frames for the full test at ~350 FPS processing speed
- **FPS metric**: Frame-count / elapsed time is the primary metric (stable ±0.2%);
  fpsdisplaysink is secondary (noisy, instantaneous peaks)
- **Power API**: Uses `set_power_measurement` + `start_power_measurement` +
  `get_power_measurement(should_clear=True)` for periodic 1-second averaged samples
- **Sleep API**: `device._device.set_sleep_state(SleepState.SLEEP_STATE_SLEEPING/AWAKE)`
  via `hailo_platform.pyhailort._pyhailort.SleepState`

## Notes

- The overcurrent protection DVM warning is expected on M.2 modules — the INA231
  sensor shares the overcurrent protection pin, so monitoring temporarily disables it
- Sleep mode powers down the NN core only; the management CPU and PCIe link stay active
  (which is why power measurement works during sleep)
