# License Plate Reader

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
python community/apps/pipeline_apps/license_plate_reader/license_plate_reader.py

# Run with USB camera
python community/apps/pipeline_apps/license_plate_reader/license_plate_reader.py --input usb

# Run with RTSP stream (e.g., parking entrance camera)
python community/apps/pipeline_apps/license_plate_reader/license_plate_reader.py --input rtsp://192.168.1.100:554/stream

# Log recognized plates to CSV
python community/apps/pipeline_apps/license_plate_reader/license_plate_reader.py --input usb --plate-log plates.csv

# Use custom HEF models (detection first, recognition second)
python community/apps/pipeline_apps/license_plate_reader/license_plate_reader.py \
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
- **Confidence threshold:** Change `confidence > 0.12` in the callback
- **CSV logging:** Use `--plate-log plates.csv` to write timestamped plate readings
- **Tracker tuning:** Adjust `keep_lost_frames` and `keep_tracked_frames` in the pipeline

## Based On

This app is built from the **paddle_ocr** pipeline app template, adapted for license plate reading with:
- Plate-specific logging with timestamps (CSV output)
- Adjusted tracker parameters for vehicle plate tracking
- Lower recognition batch size (plates are fewer per frame than general text)
- Higher frame rate cap (15 vs 10 FPS) since plate regions are larger
