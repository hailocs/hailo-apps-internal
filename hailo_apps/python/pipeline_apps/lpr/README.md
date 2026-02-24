# License Plate Recognition (LPR)

> ⚠️ **Beta:** This application is currently in beta. Features and APIs may change.

Real-time license plate recognition on Hailo accelerators using a three-stage GStreamer pipeline with tracker-based deduplication, a center-frame ROI gate, and a live display panel.

## Pipeline Architecture

```
Source → Vehicle Detection (YOLOv5m) → Tracker → Crop Vehicles → LP Detection (Tiny-YOLOv4) → User Callback (OCR) → Overlay → Display
```

| Stage | Model | Runs On |
|---|---|---|
| Vehicle detection | `yolov5m_vehicles` (640×640) | Hailo (GStreamer `hailonet`) |
| LP detection | `tiny_yolov4_license_plates` (416×416) | Hailo (GStreamer `hailonet` inside cropper) |
| OCR | LPRNet (300×75) or PaddleOCR (320×48) | Hailo (HailoRT Python API in callback) |

OCR runs outside the GStreamer pipeline — the user callback crops the license plate from the frame, resizes it, and runs synchronous inference via `HailoInfer`.

## Usage

```bash
source setup_env.sh

# Default (LPRNet, digits only)
hailo-lpr --input /path/to/video.mp4

# PaddleOCR (full alphanumeric charset)
hailo-lpr --input /path/to/video.mp4 --ocr-engine paddle

# Higher resolution for better LP crops on highway footage
hailo-lpr --input /path/to/video.mp4 --width 1920 --height 1080
```

### CLI Arguments

All standard pipeline arguments (`--input`, `--width`, `--height`, `--show-fps`, `--sync`, etc.) are supported. Additional LPR-specific argument:

| Argument | Default | Description |
|---|---|---|
| `--ocr-engine` | `lprnet` | OCR backend: `lprnet` (digits 0-9, fast) or `paddle` (full ASCII charset) |

## OCR Engines

### LPRNet (default)
- **Input**: 300×75 RGB, UINT8
- **Output**: (1, 19, 11) FLOAT32 — 19 time steps, 11 classes (digits 0-9 + CTC blank)
- **Best for**: Plates with digits only (e.g., Israeli plates)
- **Model source**: `resources_config.yaml` → 3rd model in the `lpr` app entry

### PaddleOCR
- **Input**: 320×48 RGB, UINT8
- **Output**: (1, 40, 97) FLOAT32 — 40 time steps, 97 ASCII classes
- **Best for**: Plates with letters and digits (worldwide)
- **Model path**: `$RESOURCES_ROOT/models/<arch>/ocr.hef`

Both engines use CTC greedy decoding (collapse repeated characters, remove blanks).

## Center 1/3 ROI Gate

Only vehicles whose **vertical center** falls within the **middle third** of the frame (Y 33%–66%) are processed for LP detection and OCR. This focuses recognition on the zone where plates are large enough for reliable reads and filters out distant or very close vehicles.

The gate is defined by two constants in `lpr.py`:

```python
ROI_Y_START = 1.0 / 3.0   # top of ROI zone (normalized)
ROI_Y_END   = 2.0 / 3.0   # bottom of ROI zone (normalized)
```

Vehicles outside this band are still detected and tracked (bounding boxes visible), but OCR is not attempted.

## 78% Confidence Threshold

Only plates with **OCR confidence ≥ 78%** are accepted. Below this threshold, the result is discarded and the vehicle will be retried on subsequent frames until either:
- A read exceeds 78%, or
- The vehicle leaves the frame

This is the key quality gate. A minimum text length of **4 characters** is also enforced.

The threshold is set at the top of `lpr.py`:
```python
MIN_OCR_CONFIDENCE = 0.78
```

## Tracker Deduplication

The pipeline uses `hailotracker` to assign persistent IDs to vehicles. Once a plate is recognized with ≥ 78% confidence for a given track ID, that vehicle is never re-processed — OCR inference is skipped entirely on future frames.

Each unique vehicle is recognized **at most once**, keeping compute usage proportional to unique vehicles rather than total frames.

## Display Panel

A separate OpenCV window ("LPR Panel") shows all recognized plates in real time:

- Each row contains the LP crop image and decoded text (bold)
- Newest plates appear at the top
- **Scroll**: Mouse wheel, `j`/`k` keys, or arrow keys
- **Close panel**: `ESC` (pipeline continues running)

## Console Output

### Per-Plate Output
```
Vehicle #42   | ABC12345   | conf  92% | len 8
```

### 30-Second Summary
```
--- Summary (30s) | Vehicles detected: 127 | Plates recognized (>78%): 43 ---
```

## Tips

- **Higher resolution = better crops**: Use `--width 1920 --height 1080` if your source is 1080p. The default 1280×720 downscale produces smaller LP crops.
- **LPRNet vs PaddleOCR**: LPRNet is optimized for license plates and generally produces better results on small crops. PaddleOCR recognizes letters but is trained on general scene text.
- **Confidence threshold**: The 78% threshold balances recall vs. accuracy. Lower it in `lpr.py` if you need more aggressive recognition at the cost of occasional misreads.
