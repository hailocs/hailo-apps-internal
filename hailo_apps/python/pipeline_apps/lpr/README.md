# License Plate Recognition (LPR)

Real-time license plate recognition on Hailo accelerators using a three-stage GStreamer pipeline with tracker-based deduplication and a live display panel.

## Pipeline Architecture

```
Source → Vehicle Detection (YOLOv5m) → Tracker → Crop Vehicles → LP Detection (Tiny-YOLOv4) → User Callback (OCR) → Display
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

All standard pipeline arguments (`--input`, `--width`, `--height`, `--show-fps`, `--sync`, etc.) are supported. Additional LPR-specific arguments:

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

## Quality Gates

Recognition uses a two-layer filtering approach:

### Pre-OCR: Bounding Box Size Filter
Crops that are too small or too large are skipped before running OCR inference:

| Parameter | Value | Rationale |
|---|---|---|
| `MIN_LP_WIDTH_PIXELS` | 20 | Below this, the plate is too small for any OCR model to decode |
| `MIN_LP_HEIGHT_PIXELS` | 8 | Minimum height for character features |
| `MAX_LP_WIDTH_PIXELS` | 600 | A plate this large is likely a false-positive detection |
| `MAX_LP_HEIGHT_PIXELS` | 200 | Same — rejects implausibly large detections |

### Post-OCR: Confidence Threshold
Only plates with **OCR confidence ≥ 78%** (`MIN_OCR_CONFIDENCE = 0.78`) are accepted. Below this threshold, the result is discarded and the vehicle will be retried on subsequent frames.

A minimum text length of **4 characters** (`MIN_LENGTH = 4`) is also enforced.

## Tracker Deduplication

The pipeline uses `hailotracker` to assign persistent IDs to vehicles. Once a plate is recognized with ≥ 78% confidence for a given track ID, that vehicle is never re-processed — OCR inference is skipped entirely on future frames for that vehicle.

This means each unique vehicle is recognized **at most once**, keeping compute usage proportional to unique vehicles rather than total frames.

## Display Panel

A separate OpenCV window ("LPR Panel") shows all recognized plates in real time:

- Each row contains the LP crop image, decoded text, OCR confidence, and vehicle track ID
- Newest plates appear at the top
- **Scroll**: Mouse wheel, `j`/`k` keys, or arrow keys
- **Close panel**: `ESC` (pipeline continues running)

The header shows the running count of recognized plates.

## Console Output

### Per-Plate Output
Each recognized plate prints a single line:
```
Vehicle #42   | ABC12345   | conf  92% | len 8
```

### 30-Second Summary
Every 30 seconds, a summary line is printed:
```
--- Summary (30s) | Vehicles detected: 127 | Plates recognized (>78%): 43 ---
```

## Tips

- **Higher resolution = better crops**: Use `--width 1920 --height 1080` if your source is 1080p. The default 1280×720 downscale produces smaller LP crops.
- **LPRNet vs PaddleOCR**: LPRNet is optimized for license plates and generally produces better results on small crops. PaddleOCR recognizes letters but is trained on general scene text.
- **Confidence threshold**: The 78% threshold balances recall vs. accuracy. Lower it in the source code if you need more aggressive recognition at the cost of occasional misreads.
