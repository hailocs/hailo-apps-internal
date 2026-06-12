# CLIP

## What This App Does
Real-time zero-shot classification using OpenAI's CLIP (Contrastive Language-Image Pre-training) model on Hailo. Users provide text prompts at runtime (via a GTK GUI), and the app matches video frames or detected objects against those prompts using cosine similarity between image and text embeddings. It supports two modes: whole-frame classification (detector=none) or detection-first classification (detector=person/vehicle/face/license-plate) where objects are detected, tracked, cropped, and then individually classified by CLIP.

This is the most feature-rich pipeline app, featuring a GTK GUI for interactive prompt management, multi-model inference (detection + CLIP image encoder + CLIP text encoder), ensemble text embeddings, and softmax-based matching.

## Architecture
- **Type:** Pipeline app (multi-model with GUI)
- **Pattern (no detector):** source -> clip_muxer(bypass + clip_inference) -> matching_callback -> user_callback -> display
- **Pattern (with detector):** source -> detection_wrapper -> tracker -> clip_cropper(clip_inference) -> matching_callback -> user_callback -> display
- **Models:**
  - All architectures: `clip_vit_b_32_image_encoder` + `hailo_yolov8n_4_classes_vga` (detection) + `clip_vit_b_32_text_encoder`
- **Hardware:** hailo8, hailo8l, hailo10h
- **Postprocess:** Multiple .so files -- detection postprocess, CLIP postprocess, CLIP cropper postprocess

## Key Files
| File | Purpose |
|------|---------|
| `clip.py` | Minimal entry point |
| `clip_pipeline.py` | `GStreamerClipApp` with multi-mode pipeline, matching callback, GUI integration |
| `text_image_matcher.py` | Singleton `TextImageMatcher` class for embedding comparison and softmax matching |
| `clip_text_utils.py` | Text encoder inference utilities |
| `gui.py` | GTK window for interactive text prompt management |
| `example_embeddings.json` | Pre-computed text embeddings for demo |

## Pipeline Structure

**Mode: no detector (whole-frame CLIP)**
```
SOURCE_PIPELINE
  -> tee
     -> bypass queue -> hailomuxer.sink_0
     -> videoscale -> CLIP INFERENCE_PIPELINE -> hailomuxer.sink_1
  hailomuxer -> matching_callback -> user_callback -> DISPLAY_PIPELINE
```

**Mode: with detector (e.g., --detector person)**
```
SOURCE_PIPELINE
  -> INFERENCE_PIPELINE_WRAPPER(detection)
    -> TRACKER_PIPELINE(class_id=N, keep_past_metadata=True)
      -> CROPPER_PIPELINE(CLIP INFERENCE_PIPELINE, clip cropper)
        -> matching_callback -> user_callback -> DISPLAY_PIPELINE
```

Key parameters:
- `detection_batch_size=8`, `clip_batch_size=8`
- Detection uses `scheduler_priority=31`, `scheduler_timeout_ms=100`
- CLIP uses `scheduler_priority=16`, `scheduler_timeout_ms=1000`
- Multi-process service enabled on hailo8/hailo8l
- Detector types: `person` (class_id=1), `vehicle` (2), `face` (3), `license-plate` (4), `none` (0)

## Callback Data Available
The `matching_identity_callback` handles CLIP matching internally. In the user callback:
```python
roi = hailo.get_roi_from_buffer(buffer)
# Top-level CLIP embeddings (no-detector mode):
matrices = roi.get_objects_typed(hailo.HAILO_MATRIX)  # CLIP image embeddings
# Detection-based CLIP results:
detections = roi.get_objects_typed(hailo.HAILO_DETECTION)
for detection in detections:
    classifications = detection.get_objects_typed(hailo.HAILO_CLASSIFICATION)
    # classification type='clip', label=matched_text, confidence=similarity
    embeddings = detection.get_objects_typed(hailo.HAILO_MATRIX)
```

## Common Use Cases
- Zero-shot object classification without retraining
- Interactive visual search ("find the red car", "person wearing a hat")
- Content moderation and filtering
- Anomaly detection via negative prompts
- Visual question answering

## How to Extend
- **Add prompts at runtime:** Type text in the GTK GUI; supports ensemble mode for better accuracy
- **Negative prompts:** Check the "negative" box in the GUI to exclude matches
- **Save/load embeddings:** Embeddings auto-save to JSON; use `--json-path` for custom location
- **Disable runtime prompts:** Use `--disable-runtime-prompts` for fixed prompt sets
- **Change detector:** Use `--detector person|vehicle|face|license-plate|none`
- **Adjust threshold:** Use `--detection-threshold 0.5` (0-1, higher = stricter matching)
- **Custom detection labels:** Use `--labels-json <path>`

## Related Apps
| App | When to use instead |
|-----|-------------------|
| detection | If you only need object detection without text-based classification |
| face_recognition | If you need to identify specific known people by face |
| tiling | If you need to detect small objects rather than classify them |
