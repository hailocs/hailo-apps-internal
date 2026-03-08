# Gesture Detection

Real-time hand gesture detection using MediaPipe Blaze models (palm detection + hand landmark) on Hailo-8/8L.

## Architecture

```
Camera/Video → resize_pad(192x192) → palm_detection_lite (Hailo)
  → anchor decode + NMS → detection2roi → affine warp (224x224)
  → hand_landmark_lite (Hailo) → denormalize landmarks
  → gesture classification → display
```

Two-stage pipeline:
1. **Palm Detection** (`palm_detection_lite.hef`, 192x192) — detects palm bounding boxes with 7 keypoints
2. **Hand Landmark** (`hand_landmark_lite.hef`, 224x224) — predicts 21 hand keypoints per detected palm

Gesture classification runs on the 21 landmarks in pure Python.

## Pipelines

### GStreamer Pipeline (recommended)

`gesture_detection_gst.py` — GStreamer app with `hailooverlay` rendering.

Inference runs in a Python callback via HailoRT `InferVStreams`. Results are attached as standard Hailo metadata (`HailoDetection`, `HailoLandmarks`, `HailoClassification`) so `hailooverlay` and downstream pipeline elements can consume them.

```bash
source setup_env.sh

# Camera
python -m hailo_apps.python.pipeline_apps.gesture_detection.gesture_detection_gst

# Video file
python -m hailo_apps.python.pipeline_apps.gesture_detection.gesture_detection_gst --input video.mp4

# Image
python -m hailo_apps.python.pipeline_apps.gesture_detection.gesture_detection_gst --input photo.jpg
```

**Hailo metadata structure per frame:**
```
HailoROI
  └─ HailoDetection("palm", bbox, confidence)
       ├─ HailoLandmarks("hand_landmarks", 21 points, skeleton connections)
       └─ HailoClassification("gesture", label="OPEN_HAND", confidence)
```

### Standalone Pipeline (OpenCV)

`gesture_detection_h8.py` — Pure Python with OpenCV display. No GStreamer dependency.

Useful for debugging or environments without GStreamer/hailooverlay.

```bash
source setup_env.sh

python -m hailo_apps.python.pipeline_apps.gesture_detection.gesture_detection_h8
python -m hailo_apps.python.pipeline_apps.gesture_detection.gesture_detection_h8 --input video.mp4
```

## Setup

### Download Models

```bash
python -m hailo_apps.python.pipeline_apps.gesture_detection.download_blaze_models
```

Downloads `palm_detection_lite.hef` and `hand_landmark_lite.hef` into the `models/` directory from [AlbertaBeef/blaze_tutorial releases](https://github.com/AlbertaBeef/blaze_tutorial/releases).

## Files

| File | Description |
|------|-------------|
| `gesture_detection_gst.py` | GStreamer pipeline app (production) |
| `gesture_detection_h8.py` | Standalone OpenCV app (reference/debug) |
| `blaze_base.py` | Core math: SSD anchor generation, box decoding, weighted NMS, affine warp ROI extraction |
| `blaze_palm_detector.py` | Palm detection model wrapper (`InferVStreams`) |
| `blaze_hand_landmark.py` | Hand landmark model wrapper (`InferVStreams`) |
| `gesture_recognition.py` | Pure Python gesture classification from 21 hand landmarks |
| `download_blaze_models.py` | Downloads HEF model files |
| `models/` | HEF model directory |

## Models

| Model | File | Input | Description |
|-------|------|-------|-------------|
| Palm Detection Lite | `palm_detection_lite.hef` | 192x192 RGB uint8 | 2016 SSD anchors, 4 output tensors (scores + boxes at 2 scales) |
| Hand Landmark Lite | `hand_landmark_lite.hef` | 224x224 RGB uint8 | 4 output tensors (see below) |

### Hand Landmark Output Tensors

| Tensor suffix | Shape | Description |
|---------------|-------|-------------|
| `fc1` | (63,) | Screen landmarks: 21 keypoints x (x, y, z) in pixel coords [0..224] |
| `fc2` | (63,) | World landmarks (unused) |
| `fc3` | (1,) | Handedness: >0.5 = left hand |
| `fc4` | (1,) | Hand presence confidence (raw logit, apply sigmoid) |

### Palm Detection Output Tensors

| Tensor | Shape | Description |
|--------|-------|-------------|
| `conv29` | (24, 24, 2) | Scores, large scale (1152 anchors) |
| `conv24` | (12, 12, 6) | Scores, small scale (864 anchors) |
| `conv30` | (24, 24, 36) | Boxes, large scale (1152 x 18 coords) |
| `conv25` | (12, 12, 108) | Boxes, small scale (864 x 18 coords) |

Order: large (24x24) first, then small (12x12) to match anchor generation.

## Supported Gestures

| Gesture | Condition |
|---------|-----------|
| `FIST` | 0 fingers extended |
| `OPEN_HAND` | 5 fingers extended |
| `POINTING` | Index finger only |
| `PEACE` | Index + middle |
| `THUMBS_UP` | Thumb only, tip above wrist |
| `THUMBS_DOWN` | Thumb only, tip below wrist |
| `ONE`..`FOUR` | 1-4 fingers (generic fallback) |

Finger extension detection compares tip-to-wrist distance vs PIP-to-wrist distance.

## Hand Landmark Indices (MediaPipe)

```
0: WRIST
1-4: THUMB (CMC, MCP, IP, TIP)
5-8: INDEX (MCP, PIP, DIP, TIP)
9-12: MIDDLE (MCP, PIP, DIP, TIP)
13-16: RING (MCP, PIP, DIP, TIP)
17-20: PINKY (MCP, PIP, DIP, TIP)
```

## Integration

The GStreamer pipeline attaches standard Hailo metadata to each buffer. To integrate with another pipeline:

1. Use `gesture_detection_gst.py` as an example of the callback pattern
2. The `app_callback()` function can be reused in any GStreamer pipeline that has an `identity_callback` element
3. Downstream elements receive `HailoDetection` objects with landmarks and classifications attached

## Test Photos

The `photo*.jpg` files contain test images for validation:
- `photo.jpg` — Open hand (5 fingers) → `OPEN_HAND`
- `photo1.jpg` — Thumbs up → `THUMBS_UP`
- `photo2.jpg` — Peace sign → `PEACE`

## Credits

Based on [AlbertaBeef/blaze_app_python](https://github.com/AlbertaBeef/blaze_app_python).
See also: [Hackster article](https://www.hackster.io/AlbertaBeef/blaze-app-hailo-8-edition-f1e14c).
