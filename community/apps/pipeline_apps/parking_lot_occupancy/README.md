# Parking Lot Occupancy

Real-time parking lot occupancy monitoring using YOLOv8 object detection on Hailo-8. Detects vehicles (car, truck, bus, motorcycle) and tracks them across user-defined parking zones. Each zone displays occupied/free status with color-coded overlays.

## Prerequisites

- Hailo-8 accelerator
- TAPPAS runtime installed
- Environment activated: `source setup_env.sh`
- Resources downloaded: `hailo-download-resources`
- C++ postprocess compiled: `hailo-compile-postprocess`

## How to Run

```bash
# With default 2x2 grid zones and video file
python community/apps/pipeline_apps/parking_lot_occupancy/parking_lot_occupancy.py --input path/to/parking_video.mp4

# With USB camera
python community/apps/pipeline_apps/parking_lot_occupancy/parking_lot_occupancy.py --input usb

# With custom zone definitions and frame overlay
python community/apps/pipeline_apps/parking_lot_occupancy/parking_lot_occupancy.py \
    --input usb \
    --zones-json zones.json \
    --use-frame

# Show available models
python community/apps/pipeline_apps/parking_lot_occupancy/parking_lot_occupancy.py --list-models
```

## Zone Configuration

Zones are defined in a JSON file with normalized [0,1] coordinates:

```json
[
    {
        "name": "Zone A",
        "polygon": [[0.0, 0.0], [0.5, 0.0], [0.5, 0.5], [0.0, 0.5]],
        "capacity": 5
    },
    {
        "name": "Zone B",
        "polygon": [[0.5, 0.0], [1.0, 0.0], [1.0, 0.5], [0.5, 0.5]],
        "capacity": 3
    }
]
```

Each zone has:
- `name`: Display name shown on the overlay
- `polygon`: List of [x, y] vertices in normalized coordinates (0.0 to 1.0)
- `capacity`: Number of parking spots in that zone (used for full/available status)

If no `--zones-json` is provided, a default 2x2 grid is used for demonstration.

## Architecture

```
SOURCE_PIPELINE (USB camera / video file)
  -> INFERENCE_PIPELINE_WRAPPER(INFERENCE_PIPELINE)  # YOLOv8m detection, preserves resolution
    -> TRACKER_PIPELINE(class_id=-1)                 # Track all detected objects
      -> USER_CALLBACK_PIPELINE                      # Zone occupancy logic
        -> DISPLAY_PIPELINE                          # hailooverlay + display
```

The callback:
1. Filters detections for vehicle classes only (car, truck, bus, motorcycle)
2. Computes bounding box center for each vehicle
3. Tests which zone polygon contains each vehicle center (ray-casting algorithm)
4. Counts occupied spots per zone and compares against capacity
5. Optionally draws zone overlays on the frame (with `--use-frame`)

## Customization

- **Zone polygons**: Create a JSON file with polygon coordinates matching your camera view
- **Vehicle classes**: Edit `VEHICLE_LABELS` in `parking_lot_occupancy_pipeline.py`
- **Confidence threshold**: Modify `nms_score_threshold` in the pipeline class
- **Model**: Use `--hef-path` to specify a different detection model
- **Output**: Add data logging or API integration in the callback function
