# Retail Shelf Analyzer (Tiled Detection)

## What This App Does
High-resolution shelf analysis using tiled detection to find small products. Splits each frame into overlapping NxM tiles, runs YOLOv8 detection per tile, aggregates with NMS deduplication, then divides the frame into horizontal shelf zones, counts products per zone, and flags understocked shelves.

## Architecture
- **Type:** Pipeline app (tiled detection)
- **Pattern:** Tile cropper (`hailotilecropper`) → per-tile YOLOv8 detection → tile aggregator (`hailotileaggregator`) → callback (per-zone counting) → display
- **Models:** YOLOv8 detection (COCO object classes; configurable labels)
- **Hardware:** hailo8, hailo8l, hailo10h
- **Postprocess:** C++ `libtiling_postprocess.so` (tile aggregation with NMS)

## Key Files
| File | Purpose |
|------|---------|
| `retail_shelf_analyzer.py` | Entry point + callback: assigns detections to horizontal zones, per-zone counts, empty-shelf alerts |
| `retail_shelf_analyzer_pipeline.py` | `GStreamerApp` subclass: `TilingConfiguration` + tiled detection pipeline (tiles_x/y, overlap, IOU/border thresholds) |

## How to Run
```bash
source setup_env.sh
python community/apps/pipeline_apps/retail_shelf_analyzer/retail_shelf_analyzer.py --input usb
```
Optional: `--num-zones 3`, `--empty-threshold 2`, `--tiles-x 4 --tiles-y 3`.

## How to Extend
- Swap in a custom product-detection model to count exact SKUs per shelf.
- Add planogram-compliance checking by defining expected per-zone layouts and alerting on mismatches.
