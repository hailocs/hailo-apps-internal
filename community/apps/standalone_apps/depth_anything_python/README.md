# Depth Anything Python Standalone

Monocular depth estimation using the HailoRT Python API -- no GStreamer required. Runs Depth Anything V1 or V2 on a Hailo accelerator, producing colorized depth maps from images, video files, or a live camera.

## Features

- **HailoRT Python API only** -- no GStreamer, no TAPPAS dependencies
- **Both V1 and V2** models via `--model-version`
- **Auto-download**: HEF files are downloaded automatically from Hailo Model Zoo
- **Display modes**: depth-only (colorized), side-by-side (original + depth), overlay (blended)
- **Colormaps**: inferno, spectral, magma, turbo
- **All Hailo hardware**: Hailo-8, Hailo-8L, Hailo-10H
- **Flexible input**: image file, video file, USB camera, image folder

## Prerequisites

- Hailo-8, Hailo-8L, or Hailo-10H accelerator
- Python 3.8+
- `hailo_platform` Python package (HailoRT)
- OpenCV (`pip install opencv-python`)
- NumPy

## How to Run

```bash
# Activate environment
source setup_env.sh

# Run with USB camera (V2 model, inferno colormap)
python community/apps/standalone_apps/depth_anything_python/depth_anything_standalone.py \
    --input usb

# Run Depth Anything V1
python community/apps/standalone_apps/depth_anything_python/depth_anything_standalone.py \
    --input usb --model-version v1

# Run with a video file
python community/apps/standalone_apps/depth_anything_python/depth_anything_standalone.py \
    --input path/to/video.mp4

# Run with an image file
python community/apps/standalone_apps/depth_anything_python/depth_anything_standalone.py \
    --input path/to/image.jpg

# Side-by-side: original + depth map
python community/apps/standalone_apps/depth_anything_python/depth_anything_standalone.py \
    --input usb --display-mode side-by-side

# Overlay: depth blended on original
python community/apps/standalone_apps/depth_anything_python/depth_anything_standalone.py \
    --input usb --display-mode overlay --alpha 0.6

# Different colormap
python community/apps/standalone_apps/depth_anything_python/depth_anything_standalone.py \
    --input usb --colormap turbo

# Save output (no display window)
python community/apps/standalone_apps/depth_anything_python/depth_anything_standalone.py \
    --input video.mp4 --save-output --output-dir results/ --no-display

# Show FPS counter
python community/apps/standalone_apps/depth_anything_python/depth_anything_standalone.py \
    --input usb --show-fps

# Use a custom HEF file
python community/apps/standalone_apps/depth_anything_python/depth_anything_standalone.py \
    --input usb --hef-path /path/to/custom.hef
```

## Architecture

```
Input (image / video / camera)
        |
  preprocess_thread    -- Read frames, resize to 224x224
        |
    input_queue
        |
    infer_thread       -- Async inference on Hailo device
        |
   output_queue
        |
  visualize_thread     -- Normalize depth, apply colormap, display/save
```

The app uses the standard 3-thread standalone architecture from `hailo-apps`. Post-processing is identity: the raw depth map is normalized min-max to 0-255 and colorized with OpenCV.

## CLI Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--input` | required | Input source: `usb`, video file, image file, or image folder |
| `--model-version` | `v2` | Model version: `v1` or `v2` |
| `--display-mode` | `depth` | Visualization: `depth`, `side-by-side`, or `overlay` |
| `--colormap` | `inferno` | Depth colormap: `inferno`, `spectral`, `magma`, `turbo` |
| `--alpha` | `0.5` | Blend alpha for overlay mode (0.0-1.0) |
| `--hef-path` | auto | Override HEF path (skips auto-download) |
| `--batch-size` | `1` | Inference batch size |
| `--save-output` | false | Save output frames to disk |
| `--output-dir` | auto | Directory for saved output |
| `--show-fps` | false | Display FPS counter |
| `--no-display` | false | Run headless (no OpenCV window) |
| `--camera-resolution` | `sd` | Camera resolution: `sd`, `hd`, `fhd` |
| `--arch` | auto | Override Hailo architecture detection |

## Model Comparison

| | Depth Anything V1 | Depth Anything V2 |
|---|---|---|
| Model | `depth_anything_vits` | `depth_anything_v2_vits` |
| Input | 224x224x3 | 224x224x3 |
| Output | 224x224x1 | 224x224x1 |
| FPS (Hailo-8) | 31.9 | 43.5 |
| FPS (Hailo-8L) | 37.4 | 32.4 |
| FPS (Hailo-10H) | 53.2 | 51.4 |
| License | Apache-2.0 | Apache-2.0 |

V2 is faster on Hailo-8 and is the default. V1 has slightly better accuracy.

## How It Works

1. Frames are read from the input source and resized to the model input size (224x224)
2. The Hailo accelerator runs Depth Anything inference asynchronously
3. The raw output tensor is a relative depth map (auto-dequantized by HailoRT)
4. Per-frame min-max normalization maps depth values to 0-255
5. OpenCV colormap converts grayscale depth to a color visualization
6. The result is displayed via OpenCV window or saved to disk

## Comparison with Pipeline App

| Feature | This standalone app | Pipeline app (`depth_anything/`) |
|---|---|---|
| Dependencies | HailoRT + OpenCV only | Full TAPPAS + GStreamer |
| Post-processing | Python (identical logic) | Python (identical logic) |
| Input sources | OpenCV (files, camera) | GStreamer (more formats, RTSP) |
| Best for | Prototyping, batch processing, minimal setup | Real-time pipelines, hardware decoding |
