# Depth Anything

Real-time monocular depth estimation using Depth Anything V1/V2 on Hailo accelerators. Produces colorized depth maps from a camera or video file with multiple visualization modes.

## Features

- **Both V1 and V2** models supported via `--model-version`
- **Auto-download**: HEF files are downloaded automatically from Hailo Model Zoo
- **Display modes**: depth-only (colorized), side-by-side (original + depth), overlay (blended)
- **Colormaps**: inferno, spectral, magma, turbo
- **All Hailo hardware**: Hailo-8, Hailo-8L, Hailo-10H

## Prerequisites

- Hailo-8, Hailo-8L, or Hailo-10H accelerator
- USB camera or video file
- No manual model download needed (auto-download on first run)

## How to Run

```bash
# Activate environment
source setup_env.sh

# Run with USB camera (V2 model, inferno colormap)
python community/apps/pipeline_apps/depth_anything/depth_anything.py \
    --input usb --use-frame

# Run Depth Anything V1
python community/apps/pipeline_apps/depth_anything/depth_anything.py \
    --input usb --use-frame --model-version v1

# Side-by-side: original video + depth map
python community/apps/pipeline_apps/depth_anything/depth_anything.py \
    --input usb --use-frame --display-mode side-by-side

# Overlay: depth blended on top of original video
python community/apps/pipeline_apps/depth_anything/depth_anything.py \
    --input usb --use-frame --display-mode overlay --alpha 0.6

# Different colormap
python community/apps/pipeline_apps/depth_anything/depth_anything.py \
    --input usb --use-frame --colormap turbo

# Run with video file
python community/apps/pipeline_apps/depth_anything/depth_anything.py \
    --input path/to/video.mp4 --use-frame

# Use a custom HEF file
python community/apps/pipeline_apps/depth_anything/depth_anything.py \
    --input usb --use-frame --hef-path /path/to/custom.hef
```

## Architecture

```
USB Camera / Video File
        |
  SOURCE_PIPELINE
        |
  INFERENCE_PIPELINE_WRAPPER
    |-- INFERENCE_PIPELINE (Depth Anything on Hailo, no C++ post-process)
    |-- Bypass (original resolution)
        |
  USER_CALLBACK_PIPELINE  <-- Depth extraction + colormap + display
        |
  DISPLAY_PIPELINE
```

The app uses **Python-only post-processing**: Depth Anything's output is a raw relative depth map (no math transform needed). The callback extracts the raw tensor, normalizes to 0-255, applies a colormap, and renders via OpenCV.

## CLI Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--model-version` | `v2` | Model version: `v1` or `v2` |
| `--display-mode` | `depth` | Visualization: `depth`, `side-by-side`, or `overlay` |
| `--colormap` | `inferno` | Depth colormap: `inferno`, `spectral`, `magma`, `turbo` |
| `--alpha` | `0.5` | Blend alpha for overlay mode (0.0-1.0) |
| `--input` | default video | Input source: `usb`, RTSP URL, or file path |
| `--use-frame` | always on | OpenCV display window (enabled automatically by the callback) |
| `--show-fps` | false | Display FPS counter |
| `--hef-path` | auto | Override HEF path (skips auto-download) |

## Model Comparison

| | Depth Anything V1 | Depth Anything V2 |
|---|---|---|
| Model | `depth_anything_vits` | `depth_anything_v2_vits` |
| Input | 224x224x3 | 224x224x3 |
| Output | 224x224x1 | 224x224x1 |
| FPS (Hailo-8) | 31.9 | 43.5 |
| FPS (Hailo-8L) | 37.4 | 32.4 |
| FPS (Hailo-10H) | 53.2 | 51.4 |
| Float AbsRel | 0.13 | 0.15 |
| License | Apache-2.0 | Apache-2.0 |

V2 is faster on Hailo-8 and is the default. V1 has slightly better accuracy.

## How It Works

1. The Hailo accelerator runs Depth Anything inference at 224x224 resolution
2. Raw output tensor (relative depth map) is extracted in the Python callback
3. Per-frame min-max normalization maps depth values to 0-255
4. OpenCV colormap converts grayscale depth to a color visualization
5. The result is displayed via OpenCV window (`--use-frame`)

## Customization

- **Add depth statistics overlay**: Extend the callback to draw min/max/mean text on the frame
- **Combine with detection**: Run a second model (e.g., YOLO) to get per-object depth estimates
- **Record output**: Use OpenCV VideoWriter to save the colorized depth video
- **Proximity alerts**: See `depth_proximity_alert` for threshold-based alerting on depth values
