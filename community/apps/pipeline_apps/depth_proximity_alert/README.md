# Depth Proximity Alert

Real-time depth-based proximity alerting using SCDepthV3 monocular depth estimation on Hailo-8. Monitors a configurable region of interest in the depth map and triggers visual/console alerts when objects enter a proximity threshold.

## Prerequisites

- Hailo-8, Hailo-8L, or Hailo-10H accelerator
- SCDepthV3 model HEF (downloaded via `hailo-download-resources`)
- Depth postprocess plugin (compiled via `hailo-compile-postprocess`)
- USB camera or video file

## How to Run

```bash
# Activate environment
source setup_env.sh

# Run with USB camera (default settings)
python community/apps/pipeline_apps/depth_proximity_alert/depth_proximity_alert.py --input usb

# Run with custom proximity threshold (lower = closer objects trigger alert)
python community/apps/pipeline_apps/depth_proximity_alert/depth_proximity_alert.py \
    --input usb \
    --proximity-threshold 0.2

# Run with custom alert region (x y width height, normalized 0-1)
python community/apps/pipeline_apps/depth_proximity_alert/depth_proximity_alert.py \
    --input usb \
    --alert-region 0.25 0.25 0.5 0.5

# Run with video file
python community/apps/pipeline_apps/depth_proximity_alert/depth_proximity_alert.py \
    --input path/to/video.mp4

# Show available models
python community/apps/pipeline_apps/depth_proximity_alert/depth_proximity_alert.py --list-models
```

## Architecture

```
USB Camera / Video File
        |
  SOURCE_PIPELINE
        |
  INFERENCE_PIPELINE_WRAPPER
    |-- INFERENCE_PIPELINE (SCDepthV3 on Hailo)
    |-- Bypass (original resolution)
        |
  USER_CALLBACK_PIPELINE  <-- Proximity alert logic here
        |
  DISPLAY_PIPELINE (depth map overlay + alert indicators)
```

## CLI Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--proximity-threshold` | 0.3 | Depth threshold (0.0-1.0). Lower values mean only very close objects trigger alerts. |
| `--alert-region` | Center 50% | Region of interest as `x y w h` (normalized 0-1). Only this area is monitored. |
| `--input` | default video | Input source: `usb`, RTSP URL, or file path |
| `--show-fps` | false | Display FPS counter on video |

## Customization

- **Adjust sensitivity**: Lower `--proximity-threshold` to only alert on very close objects, raise it to alert earlier.
- **Focus on a region**: Use `--alert-region` to monitor only part of the frame (e.g., a doorway or path).
- **Add audio alerts**: Extend the callback to play a sound using `subprocess` or a library like `playsound`.
- **Export events**: Log proximity events to a file or send them to an API endpoint.
- **Combine with detection**: Add a detection stage to get per-object depth estimates instead of region-based analysis.

## How It Works

1. SCDepthV3 produces a per-pixel relative depth map each frame
2. The callback extracts depth values from the configured region of interest
3. The 5th percentile depth value represents the closest object in the ROI
4. A smoothing window (10 frames) reduces noise and false positives
5. When the smoothed minimum depth falls below the threshold, an alert fires
6. A cooldown timer (1 second) prevents alert spam
