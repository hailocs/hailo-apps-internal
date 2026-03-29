# Community Apps

Example applications built by AI agents and community contributors. These live separately from the core framework (`hailo_apps/`) and can be promoted to official apps after review.

## Structure

```
community/apps/
├── pipeline_apps/       # GStreamer real-time video apps (8)
├── standalone_apps/     # Lightweight HailoRT-only apps (2)
└── gen_ai_apps/         # Hailo-10H GenAI apps (0 — coming soon)
```

## Running

Each app includes a `run.sh` wrapper. Run from the repo root:

```bash
# Via run.sh (recommended)
./community/apps/pipeline_apps/depth_anything/run.sh --input usb

# Or directly via Python
python community/apps/pipeline_apps/depth_anything/depth_anything.py --input usb
```

## Apps

### Pipeline Apps (8)

| App | Description | Entry Point |
|-----|-------------|-------------|
| depth_anything | Monocular depth estimation using Depth Anything v1/v2 | `depth_anything.py` |
| gesture_detection | Two-stage hand gesture detection (palm + landmarks) | `gesture_detection.py` |
| gesture_mouse | Hand gesture-based mouse cursor control | `gesture_mouse.py` |
| hotdog_not_hotdog | Zero-shot "hotdog or not" classification via CLIP | `hotdog_not_hotdog.py` |
| line_crossing_counter | Count objects crossing a virtual line | `line_crossing_counter.py` |
| room_security_monitor | Face recognition with enrollment UI for room access | `room_security_monitor.py` |
| semaphore_translator | Translate flag semaphore arm positions to letters | `semaphore_translator.py` |
| yolo_world | Open-vocabulary detection with text prompts | `yolo_world.py` |

### Standalone Apps (2)

| App | Description | Entry Point |
|-----|-------------|-------------|
| depth_anything_cpp | C++ depth estimation using HailoRT + OpenCV | `depth_anything.cpp` |
| depth_anything_python | Python depth estimation using HailoInfer + OpenCV | `depth_anything_standalone.py` |

## App Manifest

Each app includes an `app.yaml` manifest:

```yaml
name: my_app
title: My App Title
description: What it does.
type: pipeline        # pipeline | standalone | gen_ai
entry_point: my_app.py
models:
  - model_name.hef
hailo_arch:
  - hailo8
  - hailo8l
  - hailo10h
```

## Building New Apps

Use the AI agent skills in `.hailo/skills/` to scaffold new apps. New apps are placed in this directory automatically and can be promoted to official apps via:

```bash
python .hailo/scripts/curate_contributions.py --promote <app_name>
```
