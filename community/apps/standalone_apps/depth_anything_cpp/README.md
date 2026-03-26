# Depth Anything (C++ Standalone)

Monocular depth estimation using the **Depth Anything** model family (V1 and V2) with the HailoRT C++ API. No GStreamer required.

## How It Works

The app uses a 3-thread architecture (preprocess, infer, postprocess) built on the `hailo-apps` C++ common utilities:

1. **Preprocess** -- Read frames from image/video/camera, resize to model input dimensions.
2. **Infer** -- Run async inference on the Hailo accelerator.
3. **Postprocess** -- Dequantize the output tensor, normalize to [0,255], apply a colormap, and display or save the result.

### Post-Processing (Dequantize + Normalize)

Depth Anything outputs a single-channel feature map of **relative depth values**. Unlike SCDepthV3 (which requires sigmoid + reciprocal scaling), Depth Anything post-processing is simple:

```
1. Get float32 depth map from HailoRT (already dequantized)
2. Find min and max values
3. Normalize: pixel = (value - min) / (max - min) * 255
4. Apply colormap (INFERNO)
```

This normalization is model-agnostic -- the same logic works for both V1 and V2 HEFs, and can be reused in a Python standalone version with NumPy:

```python
import numpy as np
import cv2

# depth_map: np.ndarray of shape (H, W), float32, from HailoRT
mn, mx = depth_map.min(), depth_map.max()
normalized = ((depth_map - mn) / (mx - mn + 1e-6) * 255).astype(np.uint8)
colored = cv2.applyColorMap(normalized, cv2.COLORMAP_INFERNO)
```

## Supported Models

| Model | Architecture | Notes |
|-------|-------------|-------|
| Depth Anything V1 | Hailo-8, Hailo-8L, Hailo-10H | Original model |
| Depth Anything V2 | Hailo-8, Hailo-8L, Hailo-10H | Improved accuracy |

Use the same binary for both -- just supply the appropriate HEF file.

## Requirements

- HailoRT (4.23.0+ for Hailo-8, 5.1.1+ for Hailo-10H)
- OpenCV 4.x
- CMake 3.10+
- C++17 compiler

## Build

```bash
cd community/apps/standalone_apps/depth_anything_cpp
./build.sh
```

This creates `build/<arch>/depth_anything`.

## Usage

```bash
# Video input
./build/x86_64/depth_anything -n /path/to/depth_anything_v2.hef -i input_video.mp4

# Single image
./build/x86_64/depth_anything -n /path/to/depth_anything_v1.hef -i photo.jpg

# Camera (live)
./build/x86_64/depth_anything -n /path/to/depth_anything_v2.hef -i /dev/video0

# Directory of images with batch processing
./build/x86_64/depth_anything -n /path/to/depth_anything_v2.hef -i images/ -b 4

# Save output instead of displaying
./build/x86_64/depth_anything -n /path/to/depth_anything_v2.hef -i input.mp4 -s -o results/
```

## Arguments

| Argument | Description |
|----------|-------------|
| `-n, --net` | Path to HEF file (Depth Anything V1 or V2) |
| `-i, --input` | Image file, video file, directory of images, or camera device |
| `-b, --batch-size` | Batch size for inference (default: 1) |
| `-s, --save_stream_output` | Save output to file |
| `-o, --output-dir` | Output directory for saved results |
| `--camera-resolution` | Camera resolution: `sd`, `hd`, or `fhd` |
| `--output-resolution` | Output display resolution |
| `-f, --framerate` | Override camera framerate |
| `--list-nets` | List supported networks and exit |
| `--list-inputs` | List available demo inputs and exit |

## Notes

- Press **q** to exit the OpenCV display window when using camera input.
- The colormap can be changed in the source code (line with `cv::COLORMAP_INFERNO`). Other good options: `COLORMAP_PLASMA`, `COLORMAP_MAGMA`, `COLORMAP_TURBO`.
- For camera input, ensure you have permissions (`sudo chmod 777 /dev/video0` if needed).
- If OpenCV defaults to GStreamer for video capture, force V4L2:
  ```bash
  export OPENCV_VIDEOIO_PRIORITY_GSTREAMER=0
  export OPENCV_VIDEOIO_PRIORITY_V4L2=100
  ```
