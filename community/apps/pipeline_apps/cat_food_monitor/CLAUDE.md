# Cat Food Monitor

## What This App Does
Monitors a cat food bowl with face detection + recognition to identify individual cats and log feeding sessions (timestamps, durations) to CSV. Uses SCRFD face detection plus ArcFace embeddings matched against a LanceDB vector database.

## Architecture
- **Type:** Pipeline app
- **Pattern:** Detection + tracking + face recognition (source → SCRFD → tracker → cropper/align → ArcFace → callback → display)
- **Models:** SCRFD face detection (scrfd_10g; scrfd_2.5g on hailo8l) + ArcFace face embeddings
- **Hardware:** hailo8 (primary), also hailo8l, hailo10h
- **Postprocess:** C++ face detection/alignment `.so` + Python callback for LanceDB vector search and CSV logging

## Key Files
| File | Purpose |
|------|---------|
| `cat_food_monitor.py` | Entry point + callback: vector-DB lookup, feeding-session tracking, CSV logging |
| `cat_food_monitor_pipeline.py` | `GStreamerApp` subclass: SOURCE → INFERENCE → TRACKER → CROPPER → CALLBACK → DISPLAY (multi-model HEF) |
| `cat_food_algo_params.json` | Tuning params (skip frames, confidence threshold, batch size) |

## How to Run
```bash
source setup_env.sh
# 1) enroll/train cat identities first
python community/apps/pipeline_apps/cat_food_monitor/cat_food_monitor.py --mode train
# 2) then monitor
python community/apps/pipeline_apps/cat_food_monitor/cat_food_monitor.py --input usb
```
Optional: `--hef-path`, `--input <video|rtsp>`.

## How to Extend
- Add per-cat feeding alerts (e.g. notify when a specific cat hasn't visited in N hours).
- Capture training photos on detection, or export logs to cloud storage / a webhook.
