# Vampire Mirror

A real-time "mirror" where vampires are invisible. Uses instance segmentation with ByteTrack tracking for pixel-accurate person masks. Features a dynamic background that adapts to lighting changes, a portrait center-crop display from a wider landscape capture, and a buffer zone that prevents people from suddenly appearing or disappearing.

## How It Works

1. **Background capture**: During the first 30 frames, the app averages the scene to build a clean background. No people should be in the frame during this phase.
2. **Dynamic background**: After capture, the background continuously updates via EMA (exponential moving average) for all pixels not covered by a vampire. This handles lighting changes and moving objects.
3. **Instance segmentation**: Each frame is processed by a YOLO segmentation model on the Hailo accelerator, producing per-person pixel masks.
4. **Tracking**: ByteTrack assigns persistent track IDs to each detected person across frames.
5. **Vampire logic**: The VampireEngine decides who is a vampire based on face recognition (when available). Vampires have their pixels replaced with the background.
6. **Portrait display**: The camera captures in landscape mode. Only a portrait center crop is displayed as the "mirror view". The extra width on each side is a buffer zone.
7. **Safe entry**: If a person enters the mirror view before being identified as a vampire, they are permanently marked as human to prevent sudden disappearance.

## Requirements

- Hailo-8, Hailo-8L, or Hailo-10H accelerator
- USB camera (or video file input)
- Python environment with hailo-apps-infra installed

## Usage

```bash
# Basic usage — landscape capture with portrait mirror display
python community/apps/pipeline_apps/vampire_mirror/vampire_mirror.py \
    --input usb --width 1280 --height 720

# Custom mirror aspect ratio (3:4 instead of 9:16)
python community/apps/pipeline_apps/vampire_mirror/vampire_mirror.py \
    --input usb --mirror-ratio 3:4

# Faster background adaptation
python community/apps/pipeline_apps/vampire_mirror/vampire_mirror.py \
    --input usb --bg-alpha 0.1

# Use a video file
python community/apps/pipeline_apps/vampire_mirror/vampire_mirror.py \
    --input /path/to/video.mp4
```

## CLI Arguments

All standard pipeline arguments are supported (`--input`, `--arch`, `--show-fps`, `--hef-path`, etc.), plus:

| Argument | Default | Description |
|---|---|---|
| `--mirror-ratio` | `9:16` | Portrait mirror aspect ratio as W:H |
| `--bg-alpha` | `0.05` | Background EMA blending factor. Higher = faster adaptation |
| `--bg-capture-frames` | `30` | Number of initial frames for background capture |
| `--no-face-recognition` | off | Disable face recognition (everyone visible) |

## Tips

- **Background capture**: Make sure no people are in the frame during the first ~1 second when the app starts.
- **Wider capture = better buffer**: Use `--width 1280 --height 720` (or wider) to give the model more time to identify people before they enter the mirror view.
- **Lighting changes**: The dynamic background handles gradual lighting changes. Increase `--bg-alpha` for faster adaptation.

## Architecture

```
USB Camera (landscape) --> SOURCE_PIPELINE --> INFERENCE_PIPELINE (yolov5m_seg)
  --> TRACKER_PIPELINE (ByteTrack) --> USER_CALLBACK_PIPELINE:
      [VampireEngine decides] --> [mask replacement with dynamic background]
      --> [center crop to portrait] --> DISPLAY_PIPELINE
```

### Module Structure

| File | Purpose |
|------|---------|
| `vampire_mirror.py` | Entry point, callback, main() |
| `vampire_mirror_pipeline.py` | GStreamerApp subclass with CLI args |
| `frame_geometry.py` | Center crop and buffer zone math |
| `background_manager.py` | Dynamic background with EMA |
| `vampire_engine.py` | Vampire/human decision engine |
