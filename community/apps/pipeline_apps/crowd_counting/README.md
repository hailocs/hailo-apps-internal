# Crowd Counting - Virtual Line Crossing Counter

Real-time people counting application that detects when persons cross a virtual horizontal line in the video frame. Tracks crossing direction (left-to-right vs right-to-left) using object tracking and reports running totals.

## How It Works

1. **Detection**: YOLOv8 detects persons in each frame via the Hailo accelerator.
2. **Tracking**: HailoTracker assigns persistent IDs to each person across frames.
3. **Line crossing**: The callback monitors each tracked person's vertical center position. When a person's center crosses the virtual line between consecutive frames, a crossing event is recorded with its direction.
4. **Display**: Optionally overlays the counting line, direction indicators, and running totals on the video.

## Prerequisites

- Hailo-8 accelerator (also works on Hailo-8L and Hailo-10H)
- TAPPAS environment set up (`source setup_env.sh`)
- Resources downloaded (`hailo-download-resources`)
- Postprocess compiled (`hailo-compile-postprocess`)

## Usage

```bash
# Default: video file input, line at Y=0.5 (middle)
python community/apps/pipeline_apps/crowd_counting/crowd_counting.py

# USB camera input
python community/apps/pipeline_apps/crowd_counting/crowd_counting.py --input usb

# Custom line position (30% from top)
python community/apps/pipeline_apps/crowd_counting/crowd_counting.py --input usb --line-y 0.3

# With visual overlay (opens separate OpenCV window)
python community/apps/pipeline_apps/crowd_counting/crowd_counting.py --input usb --use-frame

# Show FPS counter
python community/apps/pipeline_apps/crowd_counting/crowd_counting.py --input usb --show-fps
```

## Architecture

```
SOURCE_PIPELINE (USB camera / video file)
  -> INFERENCE_PIPELINE_WRAPPER(INFERENCE_PIPELINE)   # YOLOv8 detection, preserves resolution
    -> TRACKER_PIPELINE(class_id=1)                   # Tracks persons (class 1)
      -> USER_CALLBACK_PIPELINE                       # Line-crossing counting logic
        -> DISPLAY_PIPELINE                           # hailooverlay + fpsdisplaysink
```

## CLI Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--input` | sample video | Input source: `usb`, `rtsp://...`, or path to video file |
| `--line-y` | 0.5 | Virtual line Y-position (0.0 = top, 1.0 = bottom) |
| `--use-frame` | off | Enable OpenCV overlay with line and counts |
| `--show-fps` | off | Show FPS counter in display |
| `--labels-json` | auto | Path to custom labels JSON |
| `--hef-path` | auto | Path to custom HEF model |

## Customization

- **Change the counting line**: Use `--line-y` to move the virtual line. Values close to 0.0 place it near the top; close to 1.0 near the bottom.
- **Swap model**: Use `--hef-path` or `--list-models` to see available detection models.
- **Count other objects**: Modify the `label != "person"` filter in `app_callback()` to track vehicles, animals, etc.
- **Add alerts**: Extend `CrowdCountingCallbackData` to trigger alerts when counts exceed thresholds.
- **Export data**: Add CSV/JSON logging in the callback for analytics.

## Direction Convention

The virtual line is horizontal. Crossings are detected by monitoring vertical movement:
- **L->R**: Person moves from above the line to below it (top-to-bottom in frame)
- **R->L**: Person moves from below the line to above it (bottom-to-top in frame)

For a camera mounted above a corridor looking down, top-to-bottom motion corresponds to left-to-right physical movement (and vice versa). Adjust the `--line-y` position and interpretation based on your camera mounting angle.
