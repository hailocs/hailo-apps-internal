# Photo Enhancer

## What This App Does
Batch 2x upscaling of photos using a Real-ESRGAN super-resolution model on Hailo. Processes a directory of JPG/PNG images and saves the upscaled results, optionally as side-by-side comparisons.

## Architecture
- **Type:** Standalone app
- **Pattern:** HailoInfer + Real-ESRGAN x2 + OpenCV; 3-thread pipeline (preprocess → async inference → postprocess)
- **Models:** real-esrgan-x2 (Real-ESRGAN 2x upscaling)
- **Hardware:** hailo8, hailo8l, hailo10h (see README)
- **Postprocess:** Python — clip to uint8, resize to original dimensions accounting for letterbox padding

## Key Files
| File | Purpose |
|------|---------|
| `photo_enhancer.py` | Main: preprocess → async inference → postprocess threads; batch processing, side-by-side comparison |
| `photo_enhancer_utils.py` | `inference_result_handler` + `resize_infer_result_to_original`: letterbox-padding removal and side-by-side composition |

## How to Run
```bash
source setup_env.sh
python -m community.apps.standalone_apps.photo_enhancer.photo_enhancer --input /path/to/images/ --save-output
```
> `APP_NAME` is intentionally `"super_resolution"` so the app reuses the super_resolution resource/model config.
Optional: `--enhanced-only`, `--output-dir results/`, `--show-fps`.

## How to Extend
- Add tiling to upscale very large images, or output quality metrics (PSNR/SSIM).
- Extend to video-frame upscaling with temporal consistency.
