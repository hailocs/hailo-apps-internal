# Gesture Detection

## What This App Does
Real-time hand gesture detection and recognition using MediaPipe Blaze models (palm detection + hand landmark) on Hailo-8/8L. Two-stage cascaded inference: detect palms, then run hand landmark estimation on each palm crop to recognize gestures (fist, open hand, pointing, peace, thumbs up/down, counting 1-4).

## Architecture
- **Type:** Pipeline app (cascaded multi-model)
- **Pattern:** Two-stage: palm detection → affine warp crop → hand landmark → gesture classification
- **Models:** `palm_detection_lite.hef` (192x192) + `hand_landmark_lite.hef` (224x224) — MediaPipe Blaze
- **Hardware:** hailo8, hailo8l, hailo10h
- **Postprocess:** Custom Python (blaze_base.py) or C++ filters depending on pipeline variant

## Key Files
| File | Purpose |
|------|---------|
| `gesture_detection.py` | GStreamer pipeline app — inference in Python callback, Hailo metadata output |
| `gesture_detection_cpp_pipeline.py` | Full C++ GStreamer pipeline — all pre/post in C++ hailofilter elements |
| `gesture_detection_standalone.py` | Python standalone (OpenCV) — no GStreamer, good for debugging |
| `pose_hand_detection.py` | Combined YOLOv8-Pose + hand gesture pipeline (person-crop palm detection) |
| `blaze_base.py` | Core math: SSD anchors, box decoding, weighted NMS, affine warp ROI |
| `blaze_palm_detector.py` | Palm detection model wrapper (HailoRT `InferVStreams`) |
| `blaze_hand_landmark.py` | Hand landmark model wrapper (HailoRT `InferVStreams`) |
| `gesture_recognition.py` | Gesture classification from 21 hand landmarks (pure Python, no Hailo deps) |
| `download_models.py` | Downloads HEF model files to `models/` |

## Pipeline Variants

### 1. GStreamer + Python inference (`gesture_detection.py`)
```
GStreamer source → Python callback:
  resize_pad(192x192) → palm_detection_lite (HailoRT InferVStreams)
  → anchor decode + NMS → detection2roi → affine warp (224x224)
  → hand_landmark_lite (HailoRT InferVStreams) → gesture classify
  → attach HailoDetection/HailoLandmarks/HailoClassification to buffer
→ hailooverlay → display
```

### 2. Full C++ pipeline (`gesture_detection_cpp_pipeline.py`)
```
source → hailonet(palm_det) → hailofilter(palm_postprocess)
  → hailocropper(palm_croppers) →
      inner: videoscale(224x224) → affine_warp → hailonet(hand_landmark) → postprocess
  → hailoaggregator → hailofilter(gesture_classification) → hailooverlay → display
```

### 3. Combined pose + hand (`pose_hand_detection.py`)
```
source → hailonet(yolov8-pose) → hailofilter(pose_postprocess) → hailotracker
  → hailonet(palm_det) → hailofilter(palm_postprocess)
  → hailocropper → [hand_landmark inner pipeline] → hailoaggregator
  → hailofilter(gesture_classify) → Python callback (associate hands to persons)
  → hailooverlay → display
```

### 4. Python standalone (`gesture_detection_standalone.py`)
```
OpenCV capture → resize_pad → palm_detection (HailoRT) → NMS → affine warp
  → hand_landmark (HailoRT) → gesture classify → OpenCV draw → display
```

## Callback Data Available
```python
# GStreamer pipeline (gesture_detection.py) attaches standard Hailo metadata:
roi = hailo.get_roi_from_buffer(buffer)
detections = roi.get_objects_typed(hailo.HAILO_DETECTION)
for detection in detections:
    label = detection.get_label()        # "palm"
    bbox = detection.get_bbox()
    confidence = detection.get_confidence()
    # Hand landmarks (21 MediaPipe keypoints)
    landmarks = detection.get_objects_typed(hailo.HAILO_LANDMARKS)
    if landmarks:
        points = landmarks[0].get_points()  # 21 points, bbox-relative coords
    # Gesture classification
    classifications = detection.get_objects_typed(hailo.HAILO_CLASSIFICATION)
    if classifications:
        gesture = classifications[0].get_label()  # e.g., "OPEN_HAND", "FIST"
```

## Models

| Model | File | Input | Anchors |
|-------|------|-------|---------|
| Palm Detection Lite | `palm_detection_lite.hef` | 192x192 RGB | 2016 SSD anchors (24x24 + 12x12) |
| Hand Landmark Lite | `hand_landmark_lite.hef` | 224x224 RGB | 21 keypoints + handedness + presence |

Download: `python -m community.apps.pipeline_apps.gesture_detection.download_models`

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

## Performance
| Platform | Python standalone | GStreamer | C++ standalone |
|----------|-------------------|-----------|----------------|
| RPi 5 | 50 FPS | — | **62 FPS** |
| Intel i7-1270P | 70 FPS | — | **72 FPS** |

## Key Technical Details
- `blaze_base.py` contains the core math shared across all variants: SSD anchor generation, box decoding with keypoint regression, weighted NMS, and affine warp ROI computation (`detection2roi`)
- The affine warp computes a rotation-aware crop from palm keypoints (wrist → middle finger base), expanded by a scale factor, for the hand landmark model
- C++ pipeline forces crop to 224x224 before affine warp so inverse rotation in normalized [0,1] is a simple rotation around (0.5, 0.5)
- `gesture_recognition.py` is pure Python with no Hailo/GStreamer deps — can be unit tested independently

## Self-Contained Postprocess
C++ postprocess .so files are built from `postprocess/` with its own meson.build.
Build: `cd postprocess && ./build.sh`
The C++ pipeline resolves .so paths: local build first (`postprocess/build/`), system install fallback (`/usr/local/hailo/resources/so/`).

## How to Extend
- **Add new gestures:** Edit `classify_hand_gesture()` in `gesture_recognition.py` — add conditions based on finger extension patterns or landmark geometry
- **Integrate into another pipeline:** Use `gesture_detection.py` as a reference — the `app_callback()` returns standard Hailo metadata consumable by any downstream GStreamer element
- **Improve accuracy:** Tune `HAND_FLAG_THRESHOLD` (default 0.5) and NMS parameters in `blaze_base.py`
- **Person-specific hands:** Use `pose_hand_detection.py` which associates detected hands with the nearest person via wrist proximity from YOLOv8-Pose keypoints

## Related Apps
| App | When to use instead |
|-----|-------------------|
| pose_estimation | Full-body pose (17 COCO keypoints) without hand-specific landmarks |
| detection | Detect hands without gesture recognition |
| clip | Text-based zero-shot gesture/action classification |
| semaphore_translator (community) | Arm-angle-based flag signal translation using body pose |
