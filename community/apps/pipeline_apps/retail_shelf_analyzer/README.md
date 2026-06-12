# Retail Shelf Analyzer

Real-time retail shelf analysis using tiled detection on Hailo-8. Detects small products on store shelves from a wide-angle, high-resolution camera by splitting frames into overlapping tiles, running YOLOv8 detection on each tile, and aggregating results. Provides per-zone product counts and empty shelf alerts.

## Prerequisites

- Hailo-8 accelerator (also works on Hailo-8L and Hailo-10H)
- TAPPAS installed (`source setup_env.sh`)
- Resources downloaded (`hailo-download-resources`)
- C++ postprocess compiled (`hailo-compile-postprocess`)

## How to Run

```bash
# With USB camera (wide-angle, high-res recommended)
python community/apps/pipeline_apps/retail_shelf_analyzer/retail_shelf_analyzer.py --input usb

# With a video file
python community/apps/pipeline_apps/retail_shelf_analyzer/retail_shelf_analyzer.py --input path/to/shelf_video.mp4

# With default tiling demo video
python community/apps/pipeline_apps/retail_shelf_analyzer/retail_shelf_analyzer.py

# Customize shelf zones and thresholds
python community/apps/pipeline_apps/retail_shelf_analyzer/retail_shelf_analyzer.py \
    --input usb \
    --num-zones 4 \
    --empty-threshold 3 \
    --confidence-threshold 0.5

# Manual tile grid for specific camera setup
python community/apps/pipeline_apps/retail_shelf_analyzer/retail_shelf_analyzer.py \
    --input usb \
    --tiles-x 4 --tiles-y 3 \
    --min-overlap 0.15
```

## Architecture

```
USB Camera / Video File
    |
    v
SOURCE_PIPELINE (decode + scale)
    |
    v
TILE_CROPPER_PIPELINE
    |-- hailotilecropper (splits frame into NxM overlapping tiles)
    |     |
    |     v
    |   INFERENCE_PIPELINE (YOLOv8 detection per tile)
    |     |
    |     v
    |-- hailotileaggregator (merge detections + NMS dedup)
    |
    v
USER_CALLBACK_PIPELINE
    |-- app_callback: filter by confidence, assign to shelf zones,
    |   count products per zone, flag empty shelves
    |
    v
DISPLAY_PIPELINE (live overlay with bounding boxes)
```

## Retail-Specific CLI Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--num-zones` | 3 | Number of horizontal shelf zones (top to bottom) |
| `--empty-threshold` | 2 | Min detections per zone before "empty" alert |
| `--confidence-threshold` | 0.4 | Min detection confidence to count a product |

All tiling arguments from the base tiling app are also available (`--tiles-x`, `--tiles-y`, `--min-overlap`, `--multi-scale`, `--scale-levels`, `--iou-threshold`, `--border-threshold`, `--labels-json`).

## Customization

- **Shelf zone layout:** Adjust `--num-zones` to match the number of shelves visible in the camera. Zones are horizontal bands from top to bottom.
- **Sensitivity:** Lower `--confidence-threshold` to detect more items (may increase false positives). Raise `--empty-threshold` to reduce false empty-shelf alerts.
- **Tile grid:** Use `--tiles-x` and `--tiles-y` for manual control, or let auto-tiling choose based on resolution.
- **Multi-scale:** Use `--multi-scale --scale-levels 2` for combined coarse and fine detection, useful if product sizes vary significantly.
- **Custom model:** Use `--hef-path <path>` to swap in a retail-specific detection model (e.g., trained on SKU data).
