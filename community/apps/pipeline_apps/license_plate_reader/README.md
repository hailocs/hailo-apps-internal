# License Plate Reader

> **Looking for production LPR?** The official, more capable **`hailo-lpr`** app
> lives at `hailo_apps/python/pipeline_apps/lpr/`. It uses a dedicated YOLOv8n
> license-plate detector (with optional 5-tile multi-scale inference for FHD/4K),
> a choice of OCR engines (retrained Latin LPRNet or multilingual PaddleOCR),
> quality gates (crop size, sharpness, length, confidence), per-track dedup
> (OCR runs once per plate, not per frame), and a live results panel. Run it with
> `hailo-lpr --input usb`.
>
> **This community app** is a simpler, self-contained demo built on the generic
> two-stage PaddleOCR text pipeline (text-region detection → recognition). It is
> meant as an easy-to-read starting point / template — use it when you want to
> learn or customize a minimal cascaded-OCR app, and prefer `hailo-lpr` for real
> license-plate workloads.

Real-time license plate detection and text recognition using a cascaded two-model pipeline on Hailo-8. The app detects text regions (including license plates) in the video frame, crops each detected region, and runs OCR character recognition to read the plate text. Recognized plates are displayed as overlays and optionally logged to a CSV file with timestamps.

## Prerequisites

- Hailo-8 accelerator (also works on Hailo-8L and Hailo-10H)
- OCR detection model (`ocr_det`) and OCR recognition model (`ocr`) — downloaded via `hailo-download-resources`
- OCR postprocess plugin (`libocr_postprocess.so`) — compiled via `hailo-compile-postprocess`

## How to Run

```bash
# Activate environment
source setup_env.sh

# Run with default OCR demo video
python -m community.apps.pipeline_apps.license_plate_reader.license_plate_reader

# Run with USB camera
python -m community.apps.pipeline_apps.license_plate_reader.license_plate_reader --input usb

# Run with RTSP stream (e.g., parking entrance camera)
python -m community.apps.pipeline_apps.license_plate_reader.license_plate_reader --input rtsp://192.168.1.100:554/stream

# Log recognized plates to CSV
python -m community.apps.pipeline_apps.license_plate_reader.license_plate_reader --input usb --plate-log plates.csv

# Raise the detection confidence threshold to suppress noisy text regions
python -m community.apps.pipeline_apps.license_plate_reader.license_plate_reader --input usb --confidence-threshold 0.3

# Use custom HEF models (detection first, recognition second)
python -m community.apps.pipeline_apps.license_plate_reader.license_plate_reader \
    --hef-path /path/to/plate_det.hef \
    --hef-path /path/to/plate_rec.hef
```

## Architecture

```
USB Camera / Video File / RTSP
    |
    v
SOURCE_PIPELINE (mirror_image=False)
    |
    v
INFERENCE_PIPELINE_WRAPPER (OCR detection - finds text regions)
    |
    v
TRACKER_PIPELINE (tracks plate regions across frames)
    |
    v
CROPPER_PIPELINE
    |--- inner: INFERENCE_PIPELINE (OCR recognition - reads characters)
    |--- bypass: original frame
    |
    v
USER_CALLBACK_PIPELINE (extracts plate text, logs results)
    |
    v
DISPLAY_PIPELINE (shows video with plate overlays)
```

## Customization

- **Frame rate:** Modify `self.frame_rate` cap in the pipeline class (default: 15 FPS)
- **Recognition batch size:** Adjust `self.recognition_batch_size` (default: 4)
- **Confidence threshold:** Pass `--confidence-threshold <float>` (default: 0.12)
- **CSV logging:** Use `--plate-log plates.csv` to write timestamped plate readings
- **Tracker tuning:** Adjust `keep_lost_frames` and `keep_tracked_frames` in the pipeline

## Based On

This app is built from the **paddle_ocr** pipeline app template, adapted for license plate reading with:
- Plate-specific logging with timestamps (CSV output)
- Adjusted tracker parameters for vehicle plate tracking
- Lower recognition batch size (plates are fewer per frame than general text)
- Higher frame rate cap (15 vs 10 FPS) since plate regions are larger
