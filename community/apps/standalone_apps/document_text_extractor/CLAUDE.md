# Document Text Extractor

## What This App Does
Batch OCR application using PaddleOCR detection + recognition models on Hailo to extract text from scanned documents and document photos. Outputs structured JSON with recognized text and bounding boxes, optionally saving annotated images.

## Architecture
- **Type:** Standalone app
- **Pattern:** HailoInfer + PaddleOCR (text detection → region rectification → character recognition); 6-thread pipeline grouped by source image via UUID
- **Models:** PaddleOCR detection (Differentiable Binarization) + PaddleOCR recognition (CTC)
- **Hardware:** hailo8 (README)
- **Postprocess:** Python — detection postprocess → region extraction → recognition postprocess → UUID-based grouping

## Key Files
| File | Purpose |
|------|---------|
| `document_text_extractor.py` | Main: 6-thread pipeline (preprocess → det infer/postprocess → ocr infer/postprocess → visualize), JSON output, optional spell correction |

## How to Run
```bash
source setup_env.sh
python -m hailo_apps.python.standalone_apps.document_text_extractor.document_text_extractor \
  --input /path/to/images/
```
Optional: `--save-output`, `--save-json`, `--use-corrector`, `--no-display`.

## How to Extend
- Add language-specific OCR models or document preprocessing (deskew, contrast) before detection.
- Add layout analysis for hierarchical/multi-page extraction.
