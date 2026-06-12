# License Plate Recognition (LPR)

## What This App Does
Real-time license-plate recognition: a 4-class YOLOv8n detector localizes plates, a `hailo_tracker` assigns each plate a stable track_id, and the selected OCR head reads the characters off each unique plate crop (OCR runs once per plate, not per frame). Quality gates (crop size, sharpness, length, confidence) filter results before they are logged and shown in a side panel.

## Architecture
- **Type:** Pipeline app (two-stage detect → track → OCR)
- **Pattern:** GStreamer detector + `hailo_tracker`, then per-crop OCR run in Python via HailoRT `HailoInfer` from the `app_callback`
- **Models:**
  - Detector: `hailo_yolov8n_384_640.hef` (4 classes: person / vehicle / face / license_plate). `--backbone yolov8n` (single inference) or `yolov8n_tiled` (5-tile: 2×2 quadrants + full frame, default for FHD/4K)
  - OCR: `lprnet_intl.hef` (retrained 37-class Latin LPRNet, default) or `paddle_ocr_v5.hef` (multilingual, 18,385-class CTC) via `--ocr {lprnet,paddle}`
- **Hardware:** hailo8, hailo8l, hailo10h
- **Postprocess:** YOLOv8 detection postprocess (GStreamer) + Python CTC decode (`ctc_decode_lprnet` / `ctc_decode_paddle`)

## Key Files
| File | Purpose |
|------|---------|
| `lpr.py` | Entry point — argparse (`--backbone`, `--ocr`, `--save-ocr-inputs`), OCR HEF resolution, `user_app_callback_class`, `app_callback` (crop + gate + OCR dispatch) |
| `lpr_pipeline.py` | `GStreamerLPRApp`, backbone constants/`BACKBONES`, the `LPR_PIPELINE` string |
| `lpr_postprocess.py` | CTC decoders, quality-gate thresholds, `letterbox_resize`, `laplacian_variance`, `min_ocr_confidence_for` |
| `lpr_display.py` | Side-panel display thread (`lpr_display_thread`, `PANEL_WIDTH`) showing recent plate crops + text |

## How to Run
```bash
source setup_env.sh
python hailo_apps/python/pipeline_apps/lpr/lpr.py --input usb
# or the installed console entry point:
hailo-lpr --input usb
# best accuracy on HD/4K:
hailo-lpr --backbone yolov8n_tiled --ocr lprnet --input <clip.mp4>
# multilingual OCR:
hailo-lpr --backbone yolov8n_tiled --ocr paddle --input <clip.mp4>
```
OCR HEFs are expected under `<resources>/models/<arch>/` (run `sudo ./install.sh` to fetch them).

## How to Extend
- **Regional accuracy:** Fine-tune LPRNet on a narrower regional plate corpus, recompile, and drop the new `lprnet_intl.hef` at `/usr/local/hailo/resources/models/<arch>/` — no pipeline changes needed (see README).
- **Tune gates:** Adjust the thresholds in `lpr_postprocess.py` (`MIN_LENGTH`, `SHARPNESS_MIN_VARIANCE`, `MIN/MAX_LP_*_PIXELS`, per-engine confidence) to trade recall for precision.
- **Debug OCR inputs:** Run with `--save-ocr-inputs [dir]` to dump every post-resize OCR-network input (filenames encode track id, confidence, decoded text).
