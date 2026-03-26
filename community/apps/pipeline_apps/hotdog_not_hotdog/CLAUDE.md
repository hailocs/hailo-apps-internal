# Hotdog Not Hotdog

## What This App Does
Binary food classifier using CLIP zero-shot classification. Compares each video frame against "hotdog" and background class embeddings ("food", "person", "animal", "object", "room") via softmax. If "hotdog" wins → HOTDOG!, otherwise → NOT HOTDOG!. Background classes are used instead of "not hotdog" because CLIP doesn't handle negation well. Text embeddings are cached to `embeddings.json` on first run.

## Architecture
- **Type:** Pipeline
- **Pattern:** source → CLIP full-frame inference (tee+muxer) → matching callback → user callback → display
- **Template base:** clip (with `--detector none` pattern, simplified — no GTK GUI)
- **Models:** clip_vit_b_32_image_encoder (every frame), clip_vit_b_32_text_encoder (first run only, cached to embeddings.json)
- **Hardware:** hailo8, hailo8l, hailo10h
- **Postprocess:** libclip_postprocess.so

## Key Files
| File | Purpose |
|------|---------|
| `hotdog_not_hotdog_pipeline.py` | GStreamerApp subclass, CLIP pipeline, text embedding setup, matching callback |
| `hotdog_not_hotdog.py` | User callback (verdict overlay), entry point |
| `README.md` | User documentation |

## Pipeline Structure
```
Source → tee → [bypass] → hailomuxer → matching_callback → user_callback → display
           └→ videoscale → CLIP inference →┘
```

## Callback Data Available
```python
roi = hailo.get_roi_from_buffer(buffer)
classifications = roi.get_objects_typed(hailo.HAILO_CLASSIFICATION)
# classifications[0].get_label() → "hotdog", "food", "person", "animal", "object", or "room"
# classifications[0].get_confidence() → float [0, 1]
```

## How to Extend
- Change prompts in `_load_or_generate_embeddings()`, run with `--regenerate-embeddings`
- Switch to detector mode to classify detected objects instead of full frame
- Add sound effects by integrating with `pydub` or `pygame.mixer`

## Related Apps
- `clip` — Full CLIP app with GTK GUI and runtime prompt editing (template base)
