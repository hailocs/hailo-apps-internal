# Line Crossing Counter

## What This App Does
Real-time people counting using zone-based virtual line crossing detection. A vertical counting line is placed in the frame (configurable via `--line-x`), surrounded by a counting zone (`--zone-width`). When a tracked person enters the zone from one side and exits from the opposite side, a crossing is counted. This means the person only needs to pass through the narrow zone, not be visible across the entire frame.

Per-track state (`TrackState`):
- `entry_side = None` — person not yet engaged with the zone
- `entry_side = "left"/"right"` — person entered the zone, entry side recorded
- On zone exit: opposite side → count crossing, same side → ignore (turned back)
- After any exit, state resets — person can be counted again if they re-enter

Position smoothing (5-frame moving average) reduces noise from jittery bounding boxes.

All visualization is rendered via OpenCV in the callback. The GStreamer pipeline uses `fakesink` to save compute.

## Architecture
- **Type:** Pipeline app
- **Pattern:** source -> inference_wrapper -> tracker -> callback -> display(fakesink)
- **Template base:** detection
- **Models:** YOLOv8m (hailo8, hailo10h), YOLOv8s (hailo8l)
- **Hardware:** hailo8, hailo8l, hailo10h
- **Postprocess:** libyolo_hailortpp_postprocess.so (filter_letterbox)

## Key Files
| File | Purpose |
|------|---------|
| `line_crossing_counter_pipeline.py` | GStreamerApp subclass, pipeline string, CLI args (`--line-x`, `--zone-width`, `--labels-json`) |
| `line_crossing_counter.py` | Zone-based crossing state machine callback, OpenCV overlay, entry point |
| `README.md` | User documentation |

## Pipeline Structure
```
SOURCE_PIPELINE
  -> INFERENCE_PIPELINE_WRAPPER(INFERENCE_PIPELINE)  # YOLOv8, preserves resolution
    -> TRACKER_PIPELINE(class_id=1)                  # tracks persons
      -> USER_CALLBACK_PIPELINE                      # zone-based line-crossing counting
        -> DISPLAY_PIPELINE(fakesink)                # no GStreamer display
```

## Callback Data Available
```python
roi = hailo.get_roi_from_buffer(buffer)
detections = roi.get_objects_typed(hailo.HAILO_DETECTION)
for detection in detections:
    label = detection.get_label()          # filter for "person"
    bbox = detection.get_bbox()
    x_center = bbox.xmin() + bbox.width() / 2.0  # normalized [0,1]
    track = detection.get_objects_typed(hailo.HAILO_UNIQUE_ID)
    track_id = track[0].get_id() if len(track) == 1 else 0
```

## How to Extend
- **Count other objects**: Change `label != "person"` filter to other COCO classes
- **Multiple lines**: Add more LineCrossingCallbackData instances for multiple zones
- **Zone counting**: Combine with zone_polygon pattern for area-based counting
- **Data export**: Add CSV/JSON logging in the callback
- **Alerts**: Trigger notifications when counts exceed thresholds
- **Adjust zone width**: `--zone-width 0.05` for precise, `--zone-width 0.2` for forgiving

## Related Apps
- **detection** — Template this app was based on
- **parking_lot_occupancy** (community) — Zone-based counting instead of line crossing
