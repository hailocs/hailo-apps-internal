# License Plate Recognition (LPR)

Real-time license plate detection and OCR using a Hailo AI accelerator.

## Pipeline Overview

The application runs a two-stage GStreamer pipeline:

1. **Plate Detection** — A YOLOv8n model (`hailo_yolov8n_4_classes_vga`) detects license plates on the full frame.
2. **Tracker** — A `hailotracker` element tracks detected plates across frames so each physical plate gets a stable track ID.
3. **OCR** — Detected plates are cropped (`lpr_croppers`) and fed into an OCR model (`ocr`) that reads the plate text.
4. **OCR Sink** — A C++ filter (`lpr_ocrsink`) normalises the OCR output, deduplicates per track, and attaches the result as a classification on the vehicle detection.
5. **Python Callback** — Validates the plate text (length, false-positive filtering), prints the result, and updates the on-screen overlay.
6. **Display** — `hailooverlay` renders bounding boxes with the recognised plate text and OCR confidence.

```
Source → Plate Detection (YOLOv8n) → Tracker → LP Cropper → OCR → OCR Sink → Callback → Overlay → Display
```

## Running

```bash
source setup_env.sh
hailo-lpr --input <video_file>
```

If `--input` is omitted the default video from `resources/` is used.

### Example

```bash
hailo-lpr --input /path/to/dashcam.mp4
```

Console output for each recognised plate:

```
LP  3 | Det Conf.: 87% | OCR Conf.: 95% | Plate: '1234567'
```

## Overlay

The overlay shows only **recognised** plates. Each bounding box is labelled:

```
LP <track_id>: <PLATE_TEXT>   <OCR_CONF>%
```

Unrecognised or invalid plates are hidden from the overlay entirely.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `HAILO_LPR_DEBUG` | off | Enable verbose Python-side debug prints. |
| `HAILO_LPR_OCRSINK_LOG` | off | Enable verbose C++ OCR sink debug prints. |
| `HAILO_LPR_NO_SKIP` | off | Re-process plates every frame even after a final result is found. |
| `HAILO_LPR_MIN_LEN` | `4` | Minimum number of characters for a plate to be accepted. |
| `HAILO_LPR_MAX_LEN` | `10` | Maximum number of characters for a plate to be accepted. |
| `HAILO_LPR_COUNTRY` | `default` | Country-specific normalisation rule (currently only `default` — digits only, 7–8 chars in the C++ sink). |
| `HAILO_LPR_DEBUG_ALL_FRAMES` | off | Log every frame in the C++ sink (instead of every Nth). |
| `HAILO_LPR_DEBUG_EVERY_N` | `30` | Log every N-th frame in the C++ sink when debug is on. |

## Architecture

All state is **in-memory** — there is no database. The Python callback keeps:

- `found_lp_tracks` — set of track IDs that already have a final plate reading (used to skip re-processing).
- `plate_texts` — `dict[track_id, (plate_text, ocr_confidence)]` for overlay rendering.

Once a track receives a valid OCR result it is locked in and displayed on every subsequent frame until the track disappears.

## Key Files

| File | Role |
|---|---|
| `license_plate_recognition.py` | Entry point, Python callback (validation, overlay, printing). |
| `license_plate_recognition_pipeline.py` | GStreamer pipeline construction (`GStreamerLPRApp`). |
| `cpp/lpr_croppers.cpp` | C++ cropper — selects license plate ROIs for the OCR stage via `GenericCropper`. |
| `cpp/lpr_ocrsink.cpp` | C++ filter — normalises OCR text, deduplicates per track, updates the tracker and CVMat singleton. |
| `cpp/ocr_postprocess.cpp` | Shared OCR post-process (used by both LPR and standalone OCR apps). |
| `core/common/defines.py` | Shared constants (`LPR_*` names for models, .so files, pipeline ID). |
