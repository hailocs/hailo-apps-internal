# License Plate Reader

## What This App Does
Two-stage OCR pipeline that detects text regions (license plates), crops them, and recognizes the plate characters with a separate recognition model. Detections are tracked across frames and logged to CSV with timestamps.

## Architecture
- **Type:** Pipeline app (cascaded OCR)
- **Pattern:** OCR detection → tracker → cropper (inner: OCR recognition) → callback (CSV logging) → display
- **Models:** `ocr_det.hef` (text-region detection) + `ocr.hef` (character recognition)
- **Hardware:** hailo8, hailo8l, hailo10h
- **Postprocess:** C++ `libocr_postprocess.so` (detection + recognition postprocess)

## Key Files
| File | Purpose |
|------|---------|
| `license_plate_reader.py` | Entry point + callback: extracts plate text from classification objects, CSV logging |
| `license_plate_reader_pipeline.py` | `GStreamerApp` subclass: detection → tracker → cropper → recognition pipeline |

## How to Run
```bash
source setup_env.sh
python community/apps/pipeline_apps/license_plate_reader/license_plate_reader.py --input usb
```
Optional: `--plate-log plates.csv`.

## How to Extend
- Add string validation (per-country regex) and confidence filtering before logging.
- Integrate a lookup against an external database / watch list.
