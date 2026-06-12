# PPE Safety Checker

Real-time PPE (Personal Protective Equipment) compliance checking using CLIP zero-shot classification on Hailo-8. The app detects workers in the video feed using YOLOv8, then classifies each person using CLIP to determine whether they are wearing the required safety equipment (hard hat, safety vest, goggles) without any model retraining.

## Prerequisites

- **Hardware:** Hailo-8 (also supports Hailo-8L and Hailo-10H)
- **Models:** CLIP image encoder, CLIP text encoder, YOLOv8 4-class detection (auto-downloaded via `hailo-download-resources`)
- **Postprocess plugins:** `libyolo_hailortpp_postprocess.so`, `libclip_postprocess.so`, `libclip_croppers_postprocess.so` (compiled via `hailo-compile-postprocess`)
- **Python deps:** Standard hailo-apps-infra environment (`source setup_env.sh`)

## How to Run

```bash
# Activate environment
source setup_env.sh

# Run with USB camera (default)
python community/apps/pipeline_apps/ppe_safety_checker/ppe_safety_checker.py --input usb

# Run with a video file
python community/apps/pipeline_apps/ppe_safety_checker/ppe_safety_checker.py --input path/to/construction_site.mp4

# Adjust detection and CLIP thresholds
python community/apps/pipeline_apps/ppe_safety_checker/ppe_safety_checker.py --input usb --detection-threshold 0.6 --clip-threshold 0.35

# Custom PPE prompts (first 3 = safe, next 3 = violation)
python community/apps/pipeline_apps/ppe_safety_checker/ppe_safety_checker.py --input usb \
    --prompts "person wearing hard hat and vest" "person with helmet" "person with safety gear" \
              "person without helmet" "person without vest" "person without safety gear"
```

## Architecture

```
USB Camera
  |
  v
SOURCE_PIPELINE
  |
  v
INFERENCE_PIPELINE_WRAPPER (YOLOv8 person detection)
  |
  v
TRACKER_PIPELINE (class_id=1, track persons)
  |
  v
CROPPER_PIPELINE (crop each detected person)
  |   |
  |   v
  |   CLIP INFERENCE_PIPELINE (classify person crop)
  |   |
  v   v
HAILOAGGREGATOR (merge results)
  |
  v
PPE Matching Callback (compare CLIP embeddings to PPE prompts)
  |
  v
User Callback (log compliance status, update counters)
  |
  v
DISPLAY_PIPELINE (show video with color-coded bounding boxes)
```

## How It Works

1. **Person Detection:** YOLOv8 detects all people in the frame
2. **Tracking:** HailoTracker assigns persistent IDs to each person
3. **CLIP Classification:** Each person crop is passed through the CLIP image encoder
4. **PPE Matching:** CLIP embeddings are compared against text prompts describing safe/unsafe PPE states
5. **Status Display:** Bounding boxes are labeled with compliance status (SAFE/VIOLATION)

## Customization

- **Prompts:** Override default prompts via `--prompts` CLI argument or modify `DEFAULT_PPE_PROMPTS` in the pipeline file
- **Thresholds:** Tune `--detection-threshold` (person detection confidence) and `--clip-threshold` (CLIP matching threshold)
- **Safe/Violation mapping:** Adjust `SAFE_PROMPT_INDICES` and `VIOLATION_PROMPT_INDICES` in the pipeline file to change which prompts map to which status

## Based On

This app is built from the **CLIP** template app (`community/apps/pipeline_apps/clip/`), simplified to remove the GTK GUI and hardcoded for person detection with PPE-specific text prompts.
