# Tiling

## What This App Does
Tiled inference for detecting small objects in high-resolution video. Instead of downscaling the entire frame to model input size (which loses small-object detail), this app splits the frame into overlapping tiles, runs detection on each tile independently, and aggregates the results with NMS deduplication. Supports both single-scale and multi-scale tiling modes, with automatic tile grid calculation based on input resolution and model input size.

This is essential for surveillance, drone imagery, and any scenario where objects of interest occupy only a small portion of a high-resolution frame.

## Architecture
- **Type:** Pipeline app
- **Pattern:** source -> tile_cropper(inference) -> callback -> display
- **Models:**
  - hailo8: `hailo_yolov8n_4_classes_vga` (default), extras: ssd_mobilenet_v1, ssd_mobilenet_v1_visdrone
  - hailo8l: `hailo_yolov8n_4_classes_vga` (default), same extras
  - hailo10h: `hailo_yolov8n_4_classes_vga` (default), same extras
- **Hardware:** hailo8, hailo8l, hailo10h
- **Postprocess:** Tiling-specific postprocess .so (resolved via `TILING_POSTPROCESS_SO_FILENAME`)
- **Config JSON:** Labels JSON auto-detected from HEF file, or pass `--labels-json`

## Key Files
| File | Purpose |
|------|---------|
| `tiling.py` | Main entry point, callback printing detections |
| `tiling_pipeline.py` | `GStreamerTilingApp` subclass, pipeline definition with TILE_CROPPER_PIPELINE |
| `configuration.py` | `TilingConfiguration` class -- auto/manual tile grid calculation |
| `tile_calculator.py` | Tile grid math: auto-calculate tiles, overlaps, batch sizes |

## Pipeline Structure
```
SOURCE_PIPELINE
  -> TILE_CROPPER_PIPELINE(
       inner: INFERENCE_PIPELINE
       tiles_along_x_axis=N, tiles_along_y_axis=M
       overlap_x_axis, overlap_y_axis
       tiling_mode=0|1, scale_level=0|1|2|3
       iou_threshold, border_threshold
     )
    -> USER_CALLBACK_PIPELINE
      -> DISPLAY_PIPELINE
```

The `TILE_CROPPER_PIPELINE` uses `hailotilecropper` + `hailotileaggregator` elements. The cropper splits the frame into tiles, each tile is processed by the inner inference pipeline, and the aggregator combines results with `flatten-detections=true` and IoU-based NMS.

Key parameters:
- Tile grid auto-calculated from input resolution and model input size
- `tiling_mode=0` (single-scale), `tiling_mode=1` (multi-scale)
- `scale_level`: 1={1x1}, 2={1x1+2x2}, 3={1x1+2x2+3x3} additional grids
- Batch size = total number of tiles (auto-calculated)
- Default video: `tiling_visdrone_720p.mp4`

## Callback Data Available
```python
roi = hailo.get_roi_from_buffer(buffer)
detections = roi.get_objects_typed(hailo.HAILO_DETECTION)
for detection in detections:
    label = detection.get_label()           # e.g., "car", "person"
    confidence = detection.get_confidence()  # float 0-1
    # Note: no tracking in this pipeline
```

## Common Use Cases
- Drone/aerial imagery object detection
- Wide-area surveillance with small-object detection
- Satellite image analysis
- Traffic monitoring from elevated cameras
- Quality inspection of large surfaces

## How to Extend
- **Manual tile grid:** Use `--tiles-x 4 --tiles-y 3` to override auto-calculation
- **Multi-scale:** Use `--multi-scale --scale-levels 2` for combined coarse + fine detection
- **Adjust overlap:** Use `--min-overlap 0.2` for more overlap (catches objects on tile boundaries)
- **Tune NMS:** Use `--iou-threshold 0.3` and `--border-threshold 0.15`
- **Custom labels:** Use `--labels-json <path>` for custom class names
- **Swap models:** Use `--hef-path <path>` or `--list-models`; VisDrone models work well for drone imagery

## Related Apps
| App | When to use instead |
|-----|-------------------|
| detection | If objects are large enough to detect without tiling |
| detection_simple | For the simplest possible detection pipeline |
| clip | If you need text-based classification of detected objects |
