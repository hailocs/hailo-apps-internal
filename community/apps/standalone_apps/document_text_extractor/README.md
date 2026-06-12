# Document Text Extractor

Batch OCR application for extracting text from scanned documents and photos of documents, using PaddleOCR detection + recognition models accelerated by Hailo-8.

## What It Does

Processes a directory of document images and:
1. Detects text regions using the PaddleOCR detection model (Differentiable Binarization)
2. Recognizes text within each region using the PaddleOCR recognition model (CTC decoding)
3. Outputs structured JSON with recognized text and bounding box coordinates
4. Optionally saves annotated images showing detected text overlaid on the original

## Prerequisites

- Hailo-8 accelerator
- OCR dependencies: `pip install -e ".[ocr]"`
- Download models: `hailo-download-resources`

## Usage

```bash
# Basic: process a directory of document images
python -m hailo_apps.python.standalone_apps.document_text_extractor.document_text_extractor \
    --input /path/to/document/images/

# Save JSON results with bounding box coordinates
python -m hailo_apps.python.standalone_apps.document_text_extractor.document_text_extractor \
    --input /path/to/document/images/ \
    --save-json --no-display

# Save annotated images + JSON, with spell correction
python -m hailo_apps.python.standalone_apps.document_text_extractor.document_text_extractor \
    --input /path/to/document/images/ \
    --save-output --save-json --use-corrector

# Run headless (no display window)
python -m hailo_apps.python.standalone_apps.document_text_extractor.document_text_extractor \
    --input /path/to/document/images/ \
    --save-json --no-display
```

## Architecture

```
preprocess --> det_infer --> det_postprocess --> ocr_infer --> ocr_postprocess --> visualize
   (read &      (text         (crop text        (recognize     (group results    (annotate &
    resize)      detection)    regions)          characters)    per image)        save/display)
```

Six threads connected by queues:
- **preprocess**: Reads images, resizes to detection model input size
- **det_infer**: Runs text detection on Hailo-8 (async inference)
- **det_postprocess**: Extracts text region polygons, crops and rectifies each region
- **ocr_infer**: Runs text recognition on each cropped region via Hailo-8
- **ocr_postprocess**: Groups recognition results by source image (UUID-based tracking)
- **visualize**: Creates annotated images, collects JSON results, saves output

## JSON Output Format

When using `--save-json`, results are saved to `<output_dir>/ocr_results.json`:

```json
{
  "document_ocr_results": [
    {
      "image_index": 0,
      "text_regions": [
        {
          "text": "Hello World",
          "confidence": 0.9523,
          "bbox": {
            "x": 120,
            "y": 45,
            "width": 340,
            "height": 38
          }
        }
      ]
    }
  ]
}
```

## CLI Arguments

| Argument | Description |
|----------|-------------|
| `--input`, `-i` | Input source: path to image directory |
| `--save-json` | Save OCR results as JSON file |
| `--save-output`, `-s` | Save annotated output images |
| `--output-dir`, `-o` | Output directory (default: auto-generated) |
| `--use-corrector` | Enable SymSpell text correction |
| `--confidence-threshold` | Min detection confidence (default: 0.3) |
| `--batch-size`, `-b` | Inference batch size (default: 1) |
| `--show-fps` | Display FPS statistics |
| `--no-display` | Run without display window |

## Customization

- **Detection sensitivity**: Adjust `--confidence-threshold` (lower = more text detected, higher = fewer false positives)
- **Spell correction**: Enable `--use-corrector` for documents with known English text
- **Batch processing speed**: Increase `--batch-size` for higher throughput on large image sets

## Based On

This app is adapted from the `paddle_ocr` standalone app, with these additions:
- JSON output with structured text and bounding box data
- Document-oriented batch processing focus
- Configurable confidence threshold via CLI
