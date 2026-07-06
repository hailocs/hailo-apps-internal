# Semaphore Flag Translator

## What This App Does
Real-time semaphore flag-signal translator. Detects arm angles from YOLOv8-pose keypoints, discretizes them to 45-degree steps, maps them to the International Maritime semaphore alphabet, and accumulates decoded letters into words with frame-based stabilization.

## Architecture
- **Type:** Pipeline app
- **Pattern:** Pose estimation + tracking → callback (arm-angle computation → semaphore lookup → word accumulation) → display
- **Models:** YOLOv8 pose (HEF resolved per architecture via the pose pipeline helper)
- **Hardware:** hailo8, hailo8l, hailo10h
- **Postprocess:** C++ `libyolov8_pose_postprocess.so` + Python callback

## Key Files
| File | Purpose |
|------|---------|
| `semaphore_translator.py` | Entry point + callback: arm-angle (`atan2`) computation, discretization, semaphore lookup, stabilization, word build, overlay |
| `semaphore_translator_pipeline.py` | `GStreamerApp` subclass: SOURCE → INFERENCE → TRACKER → CALLBACK → DISPLAY |

## How to Run
```bash
source setup_env.sh
python community/apps/pipeline_apps/semaphore_translator/semaphore_translator.py --input usb --use-frame
```
Optional: `--input path/to/video.mp4`.

## How to Extend
- Tune the per-letter stability threshold (~10 frames) and `ANGLE_TOLERANCE` for faster recognition vs robustness.
- Add a "cancel" gesture (e.g. both arms at 0°) to reset the accumulated word.
