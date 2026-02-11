# License Plate Recognition (LPR) Application

A production-grade multi-stage GStreamer pipeline for automatic license plate recognition using Hailo AI accelerators.

## Overview

This application performs end-to-end license plate recognition through a cascaded inference pipeline:

1. **Vehicle Detection** - Detect vehicles in the video frame
2. **Vehicle Tracking** - Track vehicles across frames using JDE tracker
3. **License Plate Detection** - Detect license plates within cropped vehicle regions
4. **OCR Recognition** - Recognize text on cropped license plate images

## Key Architectural Difference

> ⚠️ **Important**: Unlike other pipeline applications in this repository, the LPR app relies heavily on **C++ postprocess functions** for core logic flow, not just inference post-processing. The C++ components handle:
> - Intelligent cropping with ROI filtering, blur detection, and aging logic
> - Track state management and deduplication
> - Result cataloging for overlay display
>
> The Python callback primarily handles additional logging and database persistence, while the C++ components perform the heavy lifting of the LPR pipeline logic.

---

## Architecture

### Pipeline Flow

```
┌─────────────┐    ┌──────────────────┐    ┌─────────────┐    ┌──────────────────┐
│   SOURCE    │───▶│ VEHICLE_DETECTION │───▶│   TRACKER   │───▶│ VEHICLE_CROPPER  │
│  (video)    │    │   (YOLOv8n)       │    │   (JDE)     │    │  (C++ cropper)   │
└─────────────┘    └──────────────────┘    └─────────────┘    └────────┬─────────┘
                                                                       │
                                                                       ▼
┌─────────────┐    ┌──────────────────┐    ┌─────────────┐    ┌──────────────────┐
│   DISPLAY   │◀───│  USER_CALLBACK   │◀───│  OCR_SINK   │◀───│    LP_CROPPER    │
│  (overlay)  │    │   (Python)       │    │ (C++ logic) │    │  (C++ cropper)   │
└─────────────┘    └──────────────────┘    └─────────────┘    └────────┬─────────┘
                                                                       │
                                           ┌──────────────────┐        │
                                           │  PLATE_DETECTION │◀───────┘
                                           │    (YOLOv8n)     │
                                           └────────┬─────────┘
                                                    │
                                           ┌──────────────────┐
                                           │ OCR_RECOGNITION  │
                                           │   (OCR model)    │
                                           └──────────────────┘
```

### GStreamer Pipeline String

The pipeline is constructed programmatically. Use `--print-pipeline` to see the full GStreamer pipeline string:

```bash
python3 -m hailo_apps.python.pipeline_apps.license_plate_recognition.license_plate_recognition --print-pipeline
```

---

## Neural Network Models (HEF Files)

| Model Name | Purpose | Input Resolution | Classes |
|------------|---------|------------------|---------|
| `hailo_yolov8n_4_classes_vga` | Vehicle Detection | 640x480 (VGA) | person, face, vehicle, license_plate |
| `hailo_yolov8n_4_classes_vga` | License Plate Detection | 640x480 (VGA) | person, face, vehicle, license_plate |
| `ocr` | Text Recognition | Variable | Character classes |

> **Note**: The same YOLOv8n model is used for both vehicle and plate detection. Class filtering (`remove_labels`) is applied to keep only relevant detections at each stage.

---

## C++ Postprocess Libraries

This application uses **6 custom C++ shared libraries** for postprocessing. Unlike typical apps where C++ just handles inference output parsing, here C++ implements core application logic:

### 1. `liblpr_croppers.so`
**Source**: `lpr_croppers.cpp`  
**Functions**: `vehicles_lpr_cropper`, `license_plate_cropper`

Implements intelligent cropping using the `GenericCropper` base class:

- **vehicles_lpr_cropper**: Crops vehicle regions for plate detection
  - ROI filtering (center 25%-75% of frame by default)
  - Minimum size: 200x150 pixels
  - Maximum 2 crops per frame
  - Adds static "region" detection for ROI visualization

- **license_plate_cropper**: Crops license plate regions for OCR
  - Minimum size: 40x15 pixels
  - Maximum 4 crops per frame
  - Recognition tracking to avoid re-processing

### 2. `libgeneric_cropper.so`
**Source**: `generic_cropper.cpp`  
**Class**: `GenericCropper`

Base cropper class providing:
- ROI validation (center-inside logic)
- Size and area filtering
- Blur detection using Laplacian variance
- Track aging (avoids re-cropping recently seen tracks)
- Recognition state tracking
- Debug logging infrastructure

### 3. `liblpr_ocrsink.so`
**Source**: `lpr_ocrsink.cpp`  
**Function**: `filter`

Core OCR result processing:
- Track deduplication (skips already-recognized tracks)
- Adds `lpr_result` classification to vehicle detections
- Updates JDE tracker with recognized plates
- Catalogs plates for overlay display
- Prints final summary on EOS/exit

### 4. `liblpr_overlay.so`
**Source**: `lpr_overlay.cpp`  
**Function**: `draw_lpr`

Overlay rendering:
- Draws recognized license plates on video
- Displays ROI rectangle (yellow box)
- Supports NV12, YUY2, and RGB formats

### 5. `liblp_crop_saver.so`
**Source**: `lp_crop_saver.cpp`  
**Function**: `filter`

Debug utility for saving crops:
- Saves license plate crops to disk
- Controlled by `HAILO_LPR_SAVE_CROPS` environment variable
- Useful for training data collection and debugging

### 6. `libocr_postprocess.so`
**Source**: `ocr_postprocess.cpp`  
**Function**: `lpr_post_process`

LPR-specific OCR with caching:
- Caches OCR results per track to avoid redundant processing
- Character correction and normalization

---

## Python Components

### Main Application (`license_plate_recognition.py`)

- Entry point: `main()`
- User callback: `app_callback()` - processes OCR results from buffer
- LPR database handler for persistence
- JSONL tailer for C++/Python state synchronization
- Summary printing on exit

### Pipeline Definition (`license_plate_recognition_pipeline.py`)

- `GStreamerLPRApp` class extending `GStreamerApp`
- Constructs the multi-stage pipeline
- Handles EOS (calls C++ summary function)
- Resource path resolution for models and shared libraries

---

## Running the Application

### Basic Usage

```bash
# Run with default video
python3 -m hailo_apps.python.pipeline_apps.license_plate_recognition.license_plate_recognition

# Run with custom video
python3 -m hailo_apps.python.pipeline_apps.license_plate_recognition.license_plate_recognition --input /path/to/video.mp4

# Show help
python3 -m hailo_apps.python.pipeline_apps.license_plate_recognition.license_plate_recognition --help
```

### Debug Mode

Enable verbose logging with environment variables:

```bash
# Full debug logging
HAILO_LPR_DEBUG=1 python3 -m hailo_apps.python.pipeline_apps.license_plate_recognition.license_plate_recognition

# OCR sink specific logging
HAILO_LPR_OCRSINK_LOG=1 python3 -m hailo_apps.python.pipeline_apps.license_plate_recognition.license_plate_recognition

# Save license plate crops to disk
HAILO_LPR_SAVE_CROPS=1 python3 -m hailo_apps.python.pipeline_apps.license_plate_recognition.license_plate_recognition
```

---

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `HAILO_LPR_DEBUG` | Enable verbose debug logging | `false` |
| `HAILO_LPR_NO_SKIP` | Don't skip already-recognized tracks | `false` |
| `HAILO_LPR_HIDE_LP` | Hide license plate overlays (show only vehicles) | `false` |
| `HAILO_LPR_SAVE_CROPS` | Save LP crops to disk | `false` |
| `HAILO_X_MIN`, `HAILO_Y_MIN`, `HAILO_X_MAX`, `HAILO_Y_MAX` | ROI rectangle (normalized 0-1) | `0.25, 0.25, 0.75, 0.75` |

---

## Output

### Console Output

The application prints:
- Real-time OCR results: `[LPR] Frame X OCR Result (VALID): 'XXXXXXX' (Confidence: 0.XX, Track Y)`
- Final summary table on exit with all detected plates

### Files

- `ocr_results.txt` - Timestamped log of all OCR detections
- `lpr_database/lpr.db` - LanceDB database (if persistence enabled)
- `lpr_database/lpr_tracks.jsonl` - JSON Lines file for C++/Python sync
- `lpr_crops/` - Saved LP crops (if `HAILO_LPR_SAVE_CROPS=1`)

---

## Building C++ Libraries

The C++ postprocess libraries must be compiled before running the application:

```bash
cd hailo_apps/postprocess
./compile_postprocess.sh
```

Or manually with meson:

```bash
cd hailo_apps/postprocess/cpp
meson setup builddir --wipe
meson compile -C builddir
sudo meson install -C builddir
```

### Required Libraries

The following shared libraries will be built:
- `liblpr_croppers.so`
- `libgeneric_cropper.so`
- `liblpr_ocrsink.so`
- `liblpr_overlay.so`
- `liblp_crop_saver.so`
- `libocr_postprocess.so`

---

## Troubleshooting

### No detections

1. Check if models are downloaded: `ls /usr/local/hailo/resources/hef/`
2. Verify video has vehicles with visible license plates
3. Enable debug mode: `HAILO_LPR_DEBUG=1`
4. Check ROI settings - plates must be in center region by default

### OCR not recognizing plates

1. Check plate is within size requirements (min 40x15 px)
2. Verify country setting matches plate format
3. Enable `HAILO_LPR_SAVE_CROPS=1` to inspect cropped images
4. Check for blur - plates may be rejected by blur filter

### Pipeline errors

1. Verify C++ libraries are compiled and installed
2. Check GStreamer plugins are available: `gst-inspect-1.0 hailofilter`
3. Review pipeline string: `--print-pipeline`

---

## Files Structure

```
license_plate_recognition/
├── __init__.py
├── README.md                              # This file
├── license_plate_recognition.py           # Main app with callbacks
├── license_plate_recognition_pipeline.py  # GStreamer pipeline definition
├── debug_metadata_callback.py             # Debug utilities
├── vehicle_labels_to_remove.txt           # Labels to filter (keep vehicle)
└── plate_labels_to_remove.txt             # Labels to filter (keep license_plate)

hailo_apps/postprocess/cpp/
├── lpr_croppers.cpp/.hpp                  # Vehicle and LP croppers
├── generic_cropper.cpp/.hpp               # Base cropper class
├── lpr_ocrsink.cpp/.hpp                   # OCR result processing
├── lpr_overlay.cpp/.hpp                   # Overlay drawing
├── lp_crop_saver.cpp/.hpp                 # Debug crop saver
├── lpr_roi.hpp                            # ROI configuration utilities
├── ocr_postprocess.cpp/.hpp               # OCR postprocess with LPR caching
└── meson.build                            # Build configuration
```

---

## References

- [Hailo Model Zoo](https://github.com/hailo-ai/hailo_model_zoo)
- [TAPPAS Documentation](https://hailo.ai/developer-zone/)
- [GStreamer Documentation](https://gstreamer.freedesktop.org/documentation/)

