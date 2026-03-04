# Gesture Detection App

## Overview

Real-time gesture detection pipeline using Hailo-10H. Two-stage architecture:

1. **YOLOv8 Pose Estimation** - detects persons with 17 body keypoints (COCO format)
2. **Hand Landmark Lite** - runs on cropped hand regions, outputs 21 hand keypoints (MediaPipe format)

A Python callback then classifies gestures (fist, open hand, peace, pointing, thumbs up/down, T-pose, etc.) from the landmark geometry.

## Architecture

```
Camera → YOLOv8 Pose → Tracker → Cropper(hand_crop) → Hand Landmark → Aggregator → Callback → Display
              │                       │                      │                │
         Person detections     Crops hands from       21 keypoints       Merges hand
         + 17 body keypoints   wrist keypoints        per hand           landmarks back
                               using elbow-wrist                         into person
                               distance for sizing                       detections
```

### GStreamer Pipeline Structure

```
SOURCE → INFERENCE(yolov8_pose + yolov8pose_postprocess) → TRACKER(class_id=0)
       → CROPPER(hand_crop / hand_landmark_inference + hand_landmark_postprocess)
       → USER_CALLBACK → DISPLAY(hailooverlay)
```

## Files

| File | Purpose |
|------|---------|
| `gesture_detection.py` | Main app entry point + Python callback for gesture classification |
| `gesture_detection_pipeline.py` | GStreamer pipeline class (two-stage: pose + hand landmark) |
| `gesture_recognition.py` | Pure Python gesture classification logic (no Hailo deps) |
| `test_hand_landmark_pipeline.py` | Standalone test: runs hand landmark model directly on camera (no pose/cropper) |

### C++ Post-Processing (in `hailo_apps/postprocess/cpp/`)

| File | Purpose |
|------|---------|
| `hand_croppers.cpp/.hpp` | Cropper function: extracts hand crop regions from YOLOv8 pose wrist keypoints |
| `hand_landmark_postprocess.cpp/.hpp` | Post-process: parses hand_landmark_lite model output tensors into HailoLandmarks |

## Models

| Model | HEF | Input | Outputs |
|-------|-----|-------|---------|
| YOLOv8m Pose | `yolov8m_pose.hef` | 640x640 RGB | Person detections + 17 COCO keypoints |
| Hand Landmark Lite | `hand_landmark_lite.hef` | 224x224 RGB | 4 tensors (see below) |

### Hand Landmark Lite Output Tensors

From `hailortcli parse-hef hand_landmark_lite.hef`:

| Tensor | Shape | Description |
|--------|-------|-------------|
| `hand_landmark_lite/fc1` | NC(63) | Screen landmarks: 21 keypoints x (x, y, z) in pixel coords [0..224] |
| `hand_landmark_lite/fc2` | NC(1) | Hand flag: presence confidence (pre-sigmoid) |
| `hand_landmark_lite/fc3` | NC(63) | World landmarks: 21 keypoints x (x, y, z) in metric 3D coords |
| `hand_landmark_lite/fc4` | NC(1) | Handedness: left/right classification |

**Important:** There are TWO 63-element tensors and TWO 1-element tensors. The postprocess matches by tensor name suffix (`fc1`, `fc2`) to avoid grabbing the wrong one.

**Status:** The tensor-to-semantic mapping (which fc is landmarks vs world_landmarks, which is hand_flag vs handedness) is **assumed based on MediaPipe conventions and needs verification**. If landmarks look wrong, try swapping fc1↔fc3 or fc2↔fc4.

## C++ Post-Process Details

### `hand_croppers.cpp` — `hand_crop()`

Called by `hailocropper`. For each person detection with pose landmarks:

1. Extracts left wrist (keypoint 9) and right wrist (keypoint 10)
2. Filters by confidence threshold (0.3)
3. Estimates hand size from wrist-to-elbow distance × 2.5 (fallback: 15% of person bbox height)
4. Creates square crop centered on wrist
5. **Adds hand detection to person detection** (`detection->add_object(hand_detection)`) — this is required so the hand stays in the person's ROI tree after the aggregator merges
6. Returns hand detections as crop ROIs
7. Uses track-age fairness (oldest track gets priority), max 2 hands per frame

### `hand_landmark_postprocess.cpp` — `hand_landmark_postprocess()`

Called by `hailofilter` after hand landmark inference:

1. Finds tensors by name suffix (`fc1` for landmarks, `fc2` for hand flag)
2. Checks hand presence via sigmoid(fc2) > 0.5 threshold
3. Dequantizes fc1, reshapes to [21, 3], normalizes x,y by /224.0
4. Attaches landmarks to the correct target in the ROI hierarchy:
   - **Full pipeline (cropper mode):** The ROI received is the **person detection** (the cropper sends the parent). Finds the "hand" sub-detection and adds landmarks there.
   - **Standalone mode (test pipeline):** No detection hierarchy; adds HailoLandmarks directly to the frame ROI.

### Key Insight: ROI Hierarchy in Cropper Pipeline

The `hailocropper` sends the **person detection** (parent) as the ROI through the inner pipeline, not the hand detection itself. This means:
- The hand landmark postprocess receives `person detection` as its ROI
- It must search for the "hand" sub-detection within that ROI
- Landmarks are added to the hand detection, not the person

Without `detection->add_object(hand_detection)` in the cropper, the hand detection wouldn't be in the person's ROI tree and the callback couldn't find it.

## Gesture Recognition (`gesture_recognition.py`)

Pure Python, no Hailo dependencies. Classifies from 21 hand landmarks:

| Gesture | Condition |
|---------|-----------|
| `FIST` | 0 fingers extended |
| `OPEN_HAND` | 5 fingers extended |
| `POINTING` | Index only |
| `PEACE` | Index + middle |
| `THUMBS_UP` | Thumb only, tip above wrist |
| `THUMBS_DOWN` | Thumb only, tip below wrist |
| `ONE`..`FOUR` | 1-4 fingers (generic) |
| `T_POSE` | Body: both arms horizontal, wrists spread > 1.5× shoulder width |

Finger extension detection: compares tip-to-wrist distance vs PIP-to-wrist distance.

## Running

### Full gesture detection pipeline
```bash
source setup_env.sh
python hailo_apps/python/pipeline_apps/gesture_detection/gesture_detection.py
```

### Standalone hand landmark test (no pose, no cropper)
```bash
source setup_env.sh
python hailo_apps/python/pipeline_apps/gesture_detection/test_hand_landmark_pipeline.py
```

Runs hand_landmark_lite directly on the full camera frame. Useful for verifying the postprocess tensor parsing and hailooverlay drawing independently.

### Building the C++ post-process
```bash
source setup_env.sh
hailo-compile-postprocess
```

Compiles and installs `libhand_landmark_postprocess.so` and `libhand_croppers.so` to `/usr/local/hailo/resources/so/`.

## Debug Prints

Both C++ files currently have `fprintf(stderr, ...)` debug prints:

- `[hand_crop]` — cropper: detections found, wrist confidences, crop coordinates
- `[hand_landmark]` — postprocess: tensor names/sizes, hand flag values, raw landmark coords

**Remove these before production** by deleting the `fprintf` lines and the `#include <cstdio>`.

## Known Issues / TODO (H10h pipeline)

- **Tensor mapping unverified:** fc1 vs fc3 (screen vs world landmarks) and fc2 vs fc4 (hand flag vs handedness) mapping is assumed. If landmarks look wrong (junk positions), swap the suffix constants in `hand_landmark_postprocess.cpp`.
- **Hand landmark normalization:** Assumes fc1 outputs pixel coordinates in [0..224] range, normalized by dividing by 224. Verify by checking the raw dequantized values in the debug prints — they should be roughly in the 0-224 range when pointing a hand at the camera.
- Debug `fprintf` prints should be removed once the pipeline is verified working.

---

## Hailo-8 Mode (MediaPipe Blaze)

An alternative pipeline for **Hailo-8** using MediaPipe Blaze models (palm detection + hand landmark). Uses HailoRT Python API directly instead of GStreamer.

### Architecture (H8)

```
Camera (OpenCV) → resize_pad(192x192) → palm_detection_lite.hef (HailoRT)
  → anchor decode + NMS → detection2roi → affine warp (224x224)
  → hand_landmark_lite.hef (HailoRT) → denormalize landmarks
  → gesture_recognition.py → OpenCV display
```

### H8-Specific Files

| File | Purpose |
|------|---------|
| `gesture_detection_h8.py` | Main H8 entry point (OpenCV + HailoRT pipeline) |
| `blaze_base.py` | Common utilities: anchor generation, box decoding, NMS, ROI extraction |
| `blaze_palm_detector.py` | Palm detection wrapper (palm_detection_lite.hef) |
| `blaze_hand_landmark.py` | Hand landmark wrapper (hand_landmark_lite.hef) |
| `download_blaze_models.py` | Downloads Blaze HEF models from AlbertaBeef releases |

### H8 Models

| Model | HEF | Input | Anchors | Outputs |
|-------|-----|-------|---------|---------|
| Palm Detection Lite | `palm_detection_lite.hef` | 192x192 RGB | 2016 | 4 tensors: scores + boxes (2 scales) |
| Hand Landmark Lite | `hand_landmark_lite.hef` | 224x224 RGB | — | fc1: landmarks(63), fc4: confidence(1), fc3: handedness(1) |

### Running (H8)

```bash
# 1. Download models
python -m hailo_apps.python.pipeline_apps.gesture_detection.download_blaze_models

# 2. Run gesture detection
source setup_env.sh
python -m hailo_apps.python.pipeline_apps.gesture_detection.gesture_detection_h8

# With custom video source
python -m hailo_apps.python.pipeline_apps.gesture_detection.gesture_detection_h8 --input video.mp4

# With custom model paths
python -m hailo_apps.python.pipeline_apps.gesture_detection.gesture_detection_h8 \
    --palm-model /path/to/palm_detection_lite.hef \
    --hand-model /path/to/hand_landmark_lite.hef
```

### H8 Limitations

- **No T-pose detection** — no body pose model in H8 mode
- **No GStreamer** — uses OpenCV capture + HailoRT InferVStreams directly

### Credits

H8 Blaze implementation based on [AlbertaBeef/blaze_app_python](https://github.com/AlbertaBeef/blaze_app_python).
See also: [Hackster article](https://www.hackster.io/AlbertaBeef/blaze-app-hailo-8-edition-f1e14c).
