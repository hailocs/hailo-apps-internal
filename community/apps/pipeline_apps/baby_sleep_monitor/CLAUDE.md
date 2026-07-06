# Baby Sleep Monitor

## What This App Does
Real-time baby sleep position monitoring that uses YOLOv8 pose estimation (17 COCO keypoints) to detect unsafe sleeping positions (face-down, twisted, side-lying) and raise visual/audio alerts when an unsafe position persists.

## Architecture
- **Type:** Pipeline app
- **Pattern:** Detection + tracking + pose analysis (source → inference → tracker → callback → display)
- **Models:** YOLOv8 pose (17 COCO keypoints); HEF resolved per architecture via the pose pipeline helper
- **Hardware:** hailo8 (README), also hailo8l, hailo10h
- **Postprocess:** C++ pose postprocess `.so` + Python callback for sleep-position classification and the alert state machine

## Key Files
| File | Purpose |
|------|---------|
| `baby_sleep_monitor.py` | Entry point + app callback: keypoint extraction, position analysis, alert logic |
| `baby_sleep_monitor_pipeline.py` | `GStreamerApp` subclass: SOURCE → INFERENCE → TRACKER → CALLBACK → DISPLAY |

## How to Run
```bash
source setup_env.sh
python community/apps/pipeline_apps/baby_sleep_monitor/baby_sleep_monitor.py --input usb
```
Optional: `--show-fps`, `--use-frame`, `--hef-path <custom.hef>`.

## How to Extend
- Tune the danger-persistence threshold (seconds an unsafe position must hold before alerting) in the callback.
- Replace the console/terminal alert with real audio playback or a webhook/notification for production use.
