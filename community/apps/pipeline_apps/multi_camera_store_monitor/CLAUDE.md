# Multi-Camera Store Monitor

## What This App Does
Monitors three retail cameras (entrance, checkout, stockroom) in parallel through a single shared YOLOv8 detection pipeline using round-robin scheduling. Counts persons per camera, raises zone alerts when thresholds are exceeded, and periodically prints summary statistics.

## Architecture
- **Type:** Pipeline app (multi-stream)
- **Pattern:** N sources → round-robin mux → shared YOLOv8 detection → per-stream tracker → unified callback → stream router → per-source display
- **Models:** YOLOv8 detection (COCO; filters the person class)
- **Hardware:** hailo8 (primary), hailo8l, hailo10h
- **Postprocess:** C++ `libdetection_postprocess.so`; `libtappas_set_stream_id_tool.so` for per-source labeling

## Key Files
| File | Purpose |
|------|---------|
| `multi_camera_store_monitor.py` | Entry point + callback: per-camera person counts (current/max/avg), zone alerts |
| `multi_camera_store_monitor_pipeline.py` | `GStreamerApp` subclass: round-robin → detection+tracker → stream router |

## How to Run
```bash
source setup_env.sh
python community/apps/pipeline_apps/multi_camera_store_monitor/multi_camera_store_monitor.py \
  --sources entrance.mp4,checkout.mp4,stockroom.mp4
```
Optional: `--person-threshold 0.5`, `--show-fps`.

## How to Extend
- Export per-camera time-series / heat-map data to an analytics backend (JSON/CSV).
- Tune per-camera person thresholds based on historical occupancy.
