# Visual Quality Inspector

## What This App Does
A Vision Language Model (VLM) app for manufacturing quality inspection. Captures images from a USB or RPi camera, uses Qwen2-VL-2B-Instruct on Hailo-10H to analyze parts for defects, produces natural-language defect reports (severity/location), and logs inspection results to JSONL.

## Architecture
- **Type:** Gen AI app (VLM)
- **Pattern:** VLM image understanding with a multiprocessing backend and a state-machine UI (STREAMING → CAPTURED → PROCESSING → RESULT)
- **Models:** Qwen2-VL-2B-Instruct (VLM)
- **Hardware:** hailo10h
- **Postprocess:** VLM language generation guided by a quality-inspection system prompt

## Key Files
| File | Purpose |
|------|---------|
| `visual_quality_inspector.py` | Main: state machine, camera I/O, user interaction, JSONL logging |
| `backend.py` | Multiprocessing VLM worker: image preprocessing, VLM inference, result queueing |

## How to Run
```bash
source setup_env.sh
python -m community.apps.gen_ai_apps.visual_quality_inspector.visual_quality_inspector --input usb
```
Optional: `--input rpi`, `--results-file inspections.jsonl`.

## How to Extend
- Customize the inspection system prompt for your part type, or add defect-category classification.
- Archive captured images alongside their reports and add defect-trend statistics over time.
