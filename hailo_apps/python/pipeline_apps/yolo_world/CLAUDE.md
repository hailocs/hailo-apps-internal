# YOLO World — Open-Vocabulary Detection

## What This App Does
Open-vocabulary, zero-shot object detection: detect anything you describe in free text, with classes changeable at runtime and no retraining. A CLIP text encoder turns the prompt words into embeddings that the dual-input `yolo_world_v2s` HEF (image + 80×512 text embeddings) uses to score every region; an optional interactive panel lets you add/remove/compare classes live.

## Architecture
- **Type:** Pipeline app (open-vocabulary detector with text conditioning)
- **Pattern:** GStreamer source → Python `app_callback` runs the dual-input HEF via HailoRT, parses the fused NMS output, attaches `hailo.HailoDetection` metadata; `hailotracker` downstream stabilizes detections; `hailooverlay` draws
- **Models:** `yolo_world_v2s` HEF (dual-input: 640×640 image + 80×512 text embeddings). Text encoder: pure-NumPy CLIP ViT-B/32 (body weights `clip_text_vitb32_body_fp16.npz`) — no torch/transformers at runtime, only numpy + tokenizers
- **Hardware:** hailo8, hailo10h
- **Postprocess:** libhailort host-side `YOLOV8PostProcessOp` (DFL decode + sigmoid + per-class IoU NMS) emits one `HAILO_NMS_BY_SCORE` tensor; Python `postprocess.py` parses the byte stream and score-thresholds (sub-ms)

## Key Files
| File | Purpose |
|------|---------|
| `yolo_world.py` | Entry point — `YoloWorldCallbackData`, `app_callback` (infer → postprocess → attach metadata), wires embedding manager + inference engine + interactive controller |
| `yolo_world_pipeline.py` | `GStreamerYoloWorldApp`, the pipeline/tracker string, app-specific CLI args (`--prompts`, `--confidence-threshold`, `--interactive`, …) |
| `yolo_world_inference.py` | `YoloWorldInference` — dual-input HEF runner, `update_text_embeddings()` |
| `text_embedding_manager.py` | `TextEmbeddingManager` — prompt → embedding caching, file watching, frozen-embeddings load |
| `numpy_clip_text_encoder.py` | Pure-NumPy CLIP ViT-B/32 text encoder |
| `postprocess.py` | Parses the `HAILO_NMS_BY_SCORE` output into detection dicts |
| `live_control.py` | `LivePromptController` — interactive terminal panel (replace / `+add` / `-remove` / `?suggest`) |
| `prompt_suggester.py` | `PromptSuggester` — ranks near-synonyms by what actually detects on recent frames |

## How to Run
```bash
source setup_env.sh
python hailo_apps/python/pipeline_apps/yolo_world/yolo_world.py --input usb --prompts "cat, dog, laptop"
# or the installed console entry point:
hailo-yolo-world --input /usr/local/hailo/resources/videos/office_example.mp4 \
                 --prompts "wireless keyboard, mouse, coffee mug, bottle" --arch hailo10h
# interactive live prompt control:
hailo-yolo-world --input usb --prompts "person" --interactive
```
Without `--prompts`/`--prompts-file` the app falls back to COCO-80 (or auto-loads `embeddings.json`).

## How to Extend
- **Frozen prompts (no CLIP at runtime):** Encode once with `--prompts-file classes.json --run-duration 1` to write `embeddings.json`, then deploy with `--embeddings-file embeddings.json`; the CLIP encoder is never loaded.
- **Prompt phrasing:** Detection is very sensitive to wording — use concrete in-vocab nouns and use `--interactive` `?word` to compare synonyms live (see README "Prompt phrasing matters").
- **Throughput:** Reducing active prompt count does not speed up inference (text input is always padded to 80); recompile the HEF with a smaller `classes` NMS parameter for higher FPS.
