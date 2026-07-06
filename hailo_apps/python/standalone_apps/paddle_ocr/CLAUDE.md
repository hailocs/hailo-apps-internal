# Paddle OCR

## What This App Does
Performs end-to-end text detection and recognition (OCR) using a two-model pipeline accelerated by Hailo AI devices. The first model (ocr_det) detects text regions in the image using a Differentiable Binarization (DB) approach, and the second model (ocr) recognizes the text within each detected region. The output displays the original image side-by-side with an annotated version where detected text regions are replaced with white boxes containing the recognized text. Optional spell correction is available via SymSpell.

## Architecture
- **Type:** Standalone app
- **Inference:** Two HailoAsyncInference instances running in parallel (detection + OCR recognition)
- **Models:** ocr_det + ocr (both required, from S3; same models for hailo8, hailo8l, hailo10h)
- **Hardware:** hailo8, hailo8l, hailo10h
- **Post-processing:** CPU-side DB postprocessing (contour extraction, polygon unclipping via pyclipper/shapely), perspective warp for text rectification, CTC decoding for text recognition, optional SymSpell correction
- **Extra dependencies:** paddlepaddle, shapely, pyclipper, symspellpy (install via `pip install -e ".[ocr]"`)

## Key Files
| File | Purpose |
|------|---------|
| `paddle_ocr.py` | Main script: multi-model pipeline with 6 threads (preprocess, det infer, det postprocess, OCR infer, OCR postprocess, visualize) |
| `paddle_ocr_utils.py` | Detection postprocessing, text region cropping/warping, OCR CTC decoding, visualization, `OcrCorrector` spell check |
| `db_postprocess.py` | Differentiable Binarization postprocessing (contour extraction, box scoring, polygon unclipping) |

## How It Works
1. Parse CLI args; resolve two HEF paths (detection + OCR) via `configure_multi_model_hef_path`
2. Initialize 6-thread pipeline: preprocess -> detection inference -> detection postprocess -> OCR inference -> OCR postprocess -> visualization
3. Detection model outputs a heatmap; DB postprocessing extracts text region polygons
4. Each text region is cropped, perspective-warped to a rectangle, resized with padding to OCR input size (48x320)
5. OCR model outputs character probabilities; CTC decoding produces text strings
6. Results grouped by frame ID (UUID-based tracking) to handle multiple text regions per frame
7. Visualization creates side-by-side display: original image + annotated version with recognized text

## Common Use Cases
- Reading text in images or video (signs, labels, documents)
- Real-time text extraction from camera streams
- Document digitization and OCR processing
- License plate or signage reading

## How to Extend
- Enable spell correction: add `--use-corrector` flag for SymSpell-based text correction
- Adjust detection sensitivity: modify `bin_thresh` and `box_thresh` in `paddle_ocr_utils.py`
- Custom character set: modify the `CHARACTERS` list in `paddle_ocr_utils.py`
- Change OCR model: swap the recognition HEF while keeping the detection model

## Related Apps
| App | When to use instead |
|-----|-------------------|
| `object_detection` | Need to detect objects rather than read text |
| `paddle_ocr` (pipeline app) | Need GStreamer pipeline with RTSP or overlay elements |
| `clip` (pipeline app) | Need text-based image search rather than text reading |
