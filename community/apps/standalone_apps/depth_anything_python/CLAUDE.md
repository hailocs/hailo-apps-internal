# Depth Anything (Python Standalone)

## What This App Does
Monocular depth estimation using the HailoRT Python API (no GStreamer) for Depth Anything V1 or V2. Auto-downloads the HEF, supports multiple display modes (depth-only, side-by-side, overlay), and accepts images, video files, or a live camera.

## Architecture
- **Type:** Standalone app
- **Pattern:** HailoInfer (Python API) + OpenCV; 3-thread pipeline (preprocess → async infer → visualize); auto-download from Hailo Model Zoo
- **Models:** depth_anything_vits (V1) or depth_anything_v2_vits (V2), auto-downloaded per hardware
- **Hardware:** hailo8, hailo8l, hailo10h (see README)
- **Postprocess:** Python/NumPy — min-max normalize to 0-255 + OpenCV colormap (inferno/spectral/magma/turbo)

## Key Files
| File | Purpose |
|------|---------|
| `depth_anything_standalone.py` | Main: preprocess → async infer → visualize threads; auto-download + display modes |

## How to Run
```bash
source setup_env.sh
python community/apps/standalone_apps/depth_anything_python/depth_anything_standalone.py --input usb
```
Optional: `--model-version v2`, `--display-mode side-by-side`, `--colormap turbo`, `--save-output`, `--no-display`.

## How to Extend
- Add temporal smoothing for video, or overlay depth statistics (min/max/mean).
- For lower-latency deployment, see the `depth_anything_cpp` sibling app.
