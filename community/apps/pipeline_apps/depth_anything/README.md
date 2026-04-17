# Depth Anything

Real-time monocular depth estimation using Depth Anything V1/V2 on Hailo accelerators. Produces colorized depth maps from a camera or video file with multiple visualization modes.

## Features

- **Both V1 and V2** models supported via `--model-version`
- **Auto-download**: HEF files are downloaded automatically from Hailo Model Zoo
- **Display modes**: depth-only (colorized), side-by-side (original + depth), overlay (blended), metric (scale bar + distance readout)
- **Colormaps**: inferno, spectral, magma, turbo (inverted so close=warm, far=cool)
- **Temporal smoothing**: EMA + bilateral filter reduces frame-to-frame jitter (`--temporal-alpha`)
- **Far-end outlier clipping**: 95th-percentile clipping removes depth spikes (`--max-clip`)
- **Mouse depth readout**: Hover to see depth value at any pixel
- **All Hailo hardware**: Hailo-8, Hailo-8L, Hailo-10H

## Metric Depth (Real Distance)

The app can estimate real-world depth in meters using post-processing calibration:

### Quick Start

```bash
# Metric depth with indoor scene (0-20m range)
python community/apps/pipeline_apps/depth_anything/depth_anything.py \
    --input usb --use-frame --depth-mode metric --display-mode metric --scene-type indoor

# Outdoor scene (0-80m range)
python community/apps/pipeline_apps/depth_anything/depth_anything.py \
    --input usb --use-frame --depth-mode metric --display-mode metric --scene-type outdoor

# Custom max depth
python community/apps/pipeline_apps/depth_anything/depth_anything.py \
    --input usb --use-frame --depth-mode metric --display-mode metric --max-depth 50

# Calibrate with known reference (relative_depth:real_meters)
python community/apps/pipeline_apps/depth_anything/depth_anything.py \
    --input usb --use-frame --depth-mode metric --display-mode metric --calibrate-ref "15.3:2.5"

# Export depth data as numpy arrays
python community/apps/pipeline_apps/depth_anything/depth_anything.py \
    --input usb --use-frame --depth-mode metric --export-depth ./depth_output
```

### How It Works

1. **Scene-type prior**: Depth Anything V2's relative output is linearly mapped to a real-world range based on scene type (indoor: 0.1-20m, outdoor: 0.5-80m)
2. **CLI calibration** (optional): Run once uncalibrated, note the raw relative depth at a known distance, then re-run with `--calibrate-ref "RAW:METERS"`
3. **Metric display**: Scale bar with meter labels, center crosshair distance readout, and min/max/mean stats

### Accuracy Notes

- Without calibration, metric values are **approximate** — the relative-to-metric mapping assumes linear relationship
- With calibration on a reference point, accuracy improves significantly for the depth range around that reference
- For best results, calibrate with an object at mid-range distance
- The Depth Anything V2 official metric models (fine-tuned on Hypersim/VKITTI) would give better metric accuracy but require separate HEF compilation

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
    |-- INFERENCE_PIPELINE (Depth Anything on Hailo + C++ post-process → HailoDepthMask)
    |-- Bypass (original resolution)
        |
  USER_CALLBACK_PIPELINE  <-- Invert + clip + smooth + colormap + display
        |
  DISPLAY_PIPELINE
```

The app uses a **C++ post-process** (`libdepth_anything_postprocess.so`) to extract the raw depth tensor as a `HailoDepthMask`, followed by Python post-processing in the callback:

1. **Inversion**: Raw output is inverse-depth (close=high); inverted so close=small, far=large
2. **Far-end outlier clipping** (`--max-clip`): Caps at the 95th percentile to remove noise spikes
3. **Temporal smoothing** (`--temporal-alpha`): Bilateral spatial filter + EMA across frames
4. **Metric conversion** (optional): Linear mapping to real-world meters
5. **Normalization + colormap**: Min-max normalize to 0-255 with smoothed bounds, apply OpenCV colormap
6. **Custom display**: Separate process with mouse-hover depth readout

## CLI Arguments


| Argument          | Default       | Description                                                        |
| ----------------- | ------------- | ------------------------------------------------------------------ |
| `--model-version` | `v2`          | Model version: `v1` or `v2`                                        |
| `--display-mode`  | `depth`       | Visualization: `depth`, `side-by-side`, `overlay`, or `metric`     |
| `--colormap`      | `inferno`     | Depth colormap: `inferno`, `spectral`, `magma`, `turbo`            |
| `--alpha`         | `0.5`         | Blend alpha for overlay mode (0.0-1.0)                             |
| `--input`         | default video | Input source: `usb`, RTSP URL, or file path                        |
| `--use-frame`     | always on     | OpenCV display window (enabled automatically by the callback)      |
| `--show-fps`      | false         | Display FPS counter                                                |
| `--hef-path`      | auto          | Override HEF path (skips auto-download)                            |
| `--depth-mode`    | `relative`    | Depth output: `relative` (unitless) or `metric` (meters)           |
| `--scene-type`    | `indoor`      | Scene type for metric mode: `indoor` (20m) or `outdoor` (80m)      |
| `--max-depth`     | auto          | Override max depth in meters                                       |
| `--calibrate-ref` | off           | Calibrate with reference: `"RELATIVE:METERS"` (e.g., `"15.3:2.5"`) |
| `--export-depth`  | off           | Export depth frames as .npy to specified directory                 |
| `--temporal-alpha` | `0.4`        | Temporal smoothing factor (0.0=off, 0.9=very smooth)               |
| `--max-clip`      | `10.0`        | Clip far-end outliers beyond 95th percentile (0=disable)           |


## Model Comparison


|                 | Depth Anything V1     | Depth Anything V2        |
| --------------- | --------------------- | ------------------------ |
| Model           | `depth_anything_vits` | `depth_anything_v2_vits` |
| Input           | 224x224x3             | 224x224x3                |
| Output          | 224x224x1             | 224x224x1                |
| FPS (Hailo-8)   | 31.9                  | 43.5                     |
| FPS (Hailo-8L)  | 37.4                  | 32.4                     |
| FPS (Hailo-10H) | 53.2                  | 51.4                     |
| Float AbsRel    | 0.13                  | 0.15                     |
| License         | Apache-2.0            | Apache-2.0               |


V2 is faster on Hailo-8 and is the default. V1 has slightly better accuracy.

## How It Works

1. The Hailo accelerator runs Depth Anything inference at 224x224 resolution
2. C++ post-process extracts the depth tensor as a `HailoDepthMask`
3. Python callback inverts the raw inverse-depth values so close=small, far=large
4. Far-end outlier clipping caps at the 95th percentile, removing depth spikes that flatten colormap contrast
5. Temporal smoothing applies a bilateral spatial filter and exponential moving average (EMA) across frames, reducing jitter
6. Min-max normalization (with EMA-smoothed bounds) maps depth to 0-255
7. OpenCV colormap converts grayscale depth to a color visualization (inverted: warm=close, cool=far)
8. A custom display process renders the frame with mouse-hover depth readout at the cursor position

## Customization

- **Add depth statistics overlay**: Extend the callback to draw min/max/mean text on the frame
- **Combine with detection**: Run a second model (e.g., YOLO) to get per-object depth estimates
- **Record output**: Use OpenCV VideoWriter to save the colorized depth video
- **Proximity alerts**: See `depth_proximity_alert` for threshold-based alerting on depth values

