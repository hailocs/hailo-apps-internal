# Semaphore Flag Translator

Real-time semaphore flag signal translation using body pose estimation. The app detects a person, extracts arm keypoints (shoulders, elbows, wrists) from YOLOv8-pose output, computes arm angles, and maps them to semaphore flag alphabet letters. Letters are accumulated into words with a stabilization mechanism to avoid jitter.

## Prerequisites

- Hailo-8, Hailo-8L, or Hailo-10H accelerator
- YOLOv8 pose model (uses the same model as `pose_estimation`)
- Compiled postprocess plugins (`hailo-compile-postprocess`)

## How to Run

```bash
# With USB camera
python community/apps/pipeline_apps/semaphore_translator/semaphore_translator.py --input usb

# With video file
python community/apps/pipeline_apps/semaphore_translator/semaphore_translator.py --input path/to/video.mp4

# With frame overlay (draws arm lines and detected letters on video)
python community/apps/pipeline_apps/semaphore_translator/semaphore_translator.py --input usb --use-frame
```

## Architecture

```
USB Camera
    |
    v
SOURCE_PIPELINE (video capture + format conversion)
    |
    v
INFERENCE_PIPELINE_WRAPPER (resolution preservation)
    |-- INFERENCE_PIPELINE (YOLOv8-pose: person detection + 17 keypoints)
    |
    v
TRACKER_PIPELINE (person tracking, class_id=0)
    |
    v
USER_CALLBACK_PIPELINE
    |-- Extract shoulder + wrist keypoints
    |-- Compute arm angles (0-360 degrees)
    |-- Discretize to 45-degree steps
    |-- Look up semaphore alphabet
    |-- Stabilize letter over N frames
    |-- Accumulate letters into word
    |
    v
DISPLAY_PIPELINE (video output with overlay)
```

## Semaphore Decoding Logic

1. **Keypoint extraction:** Shoulders (5,6) and wrists (9,10) from 17 COCO keypoints
2. **Angle computation:** `atan2` from shoulder to wrist, normalized to 0-360 degrees clockwise from straight down
3. **Discretization:** Snap to nearest 45-degree increment (0, 45, 90, 135, 180, 225, 270, 315)
4. **Lookup:** Match (right_arm_angle, left_arm_angle) tuple against semaphore alphabet table
5. **Stabilization:** Same letter must hold for 10 consecutive frames before being accepted
6. **REST signal:** Both arms down (0, 0) resets but does not add a letter

## Customization

- **Adjust sensitivity:** Change `stable_threshold` in `user_app_callback_class` (higher = more stable, slower)
- **Angle tolerance:** Modify `ANGLE_TOLERANCE` constant (default 30 degrees)
- **Add signals:** Extend `SEMAPHORE_ALPHABET` dict with new (right_angle, left_angle) -> letter mappings
- **Clear word:** Currently accumulates indefinitely; add a "cancel" gesture or timeout to reset `decoded_word`
- **Swap model:** Use `--hef-path` or `--list-models` to try yolov8s_pose (faster) vs yolov8m_pose (more accurate)
