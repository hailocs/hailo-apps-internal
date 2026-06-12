# Line Crossing Counter - Zone-Based Directional People Counter

Real-time people counting application that detects when persons cross a virtual vertical line in the video frame. Uses a zone-based approach: a narrow band around the counting line tracks when a person enters from one side and exits from the other. This means a person only needs to pass through the zone, not be visible across the entire frame.

## How It Works

1. **Detection**: YOLOv8 detects persons in each frame via the Hailo accelerator.
2. **Tracking**: HailoTracker assigns persistent IDs to each person across frames.
3. **Zone-based crossing**: A counting zone is centered on the virtual line. When a tracked person enters the zone, the app records which side they came from. When they exit the zone on the opposite side, a crossing is counted. If they exit on the same side (turned back), no count is recorded.
4. **Display**: All visualization (zone band, bounding boxes, center points, counts) is rendered in a dedicated OpenCV window ("Line Crossing Counter"). The GStreamer pipeline uses `fakesink` to save compute — no GStreamer display overhead.

## Prerequisites

- Hailo-8 accelerator (also works on Hailo-8L and Hailo-10H)
- TAPPAS environment set up (`source setup_env.sh`)
- Resources downloaded (`hailo-download-resources`)
- Postprocess compiled (`hailo-compile-postprocess`)

## Usage

```bash
# Default: video file input, line at X=0.5, zone width 10%
# Opens the "Line Crossing Counter" OpenCV window with full overlay
python community/apps/pipeline_apps/line_crossing_counter/line_crossing_counter.py

# USB camera input
python community/apps/pipeline_apps/line_crossing_counter/line_crossing_counter.py --input usb

# Custom line position (30% from left edge)
python community/apps/pipeline_apps/line_crossing_counter/line_crossing_counter.py --input usb --line-x 0.3

# Wider counting zone (20% of frame width)
python community/apps/pipeline_apps/line_crossing_counter/line_crossing_counter.py --input usb --zone-width 0.2

# Show FPS counter
python community/apps/pipeline_apps/line_crossing_counter/line_crossing_counter.py --input usb --show-fps
```

## Display

This app defaults to `--use-frame` mode. All visualization is rendered via OpenCV in the callback and displayed in the **"Line Crossing Counter"** window:

- **Counting zone**: Semi-transparent band showing the active counting area
- **Center line**: Red vertical line at `--line-x` position
- **Bounding boxes**: Per-person rectangles, color-coded by state
- **Center points**: Filled dots at each person's bbox center
- **Track IDs**: Labels above each bbox (e.g., `ID:42 [L]` = entered from left)
- **Counts**: L->R, R->L, and total crossing counts

The GStreamer pipeline sends video to `fakesink` instead of a display sink, saving GPU/CPU resources. To disable the OpenCV window and run headless (console output only), you would need to modify the code to support headless mode.

## Architecture

```
SOURCE_PIPELINE (USB camera / video file)
  -> INFERENCE_PIPELINE_WRAPPER(INFERENCE_PIPELINE)   # YOLOv8 detection, preserves resolution
    -> TRACKER_PIPELINE(class_id=1)                   # Tracks persons (class 1)
      -> USER_CALLBACK_PIPELINE                       # Zone-based counting + OpenCV overlay
        -> DISPLAY_PIPELINE(fakesink)                 # No GStreamer display (saves compute)
```

## CLI Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--input` | sample video | Input source: `usb`, `rtsp://...`, or path to video file |
| `--line-x` | 0.5 | Virtual line X-position (0.0 = left edge, 1.0 = right edge) |
| `--zone-width` | 0.1 | Width of the counting zone centered on the line (0.0-1.0) |
| `--show-fps` | off | Show FPS counter in display |
| `--labels-json` | auto | Path to custom labels JSON |
| `--hef-path` | auto | Path to custom HEF model |

Note: `--use-frame` is enabled by default for this app (other pipeline apps default to off).

## Zone-Based Counting

The counting zone is a narrow vertical band centered on the counting line:

```
         Zone
    |<--------->|
    |   |   |   |
    |   | L |   |
    |   | I |   |
    |   | N |   |
    |   | E |   |
    |   |   |   |
    left  ^  right
    edge  |  edge
        line_x
```

- A person entering the zone from the **left** and exiting from the **right** → **L->R** count
- A person entering from the **right** and exiting from the **left** → **R->L** count
- A person entering and exiting from the **same side** → no count (turned back)
- After exiting the zone (either side), the person's state resets — if they re-enter the zone, they can be counted again

Position is smoothed over several frames to reduce noise from jittery bounding boxes near zone boundaries.

The `--zone-width` parameter controls how wide the counting band is. Default is 0.1 (10% of frame width). Wider zones are more forgiving but increase the chance of tracker ID switches during the crossing.

## Customization

- **Change the counting line**: Use `--line-x` to move the virtual line. Values close to 0.0 place it near the left edge; close to 1.0 near the right edge.
- **Adjust zone width**: Use `--zone-width` to control sensitivity. Narrow (0.05) for precise counting, wider (0.2) for more forgiving detection.
- **Swap model**: Use `--hef-path` or `--list-models` to see available detection models.
- **Count other objects**: Modify the `label != "person"` filter in `app_callback()` to track vehicles, animals, etc.
- **Add alerts**: Extend `LineCrossingCallbackData` to trigger alerts when counts exceed thresholds.
- **Export data**: Add CSV/JSON logging in the callback for analytics.
