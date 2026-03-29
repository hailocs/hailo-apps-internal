# Gesture Detection

Real-time hand gesture detection and recognition using MediaPipe Blaze models on Hailo-8/8L. Two-stage cascaded inference: detect palms, then run hand landmark estimation on each palm crop to recognize gestures.

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

## Prerequisites

- Hailo-8 or Hailo-8L with `hailort` and `hailo-tappas-core` installed
- Python 3.10+, GStreamer 1.0, OpenCV
- hailo-apps core framework (`source setup_env.sh`)

## Quick Start

```bash
# 1. Activate environment
source setup_env.sh

# 2. Download models (one-time)
python -m community.apps.pipeline_apps.gesture_detection.download_models

# 3. Build C++ postprocess libraries (one-time, for C++ pipeline variant)
cd community/apps/pipeline_apps/gesture_detection/postprocess
./build.sh
cd -

# 4. Run — Python pipeline (inference in Python callback)
python -m community.apps.pipeline_apps.gesture_detection.gesture_detection

# 5. Run — C++ pipeline (all inference on NPU, best performance)
python -m community.apps.pipeline_apps.gesture_detection.gesture_detection_cpp_pipeline

# 6. Run — Combined pose + hand detection
python -m community.apps.pipeline_apps.gesture_detection.pose_hand_detection

# 7. Run — Standalone (no GStreamer, good for debugging)
python -m community.apps.pipeline_apps.gesture_detection.gesture_detection_standalone
```

## Input Sources

```bash
# USB camera
python -m community.apps.pipeline_apps.gesture_detection.gesture_detection --input usb

# RPi CSI camera
python -m community.apps.pipeline_apps.gesture_detection.gesture_detection --input rpi

# Video file
python -m community.apps.pipeline_apps.gesture_detection.gesture_detection --input video.mp4
```

## Pipeline Variants

### 1. Python Pipeline (`gesture_detection.py`)
GStreamer source → Python callback (palm detection + hand landmark + gesture) → hailooverlay → display

All inference runs in the Python callback via HailoRT `InferVStreams`. Simplest to understand and modify.

### 2. C++ Pipeline (`gesture_detection_cpp_pipeline.py`) — Best Performance
```
source → hailonet(palm_det) + C++ postprocess
  → hailocropper → videoscale(224x224) → affine_warp → hailonet(hand) → postprocess
  → hailoaggregator → gesture_classification → hailooverlay → display
```

All processing in C++ hailofilter elements. ~62 FPS on RPi 5 (vs ~50 FPS Python variant).

### 3. Pose + Hand (`pose_hand_detection.py`)
Adds YOLOv8-Pose upstream for full-body skeleton. Associates detected hands with nearest person by wrist proximity.

### 4. Standalone (`gesture_detection_standalone.py`)
Pure Python with OpenCV + HailoRT. No GStreamer dependency. Good for SSH/headless debugging. Supports `--debug` flag for per-stage visualization.

## Building the C++ Postprocess Libraries

Required for the C++ pipeline variant (`gesture_detection_cpp_pipeline.py`):

```bash
cd community/apps/pipeline_apps/gesture_detection/postprocess
./build.sh              # Build + install to /usr/local/hailo/resources/so/
./build.sh --no-install # Build only (use local build/ directory)
```

The C++ pipeline automatically checks the local `postprocess/build/` directory first, then falls back to the system install path.

## Building the Standalone C++ App

```bash
cd community/apps/pipeline_apps/gesture_detection/cpp
./build.sh
./build/gesture_detection              # Run with default camera
./build/gesture_detection video.mp4    # Run with video file
```

## Models

| Model | Input | Output |
|-------|-------|--------|
| `palm_detection_lite.hef` | 192x192 RGB | Up to 2 palm detections with 7 keypoints |
| `hand_landmark_lite.hef` | 224x224 RGB | 21 hand landmarks + handedness + presence |

Source: [AlbertaBeef/blaze_tutorial](https://github.com/AlbertaBeef/blaze_tutorial) (MediaPipe Blaze for Hailo)

## Performance

| Platform | Python Pipeline | C++ Pipeline | Standalone C++ |
|----------|----------------|--------------|----------------|
| RPi 5 (Hailo-8L) | ~50 FPS | **~62 FPS** | — |
| Intel i7 (Hailo-8) | ~70 FPS | **~72 FPS** | — |

## How to Extend

- **Add gestures:** Edit `gesture_recognition.py` — add conditions in `classify_hand_gesture()` based on finger extension patterns or landmark geometry
- **Integrate into another pipeline:** Use `gesture_detection.py` as reference — the callback attaches standard Hailo metadata (HailoDetection, HailoLandmarks, HailoClassification)
- **Tune accuracy:** Adjust `HAND_FLAG_THRESHOLD` (default 0.5) and NMS parameters in `blaze_base.py`
