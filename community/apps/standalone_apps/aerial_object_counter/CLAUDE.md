# Aerial Object Counter

## What This App Does
Detects and classifies objects in aerial/drone imagery using oriented (rotated) bounding boxes from a YOLO11s-OBB model. Produces annotated images with per-class counts and a JSON summary of object statistics per image.

## Architecture
- **Type:** Standalone app
- **Pattern:** HailoInfer + OpenCV; 3-thread pipeline (preprocess → async inference → counting/visualization) with OBB detection
- **Models:** yolo11s-obb (YOLO11 small, oriented bounding boxes)
- **Hardware:** hailo8, hailo8l, hailo10h (see README)
- **Postprocess:** Python — OBB decoding with rotated NMS, per-class counting, count overlay

## Key Files
| File | Purpose |
|------|---------|
| `aerial_object_counter.py` | Main app: preprocess → async inference → counting visualizer threads |
| `aerial_object_counter_post_process.py` | OBB postprocess, per-class counting, count-overlay annotation |

## How to Run
```bash
source setup_env.sh
python community/apps/standalone_apps/aerial_object_counter/aerial_object_counter.py --input /path/to/drone/images/
```
Optional: `--score-threshold 0.4`, `--json-output results/counts.json`, `--no-display`.

## How to Extend
- Extend the label set / swap in a model trained on a custom aerial dataset.
- Add cross-frame tracking for video surveys or batch-processing optimizations for large image sets.
