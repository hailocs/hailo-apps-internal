# Parking Lot Occupancy Monitor

## What This App Does
Real-time vehicle detection and zone-based occupancy tracking. Detects vehicles (car, truck, bus, motorcycle), assigns each to user-defined polygon zones via a point-in-polygon test, and shows color-coded zone status (green = available, red = full).

## Architecture
- **Type:** Pipeline app
- **Pattern:** Detection → tracker → callback (polygon zone assignment) → display overlay
- **Models:** YOLOv8 detection (COCO vehicle classes)
- **Hardware:** hailo8 (primary), hailo8l, hailo10h
- **Postprocess:** C++ `libdetection_postprocess.so` + Python callback for zone logic and overlay

## Key Files
| File | Purpose |
|------|---------|
| `parking_lot_occupancy.py` | Entry point + callback: `ParkingZone` (normalized polygon + ray-cast test), per-zone occupancy counting, overlay |
| `parking_lot_occupancy_pipeline.py` | `GStreamerApp` subclass: loads zones from JSON or a default 2×2 grid; wraps YOLOv8 detection |

## How to Run
```bash
source setup_env.sh
python community/apps/pipeline_apps/parking_lot_occupancy/parking_lot_occupancy.py --input usb
```
Optional: `--zones-json zones.json`, `--use-frame`.

## How to Extend
- Define custom zones in a JSON file (normalized polygon coordinates) for your camera layout.
- Add a historical occupancy database for time-of-day forecasting, or expose available zones to a reservation/navigation app.
