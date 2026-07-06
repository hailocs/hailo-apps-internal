# Retail Shelf Analyzer

Real-time retail shelf analysis using tiled detection on Hailo-8 / Hailo-8L / Hailo-10H. Detects small products on store shelves from a wide-angle, high-resolution camera by splitting frames into overlapping tiles, running YOLOv8 detection on each tile, and aggregating results. Provides per-zone product counts and empty shelf alerts.

> **Default model is a DEMO, not a product detector.** With no `--hef-path`, the tiling pipeline resolves `hailo_yolov8n_4_classes_vga` — a VisDrone-derived 4-class detector whose classes are **person / vehicle / face / license_plate**. It contains **no retail product classes**, so out of the box this app detects **zero** shelf products and every zone will read as empty. The default model is useful only for verifying the tiling/zone/alert plumbing end to end (e.g. counting people walking past). **For real shelf analysis you must supply a product/SKU detector or a COCO-trained YOLOv8 HEF via `--hef-path`** (with a matching `--labels-json`). The app prints a startup WARNING whenever it is running on the demo model.

## Prerequisites

- Hailo-8, Hailo-8L, or Hailo-10H accelerator
- TAPPAS installed (`source setup_env.sh`)
- Resources downloaded (`hailo-download-resources`)
- C++ postprocess compiled (`hailo-compile-postprocess`)

## How to Run

```bash
# With USB camera (wide-angle, high-res recommended)
python -m community.apps.pipeline_apps.retail_shelf_analyzer.retail_shelf_analyzer --input usb

# With a video file
python -m community.apps.pipeline_apps.retail_shelf_analyzer.retail_shelf_analyzer --input path/to/shelf_video.mp4

# With default tiling demo video (demo model only — see note above)
python -m community.apps.pipeline_apps.retail_shelf_analyzer.retail_shelf_analyzer

# Production: supply a real product/SKU or COCO YOLOv8 model
python -m community.apps.pipeline_apps.retail_shelf_analyzer.retail_shelf_analyzer \
    --input usb \
    --hef-path /path/to/product_detector.hef \
    --labels-json /path/to/product_labels.json

# Customize shelf zones and thresholds
python -m community.apps.pipeline_apps.retail_shelf_analyzer.retail_shelf_analyzer \
    --input usb \
    --num-zones 4 \
    --empty-threshold 3 \
    --confidence-threshold 0.5

# Manual tile grid for specific camera setup
python -m community.apps.pipeline_apps.retail_shelf_analyzer.retail_shelf_analyzer \
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
- **Custom model:** Use `--hef-path <path>` to swap in a retail-specific detection model (e.g., trained on SKU data), with `--labels-json <path>` for its label space. This is required for any real deployment — the bundled demo model has no product classes (see the note at the top of this README).
- **Excluded labels:** The callback skips a hard-coded set of COCO non-product labels (`person`, `cat`, `dog`, ...) so passers-by are not counted as products. This filter is **model-dependent** and only meaningful with a COCO-trained model; with the default 4-class demo model only `person` matches. When you swap in a product detector, update `EXCLUDED_LABELS` in `retail_shelf_analyzer.py` to match that model's labels (or empty it).
