# Instance Segmentation

## What This App Does
Real-time instance segmentation that detects objects and produces per-instance pixel masks using YOLOv5-seg models. Each detected object gets both a bounding box and a binary mask showing exactly which pixels belong to it. The pipeline includes tracking for consistent instance IDs and resolution-preserving inference wrapping. The callback demonstrates extracting and rendering colored instance masks overlaid on the video frame.

This goes beyond detection by providing precise object boundaries, enabling applications like background removal, object counting with occlusion handling, and scene understanding.

## Architecture
- **Type:** Pipeline app
- **Pattern:** source -> inference_wrapper -> tracker -> callback -> display
- **Models:**
  - hailo8: `yolov5m_seg` (default)
  - hailo8l: `yolov5n_seg` (default)
  - hailo10h: `yolov5m_seg` (default)
- **Hardware:** hailo8, hailo8l, hailo10h
- **Postprocess:** TAPPAS instance segmentation postprocess .so (resolved via `INSTANCE_SEGMENTATION_POSTPROCESS_SO_FILENAME`)
- **Config JSON:** Model-specific config file (e.g., `yolov5m_seg.json` or `yolov5n_seg.json`) selected based on HEF name

## Key Files
| File | Purpose |
|------|---------|
| `instance_segmentation.py` | Main entry point, callback with mask extraction and colored overlay rendering |
| `instance_segmentation_pipeline.py` | `GStreamerInstanceSegmentationApp` subclass, pipeline definition |

## Pipeline Structure
```
SOURCE_PIPELINE(640x640)
  -> INFERENCE_PIPELINE_WRAPPER(INFERENCE_PIPELINE)  # preserves original resolution
    -> TRACKER_PIPELINE(class_id=1)                  # tracks class 1 (person)
      -> USER_CALLBACK_PIPELINE
        -> DISPLAY_PIPELINE
```

Key parameters:
- `video_width=640`, `video_height=640` (overridden from defaults)
- `batch_size=2`
- Config JSON auto-selected based on HEF model name (yolov5m_seg vs yolov5n_seg)

## Callback Data Available
```python
roi = hailo.get_roi_from_buffer(buffer)
detections = roi.get_objects_typed(hailo.HAILO_DETECTION)
for detection in detections:
    label = detection.get_label()
    bbox = detection.get_bbox()
    confidence = detection.get_confidence()
    track = detection.get_objects_typed(hailo.HAILO_UNIQUE_ID)
    track_id = track[0].get_id() if len(track) == 1 else 0

    # Instance mask
    masks = detection.get_objects_typed(hailo.HAILO_CONF_CLASS_MASK)
    if len(masks) != 0:
        mask = masks[0]
        mask_height = mask.get_height()
        mask_width = mask.get_width()
        data = np.array(mask.get_data()).reshape((mask_height, mask_width))
        # Resize mask to detection bbox size, threshold at 0.5
```

The callback includes frame skipping (`frame_skip=2`) and 1/4 resolution rendering for performance. Masks are colored per track ID using a predefined color palette.

## Common Use Cases
- Video background removal or replacement
- Precise object counting with occlusion handling
- Autonomous driving scene understanding
- Industrial quality inspection (identifying defective parts)
- Augmented reality object masking

## How to Extend
- **Swap models:** Use `--hef-path <path>` or `--list-models`
- **Full-res masks:** Remove the `reduced_width/reduced_height` downscaling in the callback for full-resolution mask rendering
- **Change frame skip:** Modify `self.frame_skip` in `user_app_callback_class` for different processing rates
- **Track all classes:** Change `TRACKER_PIPELINE(class_id=-1)` to track all object classes
- **Export masks:** Save mask arrays as numpy files or images for offline analysis

## Related Apps
| App | When to use instead |
|-----|-------------------|
| detection | If you only need bounding boxes (faster, no mask overhead) |
| pose_estimation | If you need body joint positions instead of masks |
| depth | If you need distance estimation rather than segmentation |
