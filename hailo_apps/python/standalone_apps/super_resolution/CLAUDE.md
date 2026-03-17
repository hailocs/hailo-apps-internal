# Super Resolution

## What This App Does
Enhances image quality and detail using AI-based super resolution on Hailo AI accelerators. The app takes low-resolution input (images, video, or camera stream) and produces upscaled output with improved clarity. It supports Real-ESRGAN (x2 upscaling) and ESPCN models. The output is displayed as a side-by-side comparison of the original and super-resolved images.

## Architecture
- **Type:** Standalone app
- **Inference:** HailoAsyncInference (async queue-based via `HailoInfer`)
- **Models:** real_esrgan_x2 (default for all architectures)
- **Hardware:** hailo8, hailo8l, hailo10h
- **Post-processing:** CPU-side image reconstruction; SRGAN uses direct RGB output clipping, ESPCN uses YUV color space conversion (Y-channel super resolution + UV upsampling)

## Key Files
| File | Purpose |
|------|---------|
| `super_resolution.py` | Main script: CLI parsing, 3-thread pipeline, model-type auto-detection (ESPCN vs SRGAN) |
| `super_resolution_utils.py` | `SrganUtils` and `Espcnx4Utils` classes for model-specific pre/post-processing, side-by-side visualization |

## How It Works
1. Parse CLI args and resolve HEF model path
2. Auto-detect model type from HEF filename (`espcn` triggers ESPCN pipeline, otherwise SRGAN)
3. Initialize input source and create 3-thread pipeline
4. For SRGAN: direct resize preprocessing, output clipped to uint8
5. For ESPCN: RGB-to-YUV conversion, Y-channel extraction for inference, UV channels bicubic-upsampled and recombined
6. Post-processing resizes inference result back to original dimensions (removing letterbox padding) and creates side-by-side comparison image

## Common Use Cases
- Enhancing low-resolution security camera footage
- Upscaling images for better visual quality
- Real-time video enhancement from camera streams
- Comparing original vs enhanced quality

## How to Extend
- Swap model: use `--hef-path <model_name>` with a different super resolution HEF
- Change upscale factor: use a different model (current default is 2x)
- Modify output format: change `inference_result_handler` to output only the enhanced image instead of side-by-side
- Adjust color handling: modify YUV conversion matrices in `super_resolution_utils.py`

## Related Apps
| App | When to use instead |
|-----|-------------------|
| `object_detection` | Need to detect objects rather than enhance image quality |
| `depth` (pipeline app) | Need depth estimation rather than resolution enhancement |
