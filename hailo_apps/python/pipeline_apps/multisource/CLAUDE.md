# Multisource

## What This App Does
Multi-stream object detection that processes multiple video sources through a single shared inference pipeline. Sources are multiplexed via `hailoroundrobin`, processed through a single detection + tracking pipeline, then demultiplexed via `hailostreamrouter` back to individual display sinks. Each stream gets its own display window with overlaid detections and tracking. The callback receives a stream ID, enabling stream-specific logic.

This demonstrates efficient hardware utilization by sharing one Hailo accelerator across multiple camera feeds, which is the standard pattern for multi-camera surveillance systems.

## Architecture
- **Type:** Pipeline app (multi-stream)
- **Pattern:** N sources -> roundrobin -> inference -> tracker -> callback -> streamrouter -> N displays
- **Models:** Same as detection app:
  - hailo8: `yolov8m` (default)
  - hailo8l: `yolov8s` (default)
  - hailo10h: `yolov8m` (default)
- **Hardware:** hailo8, hailo8l, hailo10h
- **Postprocess:** TAPPAS detection postprocess .so

## Key Files
| File | Purpose |
|------|---------|
| `multisource.py` | Main entry point, unified callback printing stream_id + label + track_id |
| `multisource_pipeline.py` | `GStreamerMultisourceApp` with round-robin/stream-router pipeline |

## Pipeline Structure
```
SOURCE_PIPELINE("source_0") -> hailofilter(set_stream_id "src_0") -> robin.sink_0
SOURCE_PIPELINE("source_1") -> hailofilter(set_stream_id "src_1") -> robin.sink_1
...

hailoroundrobin(mode=1) name=robin
  -> INFERENCE_PIPELINE (shared)
    -> TRACKER_PIPELINE(class_id=-1)
      -> USER_CALLBACK_PIPELINE (unified callback)
        -> hailostreamrouter name=router
          router.src_0 -> per-source callback -> DISPLAY_PIPELINE("hailo_display_0")
          router.src_1 -> per-source callback -> DISPLAY_PIPELINE("hailo_display_1")
          ...
```

Key parameters:
- `hailoroundrobin mode=1`: round-robin multiplexing of source streams
- `hailostreamrouter`: demultiplexes by stream ID with `input-streams` property
- Stream IDs set via `hailofilter` with `set_stream_id_so` from TAPPAS
- `nms-score-threshold=0.3`, `nms-iou-threshold=0.45`
- Default: 2 sources (duplicates the default video) if `--sources` not specified

## Callback Data Available
```python
roi = hailo.get_roi_from_buffer(buffer)
stream_id = roi.get_stream_id()  # e.g., "src_0", "src_1"
detections = roi.get_objects_typed(hailo.HAILO_DETECTION)
for detection in detections:
    ids = detection.get_objects_typed(hailo.HAILO_UNIQUE_ID)
    track_id = ids[0].get_id() if ids else 0
    label = detection.get_label()
```

## Common Use Cases
- Multi-camera surveillance systems
- Retail analytics across multiple store cameras
- Traffic monitoring at intersections (multiple angles)
- Building security with entrance/exit cameras
- Comparing detection results across different camera angles

## How to Extend
- **Add more sources:** Use `--sources /dev/video0,/dev/video1,rtsp://...` (comma-separated)
- **Per-source logic:** Access `roi.get_stream_id()` in the callback to apply different logic per camera
- **Change model:** Use `--hef-path <path>` for a different detection model
- **Remove per-source callbacks:** Simplify by removing the per-source `USER_CALLBACK_PIPELINE` after the router

## Related Apps
| App | When to use instead |
|-----|-------------------|
| detection | If you only have one video source |
| reid_multisource | If you need cross-camera person re-identification |
| face_recognition | If you need to identify specific people |
