# Vampire Mirror

A real-time "mirror" where vampires are invisible. The app uses instance segmentation with ByteTrack tracking to detect and track people. The first person detected is treated as human (visible in the mirror), while all subsequent people are treated as vampires -- their pixels are replaced with the saved background image, making them disappear.

## How It Works

1. **Background capture**: During the first 30 frames, the app captures and averages the scene (with no people) to build a clean background image.
2. **Instance segmentation**: Each frame is processed by a YOLO segmentation model running on the Hailo accelerator, producing per-person pixel masks.
3. **Tracking**: ByteTrack assigns persistent track IDs to each detected person across frames.
4. **Vampire logic**: The first tracked person is automatically assigned as "human" (visible). All other tracked people are "vampires" -- their segmentation mask pixels are replaced with the corresponding background pixels.
5. **Output**: The result looks like a normal camera feed, except vampires simply do not appear.

## Requirements

- Hailo-8, Hailo-8L, or Hailo-10H accelerator
- USB camera (or video file input)
- Python environment with hailo-apps-infra installed

## Usage

```bash
# Basic usage with USB camera
./run.sh --input usb --show-fps

# Or via Python module
python3 -m hailo_apps.python.pipeline_apps.vampire_mirror.vampire_mirror --input usb --show-fps

# Pre-configure specific track IDs as human
python3 -m hailo_apps.python.pipeline_apps.vampire_mirror.vampire_mirror --input usb --human-ids 1,3

# Use a video file
python3 -m hailo_apps.python.pipeline_apps.vampire_mirror.vampire_mirror --input /path/to/video.mp4
```

## CLI Arguments

All standard pipeline arguments are supported (`--input`, `--arch`, `--show-fps`, `--hef-path`, etc.), plus:

| Argument | Default | Description |
|---|---|---|
| `--human-ids` | `""` | Comma-separated track IDs to treat as human (visible). If empty, the first detected person is automatically assigned as human. |

## Tips

- **Background capture**: Make sure no people are in the frame during the first ~1 second (30 frames) when the app starts. This is when the background image is captured.
- **Lighting**: The background replacement works best when lighting is consistent. Avoid sudden changes in lighting after the background is captured.
- **Multiple humans**: Use `--human-ids 1,2,3` to pre-assign specific track IDs as human if you want multiple visible people.

## Architecture

```
USB Camera --> SOURCE_PIPELINE --> INFERENCE_PIPELINE (yolov5m_seg) -->
  TRACKER_PIPELINE (ByteTrack) --> USER_CALLBACK_PIPELINE (vampire logic) -->
  DISPLAY_PIPELINE (with use_frame overlay)
```

The app subclasses `GStreamerInstanceSegmentationApp` to reuse the full instance segmentation pipeline, and adds a custom callback that implements the vampire replacement logic.
