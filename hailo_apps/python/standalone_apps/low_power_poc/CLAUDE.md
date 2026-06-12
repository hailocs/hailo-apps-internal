# Low-Power Mode PoC

## What This App Does
Benchmarks a Hailo-8/8L M.2 module's sleep mode by measuring power consumption, sleep/wake transition latency, and FPS recovery across three states: active inference (baseline) → sleep → active inference (post-wake validation). It emits a PASS/FAIL report (FPS delta < threshold and device-alive checks) and a JSON file.

## Architecture
- **Type:** Standalone app (benchmark / proof-of-concept, no display)
- **Pattern:** Runs `detection_simple` (yolov6n) inference as a subprocess for FPS, samples power via the HailoRT power-measurement API, and toggles sleep state via `set_sleep_state`
- **Models:** yolov6n (640×640) — invoked through the `detection_simple` app for the inference phases
- **Hardware:** hailo8, hailo8l (sleep API not supported on hailo10h)
- **Postprocess:** N/A — measures power/FPS/timing rather than producing detections; computes FPS delta and power-reduction stats

## Key Files
| File | Purpose |
|------|---------|
| `low_power_poc.py` | Whole PoC — pre-flight device check, baseline/post-wake inference runs, sleep entry/exit timing, periodic power sampling, report generation, argparse CLI |

## How to Run
```bash
source setup_env.sh
# defaults (15s inference per phase, 40s sleep):
python -m hailo_apps.python.standalone_apps.low_power_poc.low_power_poc
# custom durations:
python -m hailo_apps.python.standalone_apps.low_power_poc.low_power_poc \
    --inference-duration 20 --sleep-duration 30 --fps-threshold 3.0 --output-json my_report.json
```
CLI: `--inference-duration` (15), `--sleep-duration` (40), `--fps-threshold` (5.0%), `--output-json` (`low_power_report.json`). Requires HailoRT 4.23+ and `ffmpeg`/`ffprobe`.

## How to Extend
- **Different model/baseline:** The inference phases shell out to `detection_simple`; swap the model or args there to benchmark sleep recovery against another network.
- **Pass criteria:** Tune `--fps-threshold` (max allowed baseline-vs-post-wake FPS delta) for stricter/looser validation.
- **Note:** Sleep powers down the NN core only — the management CPU and PCIe link stay active, which is why power sampling works during sleep.
