# Detection

## What This App Does
Real-time object detection with tracking using YOLO models on Hailo accelerators. This is the flagship detection pipeline that wraps inference in a resolution-preserving cropper (INFERENCE_PIPELINE_WRAPPER), adds object tracking via HailoTracker, and displays results with bounding boxes and labels overlaid on the video. It serves as the reference implementation for detection + tracking pipelines.

The callback demonstrates accessing detections with track IDs, filtering by label (e.g., "person"), and optionally extracting the video frame for custom OpenCV processing.

## Architecture
- **Type:** Pipeline app
- **Pattern:** source -> inference_wrapper -> tracker -> callback -> display
- **Models:**
  - hailo8: `yolov8m` (default), extras: yolov5m_wo_spp, yolov8s, yolov5s/m, yolov6n, yolov7, yolov8n/l/x, yolov9c, yolov10n/s/b/x, yolov11n/s/m/l/x
  - hailo8l: `yolov8s` (default), similar extras
  - hailo10h: `yolov8m` (default), similar extras plus yolov7x
- **Hardware:** hailo8, hailo8l, hailo10h
- **Postprocess:** TAPPAS detection postprocess .so (resolved via `DETECTION_POSTPROCESS_SO_FILENAME`)

## Key Files
| File | Purpose |
|------|---------|
| `detection.py` | Main entry point, user callback that prints person detections with track IDs |
| `detection_pipeline.py` | `GStreamerDetectionApp` subclass, pipeline definition |

## Pipeline Structure
```
SOURCE_PIPELINE
  -> INFERENCE_PIPELINE_WRAPPER(INFERENCE_PIPELINE)  # preserves original resolution
    -> TRACKER_PIPELINE(class_id=1)                  # tracks class 1 (person)
      -> USER_CALLBACK_PIPELINE                      # identity element for callback
        -> DISPLAY_PIPELINE                          # hailooverlay + fpsdisplaysink
```

Key parameters:
- `batch_size=2` (overridden from default 1)
- `nms-score-threshold=0.3`, `nms-iou-threshold=0.45`
- `output-format-type=HAILO_FORMAT_TYPE_FLOAT32`
- Labels JSON auto-detected from HEF file, or pass `--labels-json`

## Callback Data Available
```python
roi = hailo.get_roi_from_buffer(buffer)
detections = roi.get_objects_typed(hailo.HAILO_DETECTION)
for detection in detections:
    label = detection.get_label()          # e.g., "person", "car"
    confidence = detection.get_confidence() # float 0-1
    track = detection.get_objects_typed(hailo.HAILO_UNIQUE_ID)
    track_id = track[0].get_id() if len(track) == 1 else 0
```

With `--use-frame`, the raw video frame is available as a numpy array via `get_numpy_from_buffer()`.

## Common Use Cases
- Counting people or vehicles in a scene
- Security camera monitoring with persistent object tracking
- Traffic analysis and flow monitoring
- Building occupancy estimation
- Custom alerting when specific objects appear

## How to Extend
- **Swap models:** Use `--hef-path <path>` or `--list-models` to see available models
- **Custom callback:** Subclass `app_callback_class`, add state, modify `app_callback()` in `detection.py`
- **Change input:** Use `--input /dev/video0` (USB), `--input rtsp://...` (RTSP), or `--input file.mp4`
- **Remove tracking:** Remove `TRACKER_PIPELINE` from `get_pipeline_string()` in the pipeline class
- **Custom labels:** Use `--labels-json <path>` for a custom label mapping file

## Related Apps
| App | When to use instead |
|-----|-------------------|
| detection_simple | If you want a simpler pipeline without wrapper/tracking (lower latency, lower resolution) |
| tiling | If you need to detect small objects in high-res images |
| multisource | If you need to process multiple video streams simultaneously |
| instance_segmentation | If you need per-pixel masks in addition to bounding boxes |
