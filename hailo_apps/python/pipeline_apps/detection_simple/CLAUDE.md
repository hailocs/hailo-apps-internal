# Detection Simple

## What This App Does
A minimal object detection pipeline without resolution-preserving wrapper or tracking. This is the simplest detection pipeline in the repository -- source feeds directly into inference then to display. It runs at a fixed 640x640 resolution, making it lightweight and low-latency. Ideal for learning how the GStreamer pipeline works or when tracking is not needed.

The callback simply prints each detection's label and confidence, demonstrating the most basic detection data access pattern.

## Architecture
- **Type:** Pipeline app
- **Pattern:** source -> inference -> callback -> display (no wrapper, no tracker)
- **Models:**
  - hailo8: `yolov6n` (default)
  - hailo8l: `yolov6n` (default)
  - hailo10h: `yolov6n` (default)
- **Hardware:** hailo8, hailo8l, hailo10h
- **Postprocess:** TAPPAS simple detection postprocess .so (resolved via `SIMPLE_DETECTION_POSTPROCESS_SO_FILENAME`)

## Key Files
| File | Purpose |
|------|---------|
| `detection_simple.py` | Main entry point, minimal callback printing detections |
| `detection_simple_pipeline.py` | `GStreamerDetectionSimpleApp` subclass, pipeline definition |

## Pipeline Structure
```
SOURCE_PIPELINE(640x640, no_webcam_compression=True)
  -> INFERENCE_PIPELINE  # direct inference, no wrapper
    -> USER_CALLBACK_PIPELINE
      -> DISPLAY_PIPELINE
```

Key parameters:
- `video_width=640`, `video_height=640` (overridden from defaults)
- `batch_size=2`
- `nms-score-threshold=0.3`, `nms-iou-threshold=0.45`
- `no_webcam_compression=True` in SOURCE_PIPELINE
- Uses a dedicated default video (`SIMPLE_DETECTION_VIDEO_NAME`)

## Callback Data Available
```python
for detection in hailo.get_roi_from_buffer(buffer).get_objects_typed(hailo.HAILO_DETECTION):
    label = detection.get_label()           # e.g., "person", "car"
    confidence = detection.get_confidence()  # float 0-1
    # No track IDs -- no tracker in pipeline
```

## Common Use Cases
- Learning the Hailo GStreamer pipeline framework
- Quick prototyping and testing new models
- Low-latency detection without tracking overhead
- Benchmarking raw inference performance

## How to Extend
- **Add tracking:** Add `TRACKER_PIPELINE(class_id=-1)` after the inference pipeline in `get_pipeline_string()`
- **Add resolution wrapper:** Replace `INFERENCE_PIPELINE` with `INFERENCE_PIPELINE_WRAPPER(INFERENCE_PIPELINE(...))` for higher-res display
- **Swap models:** Use `--hef-path <path>` to try different detection models
- **Custom labels:** Use `--labels-json <path>`
- **Change input:** Use `--input /dev/video0` or `--input file.mp4`

## Related Apps
| App | When to use instead |
|-----|-------------------|
| detection | Full-featured detection with tracking and resolution preservation |
| tiling | For detecting small objects using tiled inference |
| multisource | For processing multiple video sources |
