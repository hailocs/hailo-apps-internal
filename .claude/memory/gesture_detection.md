# Gesture Detection App - Detailed Notes

## Working Pipelines (VERIFIED)

### 1. GStreamer Pipeline: `gesture_detection_gst.py`
- GStreamer source → Python callback (InferVStreams) → hailooverlay → display
- Attaches: HailoDetection("palm") + HailoLandmarks("hand_landmarks", 21pts) + HailoClassification("gesture")
- **Landmarks must be normalized relative to the detection bbox** (not the frame) for hailooverlay
- `python -m hailo_apps.python.pipeline_apps.gesture_detection.gesture_detection_gst --input <source>`

### 2. Standalone OpenCV: `gesture_detection_h8.py`
- Pure Python (OpenCV + HailoRT InferVStreams), no GStreamer
- `python -m hailo_apps.python.pipeline_apps.gesture_detection.gesture_detection_h8 --input <source>`

## Blaze Model Tensor Mapping (VERIFIED)
### Palm Detection (palm_detection_lite.hef, 192x192)
- Score tensors: conv29 (24x24x2, 1152), conv24 (12x12x6, 864) — large first
- Box tensors: conv30 (24x24x36), conv25 (12x12x108) — 18 coords/anchor

### Hand Landmark (hand_landmark_lite.hef, 224x224)
- `fc1`: screen landmarks (21x3=63) in 0..224 pixel coords
- `fc2`: world landmarks (63) — unused
- `fc3`: handedness (1) — >0.5 = left
- `fc4`: hand presence confidence (1) — raw logit, sigmoid

## Key Files (cleaned up)
- `blaze_base.py` — anchors, NMS, ROI extraction, affine warp
- `blaze_palm_detector.py` / `blaze_hand_landmark.py` — model wrappers
- `gesture_recognition.py` — pure Python gesture classification
- `gesture_detection_gst.py` — GStreamer pipeline (production)
- `gesture_detection_h8.py` — standalone OpenCV (reference)
- `download_blaze_models.py` — model downloader

## Hailo Metadata (hailooverlay expects)
- Landmarks on HailoDetection are **relative to the detection bbox** [0,1]
- `add_landmarks_to_detection()` in C++ does: `(landmark - bbox_min) / bbox_size`
- In Python: `px = (lm_pixel_x - bbox_xmin) / bbox_width`

### 3. Full C++ GStreamer Pipeline: `gesture_detection_cpp_pipeline.py`
- All pre/post processing in C++, inference via hailonet (streaming)
- Pipeline: source → palm_detection (hailonet+hailofilter) → palm_croppers (hailocropper) → [hand_affine_warp → hand_landmark hailonet+hailofilter] → gesture_classification → display
- **104+ FPS** uncapped (vs 68.8 Python, 44.3 native MediaPipe)
- `python -m hailo_apps.python.pipeline_apps.gesture_detection.gesture_detection_cpp_pipeline --input <source>`

### 4. Native MediaPipe CPU Baseline: `gesture_detection_native.py`
- Pure CPU MediaPipe HandLandmarker (tasks API v0.10.32)
- `python -m hailo_apps.python.pipeline_apps.gesture_detection.gesture_detection_native --input <source>`

## C++ Postprocess Libraries (all compiled, in /usr/local/hailo/resources/so/)
- `libpalm_detection_postprocess.so` — SSD anchor decode + weighted NMS
- `libpalm_croppers.so` — palm→hand ROI, rotation angle in label string
- `libhand_affine_warp.so` — OpenCV warpAffine rotation correction (use-gst-buffer=true)
- `libhand_landmark_postprocess.so` — 21-keypoint landmark extraction
- `libgesture_classification.so` — finger extension → gesture label
- `libhand_croppers.so` — person pose wrist→hand ROI (alternative cropper)

## Important: palm_angle storage
- Rotation theta stored as **label string** (not confidence) in HailoClassification("palm_angle")
- Confidence must be [0,1], theta is radians (-π to π), so use `std::to_string(theta)` in label
- `hand_affine_warp.cpp` reads via `std::stof(cls->get_label())`

## Bugs Found & Fixed (March 2026)

### 1. Rotation-Unaware DY Shift (MAJOR)
- **Files**: `blaze_base.py`, `palm_croppers.cpp`, `hand_landmark.cpp`
- **Bug**: `yc += dy * scale` only shifts in Y, not along the hand axis
- **Fix**: Rotate the shift: `xc += -dy * scale * sin(theta); yc += dy * scale * cos(theta)`
- For rotated hands, the old code put the ROI center off to the side of the hand

### 2. Variable AABB Expand Factor
- **Files**: `palm_croppers.cpp`, `hand_affine_warp.cpp`, `hand_landmark_postprocess.cpp`
- **Bug**: `expand = |cos θ| + |sin θ|` changed with rotation → unstable crop size
- **Fix**: Fixed `expand = √2 = 1.41421356` in all three files
- Maximum envelope for any rotation, crop size now independent of orientation

### 3. Non-Square AABB on Non-Square Frames
- **Files**: `palm_croppers.cpp`
- **Bug**: Used palm width only for scale; no max(w,h) for non-square palm bboxes
- **Fix**: `scale_px = std::max(width_px, height_px)` before applying DSCALE
- Also: pixel-space square crop → different normalized w/h is CORRECT (not a bug)

### 4. scaling_bbox Distortion (MAJOR — bbox not tight around landmarks)
- **File**: `gesture_classification.cpp`
- **Root cause**: INFERENCE_PIPELINE_WRAPPER sets non-identity `scaling_bbox` on ROI
  (letterbox transform: ymin=-0.3889, h=1.7778 for 16:9 → square model)
- hailooverlay applies scaling_bbox to detection bboxes but NOT to landmarks
- gesture_classification creates tight hand dets in frame-absolute coords
- **Fix**: `roi->clear_scaling_bbox()` at end of gesture_classification
- See [tappas_coordinate_spaces.md](tappas_coordinate_spaces.md) for full analysis

### 5. Missing Letterbox for Palm Detection
- **Files**: `gesture_detection_cpp_pipeline.py`, `pose_hand_detection.py`
- **Bug**: `INFERENCE_PIPELINE` videoscale stretched instead of letterboxing
- **Fix**: Added `letterbox=True` param to `INFERENCE_PIPELINE()` helper;
  passes `add-borders=true` to videoscale for aspect-ratio-preserving resize

## Critical: Aspect Ratio in palm_croppers
- Python `blaze_base.detection2roi` works in **pixel coords** (after denormalize_detections)
- C++ `palm_croppers.cpp` must also work in pixel space via `image->width()/height()`
- The AABB must be **square in pixel space** so videoscale to 224x224 is uniform
- All three C++ files (palm_croppers, hand_affine_warp, hand_landmark_postprocess) must
  use the SAME fixed expand factor (√2)

## Remaining TODO
- Remove debug fprintf from gesture_classification.cpp and hand_landmark_postprocess.cpp
- Verify pose_hand_detection.py pipeline (two wrappers compound scaling_bbox)
- Consider transforming palm_croppers to work in scaling_bbox-aware space for robustness

## Removed Files (non-functional)
- gesture_detection.py / gesture_detection_pipeline.py — hailo10h C++ SO pipeline (broken)
- gesture_detection_blaze.py / gesture_detection_blaze_pipeline.py — C++ blaze pipeline (abandoned)
- test_hand_landmark_pipeline.py, test_blaze_on_photos.py — test scripts
