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

# Custom mirror aspect ratio (e.g. 9:16 instead of the default 3:4)
python community/apps/pipeline_apps/vampire_mirror/vampire_mirror.py \
    --input usb --mirror-ratio 9:16

# Faster background adaptation
python community/apps/pipeline_apps/vampire_mirror/vampire_mirror.py \
    --input usb --bg-alpha 0.1

# Debug: show bounding boxes + segmentation contours over the mirror view
python community/apps/pipeline_apps/vampire_mirror/vampire_mirror.py \
    --input usb --show-overlay

# Use a video file
python community/apps/pipeline_apps/vampire_mirror/vampire_mirror.py \
    --input /path/to/video.mp4
```

## CLI Arguments

All standard pipeline arguments are supported (`--input`, `--arch`, `--show-fps`, `--hef-path`, etc.), plus:

| Argument | Default | Description |
|---|---|---|
| `--mirror-ratio` | `3:4` | Portrait mirror aspect ratio as W:H |
| `--bg-alpha` | `0.05` | Background EMA blending factor. Higher = faster adaptation |
| `--bg-capture-frames` | `30` | Number of initial frames for background capture |
| `--bg-process` / `--no-bg-process` | on | Run the background EMA in a subprocess and draw vampires via the `hailovampire_overlay` C++ element. `--no-bg-process` is a debug fallback that runs the EMA in-process and disables the vampire-invisibility effect |
| `--show-overlay` / `--no-show-overlay` | off | Draw the `hailooverlay` bounding-box / segmentation overlay on the displayed frame. Off by default so the mirror has no debug graphics; enable for debugging |
| `--dilate-radius` | `25` | Dilation kernel radius (px) applied to each vampire mask before background compositing. Bigger = wider invisibility halo around the body |
| `--dilate-iterations` | `3` | Dilation iterations for the vampire mask. Combine with `--dilate-radius` to control halo size |
| `--no-face-recognition` | off | Disable face recognition (everyone visible) |

## Tips

- **Background capture**: Make sure no people are in the frame during the first ~1 second when the app starts.
- **Wider capture = better buffer**: Use `--width 1280 --height 720` (or wider) to give the model more time to identify people before they enter the mirror view.
- **Lighting changes**: The dynamic background handles gradual lighting changes. Increase `--bg-alpha` for faster adaptation.

## Architecture

```
USB Camera (landscape 1280x720)
  --> SOURCE_PIPELINE --> INFERENCE_PIPELINE (yolov5m_seg, letterboxed to 640x640)
  --> TRACKER_PIPELINE (ByteTrack)
  --> USER_CALLBACK_PIPELINE (Python):
      submits person_mask to BackgroundService, runs VampireEngine per track,
      tags vampires with a HailoClassification("vampire") metadata
  --> hailovampire_overlay (C++ in-place transform):
      reads bg buffer from shared memory, paints vampire pixels onto the full
      1280x720 frame
  --> hailooverlay (bbox + segmentation contours — bypassed unless --show-overlay)
  --> videocrop (portrait center crop, e.g. 532x710 for 3:4)
  --> DISPLAY_PIPELINE (videoconvert -> fpsdisplaysink)
```

The background EMA runs in a separate Python subprocess (`bg_service.py`) and
publishes the live background through a double-buffered POSIX shared-memory
segment. The C++ overlay element reads it lock-free via an index byte that the
service flips between the two buffers.

`videocrop` is placed **after** `hailooverlay` so that any debug overlay
drawing happens at full source resolution before the portrait crop — otherwise
the normalized bbox metadata would be misaligned against the cropped frame's
new aspect ratio.

### Module Structure

| File | Purpose |
|------|---------|
| `vampire_mirror.py` | Entry point, per-frame callback, main() |
| `vampire_mirror_pipeline.py` | `GStreamerInstanceSegmentationApp` subclass — CLI args, vampire/crop pipeline splices |
| `frame_geometry.py` | Portrait crop coordinates and buffer-zone math |
| `background_manager.py` | In-process dynamic background EMA (used by `--no-bg-process`) |
| `bg_service.py` | Background-EMA subprocess + double-buffered shm publisher |
| `bg_shm.py` | POSIX shared-memory helpers |
| `vampire_engine.py` | Vampire / human decision engine |

The C++ `hailovampire_overlay` element lives under
`hailo_apps/postprocess/cpp/vampire_overlay/`.
