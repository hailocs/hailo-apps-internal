# PPE Safety Checker (CLIP Zero-Shot)

## What This App Does
Real-time PPE compliance checking via CLIP zero-shot classification. Detects people with YOLOv8, crops each person, extracts CLIP image embeddings, and matches them against text prompts describing safe (hard hat, safety vest) vs unsafe states, overlaying color-coded boxes (green = compliant, red = violation).

## Architecture
- **Type:** Pipeline app (CLIP zero-shot)
- **Pattern:** YOLOv8 person detection → tracker → cropper (CLIP image encoder) → matching callback (text↔image embedding) → display
- **Models:** `clip_image.hef` (image encoder) + `clip_text.hef` (text encoder) + YOLOv8 (person detection)
- **Hardware:** hailo8 (primary), hailo8l, hailo10h
- **Postprocess:** C++ `.so`: `libyolo_hailortpp_postprocess.so`, `libclip_postprocess.so`, `libclip_croppers_postprocess.so`

## Key Files
| File | Purpose |
|------|---------|
| `ppe_safety_checker.py` | Entry point + callback: accumulates safe/violation counts from classification labels |
| `ppe_safety_checker_pipeline.py` | `GStreamerApp` subclass: sets up CLIP + YOLOv8, matching callback ranks prompts and tags SAFE/VIOLATION/UNKNOWN |

## How to Run
```bash
source setup_env.sh
python community/apps/pipeline_apps/ppe_safety_checker/ppe_safety_checker.py --input usb
```
Optional: `--detection-threshold 0.5`, `--clip-threshold 0.3`.

## How to Extend
- Edit the text prompts in the pipeline to define new PPE classes (gloves, goggles, etc.) — no retraining needed (zero-shot).
- Add audio/visual alerts on violation, or track per-worker compliance history.
