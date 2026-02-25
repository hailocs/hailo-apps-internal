License Plate Recognition (LPR)
================================
This example demonstrates real-time license plate recognition using a Hailo-8, Hailo-8L, or Hailo-10H device.<br>
It processes input videos or camera streams through a three-stage pipeline (vehicle detection → LP detection → OCR), with tracker-based deduplication, a center-frame ROI gate, and a live display panel.

![LPR Demo](../../../../doc/images/lpr.gif)

Requirements
------------
- hailo_platform:
    - 4.23.0 (for Hailo-8 devices)
    - 5.1.1 (for Hailo-10H devices)
- opencv-python

Supported Models
----------------
| Stage | Model | Input Size |
|---|---|---|
| Vehicle detection | `yolov5m_vehicles` | 640×640 |
| LP detection | `tiny_yolov4_license_plates` | 416×416 |
| OCR (default) | LPRNet | 300×75 |
| OCR (alternative) | PaddleOCR | 320×48 |

## Installation and Usage

Run this app in one of two ways:
1. Standalone installation in a clean virtual environment (no TAPPAS required) — see [Option 1](#option-1-standalone-installation)
2. From an installed `hailo-apps` repository — see [Option 2](#option-2-inside-an-installed-hailo-apps-repository)

## Option 1: Standalone Installation

To avoid compatibility issues, it's recommended to use a clean virtual environment.

0. Install PCIe driver and PyHailoRT
    - Download and install the PCIe driver and PyHailoRT from the Hailo website
    - To install the PyHailoRT whl:
    ```shell script
    pip install hailort-X.X.X-cpXX-cpXX-linux_x86_64.whl
    ```

1. Clone the repository:
    ```shell script
    git clone https://github.com/hailo-ai/hailo-apps.git
    cd hailo-apps/python/pipeline_apps/lpr
    ```

2. Install dependencies:
    ```shell script
    pip install -r requirements.txt
    ```

## Option 2: Inside an Installed hailo-apps Repository
If you installed the full repository:
```shell script
git clone https://github.com/hailo-ai/hailo-apps.git
cd hailo-apps
sudo ./install.sh
source setup_env.sh
```

Then the app is already ready for usage:
```shell script
cd hailo-apps/python/pipeline_apps/lpr
```

## Run

After completing either installation option, run:
```shell script
# Default (LPRNet, digits only)
hailo-lpr --input /path/to/video.mp4

# PaddleOCR (full alphanumeric charset)
hailo-lpr --input /path/to/video.mp4 --ocr-engine paddle

# Higher resolution for better LP crops on highway footage
hailo-lpr --input /path/to/video.mp4 --width 1920 --height 1080
```

Arguments
---------
All standard pipeline arguments (`--input`, `--width`, `--height`, `--show-fps`, `--sync`, etc.) are supported. Additional LPR-specific arguments:

| Argument | Default | Description |
|---|---|---|
| `--ocr-engine` | `lprnet` | OCR backend: `lprnet` (digits 0-9, fast) or `paddle` (full ASCII charset) |
| `--input, -i` | — | Input source: a video file path, `usb` for USB camera, or `rpi` for Raspberry Pi camera. Use `--list-inputs` to see predefined inputs. |
| `--width` | `1280` | Input width in pixels |
| `--height` | `720` | Input height in pixels |
| `--show-fps` | — | Display FPS performance metrics |
| `--list-models` | — | Print all supported models for this application and exit |
| `--list-inputs` | — | Print available predefined input resources and exit |

For more information:
```shell script
hailo-lpr -h
```

## Pipeline Architecture

The pipeline adapts automatically based on the detected Hailo device:

**Hailo-10H:**
```
Source → Vehicle Detection (YOLOv5m) → Tracker → Crop Vehicles → LP Detection (Tiny-YOLOv4) → User Callback (OCR) → Overlay → Display
```

**Hailo-8 / Hailo-8L:**
```
Source → Vehicle Detection (YOLOv5m) → Tracker → User Callback (LP Detection + OCR) → Overlay → Display
```

| Stage | Model | Hailo-10H | Hailo-8 / Hailo-8L |
|---|---|---|---|
| Vehicle detection | `yolov5m_vehicles` (640×640) | GStreamer `hailonet` | GStreamer `hailonet` |
| LP detection | `tiny_yolov4_license_plates` (416×416) | GStreamer `hailonet` inside cropper | HailoRT Python API in callback |
| OCR | LPRNet (300×75) or PaddleOCR (320×48) | HailoRT Python API in callback | HailoRT Python API in callback |

On **Hailo-10H**, LP detection runs inside a GStreamer `hailocropper` element using the TAPPAS `libyolo_post.so` postprocess. On **Hailo-8/8L**, the TAPPAS postprocess SO is incompatible with the model output, so LP detection runs in the Python callback using `HailoInfer` with a built-in YOLOv4 postprocess implementation. The switch is automatic — no user configuration needed.

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

🔧 Configuration and Tuning
----------------------------

#### Center 1/3 ROI Gate

Only vehicles whose **vertical center** falls within the **middle third** of the frame (Y 33%–66%) are processed for LP detection and OCR. This focuses recognition on the zone where plates are large enough for reliable reads and filters out distant or very close vehicles.

```python
ROI_Y_START = 1.0 / 3.0   # top of ROI zone (normalized)
ROI_Y_END   = 2.0 / 3.0   # bottom of ROI zone (normalized)
```

Vehicles outside this band are still detected and tracked (bounding boxes visible), but OCR is not attempted.

#### 78% Confidence Threshold

Only plates with **OCR confidence ≥ 78%** are accepted. Below this threshold, the result is discarded and the vehicle will be retried on subsequent frames until either:
- A read exceeds 78%, or
- The vehicle leaves the frame

This is the key quality gate. A minimum text length of **4 characters** is also enforced.

```python
MIN_OCR_CONFIDENCE = 0.78
```

#### Tracker Deduplication

The pipeline uses `hailotracker` to assign persistent IDs to vehicles. Once a plate is recognized with ≥ 78% confidence for a given track ID, that vehicle is never re-processed — OCR inference is skipped entirely on future frames.

Each unique vehicle is recognized **at most once**, keeping compute usage proportional to unique vehicles rather than total frames.

## Display Panel

A separate OpenCV window ("LPR Panel") shows all recognized plates in real time:

- Each row contains the LP crop image and decoded text (bold)
- Newest plates appear at the top
- **Scroll**: Mouse wheel, `j`/`k` keys, or arrow keys
- **Close panel**: `ESC` (pipeline continues running)

## Console Output

**Per-Plate Output:**
```
Vehicle #42   | ABC12345   | conf  92% | len 8
```

**30-Second Summary:**
```
--- Summary (30s) | Vehicles detected: 127 | Plates recognized (>78%): 43 ---
```

Example
-------

**List supported networks:**
```shell script
hailo-lpr --list-models
```

**List available input resources:**
```shell script
hailo-lpr --list-inputs
```

**LPR with default OCR engine (LPRNet):**
```shell script
hailo-lpr --input /path/to/video.mp4
```

**LPR with PaddleOCR (full charset):**
```shell script
hailo-lpr --input /path/to/video.mp4 --ocr-engine paddle
```

**LPR on USB camera with 1080p input:**
```shell script
hailo-lpr --input usb --width 1920 --height 1080
```

Additional Notes
----------------
- **Higher resolution = better crops**: Use `--width 1920 --height 1080` if your source is 1080p. The default 1280×720 downscale produces smaller LP crops.
- **LPRNet vs PaddleOCR**: LPRNet is optimized for license plates and generally produces better results on small crops. PaddleOCR recognizes letters but is trained on general scene text.
- **Confidence threshold**: The 78% threshold balances recall vs. accuracy. Lower it in `lpr.py` if you need more aggressive recognition at the cost of occasional misreads.
- The list of supported models is defined in `resources_config.yaml`.
- For any issues, open a post on the [Hailo Community](https://community.hailo.ai).

Disclaimer
----------
This code example is provided by Hailo solely on an "AS IS" basis and "with all faults". No responsibility or liability is accepted or shall be imposed upon Hailo regarding the accuracy, merchantability, completeness or suitability of the code example. Hailo shall not have any liability or responsibility for errors or omissions in, or any business decisions made by you in reliance on this code example or any part of it. If an error occurs when running this example, please open a ticket in the "Issues" tab.<br />
Please note that this example was tested on specific versions and we can only guarantee the expected results using the exact version mentioned above on the exact environment. The example might work for other versions, other environment or other HEF file, but there is no guarantee that it will.
