# Depth Anything

## What This App Does
Real-time monocular depth estimation using Depth Anything V1/V2. Produces colorized depth maps with several visualization modes (depth-only, side-by-side, overlay, metric with scale bar) and optional metric-depth conversion with calibration.

## Architecture
- **Type:** Pipeline app
- **Pattern:** Depth estimation (source → inference → callback colorize/smooth/metric → display)
- **Models:** depth_anything_vits (V1), depth_anything_v2_vits (V2, default) — auto-downloaded from Hailo Model Zoo
- **Hardware:** hailo8, hailo8l, hailo10h
- **Postprocess:** C++ `depth_anything_postprocess.so` extracts the depth mask + Python callback (inversion, clipping, temporal smoothing, colormap, metric conversion)

## Key Files
| File | Purpose |
|------|---------|
| `depth_anything.py` | Entry point + callback: colorization, temporal smoothing, metric conversion, export |
| `depth_anything_pipeline.py` | `GStreamerApp` subclass: SOURCE → INFERENCE → CALLBACK → DISPLAY |
| `metric_depth.py` | `MetricDepthConverter`: scene-type mapping and calibration logic |
| `postprocess/` | C++ postprocess source (builds `libdepth_anything_postprocess.so`) |

## How to Run
```bash
source setup_env.sh
python community/apps/pipeline_apps/depth_anything/depth_anything.py --input usb --use-frame
```
Optional: `--model-version v1|v2`, `--display-mode depth|side-by-side|overlay|metric`, `--colormap inferno|spectral|magma|turbo`, `--depth-mode relative|metric`, `--scene-type indoor|outdoor`, `--calibrate-ref "RELATIVE:METERS"`, `--export-depth ./dir`, `--temporal-alpha 0.4`.

## How to Extend
- Run detection in parallel for per-object depth, or record depth video with `cv2.VideoWriter`.
- For proximity alerting, see the sibling `depth_proximity_alert` app pattern.
