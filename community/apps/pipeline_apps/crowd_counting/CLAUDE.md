# Crowd Counting

## What This App Does
Real-time people detection and tracking with virtual line-crossing detection. Tracks the direction of each crossing (top-to-bottom vs bottom-to-top) and reports running totals for entrances/exits.

## Architecture
- **Type:** Pipeline app
- **Pattern:** Detection + tracking + line-crossing logic (source → inference → tracker → callback → display)
- **Models:** YOLOv8m (person detection, COCO person class)
- **Hardware:** hailo8, hailo8l, hailo10h
- **Postprocess:** C++ detection postprocess `.so` + Python callback for crossing logic and frame overlay

## Key Files
| File | Purpose |
|------|---------|
| `crowd_counting.py` | Entry point + callback: line-crossing state machine, direction inference, overlay drawing |
| `crowd_counting_pipeline.py` | `GStreamerApp` subclass: SOURCE → INFERENCE → TRACKER → CALLBACK → DISPLAY |

## How to Run
```bash
source setup_env.sh
python community/apps/pipeline_apps/crowd_counting/crowd_counting.py --input usb
```
Optional: `--line-y 0.3` (line position 0-1), `--use-frame`, `--show-fps`, `--hef-path`.

## How to Extend
- Add direction-specific alerts (e.g. notify only on entrance crossings) or log crossings with timestamps.
- Convert the in/out counters into a live occupancy count.
