# Photo Enhancer

Batch 2x upscale of photos using Real-ESRGAN super resolution on Hailo-8.

Processes a directory of images (jpg/png), runs Real-ESRGAN x2 inference on the Hailo accelerator, and saves upscaled results to an output directory. By default, outputs are side-by-side comparisons; use `--enhanced-only` to save only the enhanced image.

## Prerequisites

- Hailo-8 accelerator (also supports Hailo-8L and Hailo-10H)
- Real-ESRGAN x2 model HEF (downloaded via `hailo-download-resources`)
- Python environment activated (`source setup_env.sh`)

## How to Run

```bash
# Process a directory of images (saves side-by-side comparison)
python community/apps/standalone_apps/photo_enhancer/photo_enhancer.py \
    --input /path/to/image/directory \
    --save-output

# Save only the enhanced images (no side-by-side)
python community/apps/standalone_apps/photo_enhancer/photo_enhancer.py \
    --input /path/to/image/directory \
    --save-output \
    --enhanced-only

# Specify output directory and show FPS
python community/apps/standalone_apps/photo_enhancer/photo_enhancer.py \
    --input /path/to/image/directory \
    --output-dir /path/to/output \
    --save-output \
    --show-fps

# Run without display (headless mode)
python community/apps/standalone_apps/photo_enhancer/photo_enhancer.py \
    --input /path/to/image/directory \
    --save-output \
    --no-display
```

## Architecture

```
Input Directory (jpg/png images)
        |
        v
  [Preprocess Thread]  -- resize to model input (256x256)
        |
        v
  [Inference Thread]   -- Real-ESRGAN x2 on Hailo-8 (HailoAsyncInference)
        |
        v
  [Postprocess Thread] -- clip output, resize to original, save to disk
        |
        v
Output Directory (upscaled images)
```

Three threads run in parallel via queues:
1. **Preprocess:** Reads images from the input directory, resizes to model input dimensions
2. **Inference:** Runs Real-ESRGAN x2 on the Hailo accelerator using async inference
3. **Postprocess:** Converts model output to displayable images, saves to output directory

## Customization

- **Enhanced-only output:** Use `--enhanced-only` to skip the side-by-side comparison and save only the upscaled image.
- **Batch size:** Adjust `--batch-size` for throughput tuning (default: 1).
- **Output directory:** Use `--output-dir` to specify where upscaled images are saved (default: `output_images/`).
- **Different model:** Use `--hef-path <model_name>` to use a different super resolution HEF.

## Based On

This app is based on the [super_resolution](../super_resolution/) standalone app template.
