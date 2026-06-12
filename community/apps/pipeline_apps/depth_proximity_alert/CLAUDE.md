# Depth Proximity Alert

## What This App Does
Real-time depth-based proximity alerting using SCDepthV3 monocular depth estimation. Monitors a configurable region of interest and triggers visual/console alerts when an object enters a proximity threshold.

## Architecture
- **Type:** Pipeline app
- **Pattern:** Depth estimation + ROI analysis (source → inference → callback threshold/alert → display)
- **Models:** scdepthv3 (monocular depth estimation)
- **Hardware:** hailo8, hailo8l, hailo10h
- **Postprocess:** C++ depth postprocess `.so` + Python callback for ROI extraction, threshold comparison, and alert cooldown

## Key Files
| File | Purpose |
|------|---------|
| `depth_proximity_alert.py` | Entry point + callback: ROI depth analysis (percentile + smoothing), alert state machine |
| `depth_proximity_alert_pipeline.py` | `GStreamerApp` subclass: SOURCE → INFERENCE → CALLBACK → DISPLAY |

## How to Run
```bash
source setup_env.sh
python community/apps/pipeline_apps/depth_proximity_alert/depth_proximity_alert.py --input usb
```
Optional: `--proximity-threshold 0.3` (0-1, lower = closer), `--alert-region x y w h` (normalized; default center 50%), `--show-fps`.

## How to Extend
- Add an audio alert or log proximity events with timestamps to a file.
- Combine with object detection to attribute the proximity to a specific detected object.
