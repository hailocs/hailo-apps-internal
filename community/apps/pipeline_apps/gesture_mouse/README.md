# Gesture Mouse

Control your computer mouse with hand gestures using Hailo-8 accelerated hand tracking.

Uses the MediaPipe Blaze palm detection + hand landmark models running on Hailo to track your index fingertip and map it to cursor position. Pinch your thumb and index finger together to click.

**Supported hardware:** Hailo-8, Hailo-8L, Hailo-10H (architecture auto-detected; correct models downloaded automatically)

## Prerequisites

- Hailo-8, Hailo-8L, or Hailo-10H
- Gesture detection models (auto-downloaded on first run, or manually: `python -m community.apps.pipeline_apps.gesture_detection.download_models`)
- C++ postprocess plugins compiled (`hailo-compile-postprocess`)
- `pynput` installed (`pip install pynput`)
- Optional: `screeninfo` for auto screen size detection (`pip install screeninfo`)

## Usage

```bash
# Basic usage with USB camera
python community/apps/pipeline_apps/gesture_mouse/gesture_mouse.py --input usb

# Adjust cursor speed and smoothing
python community/apps/pipeline_apps/gesture_mouse/gesture_mouse.py --input usb --speed 2.0 --smoothing 0.5

# Cursor movement only (no clicking)
python community/apps/pipeline_apps/gesture_mouse/gesture_mouse.py --input usb --no-click

# From video file (for testing)
python community/apps/pipeline_apps/gesture_mouse/gesture_mouse.py --input path/to/video.mp4
```

## Gesture Controls

| Gesture | Action |
|---------|--------|
| Point / any fingers up | Move cursor (index fingertip tracks position) |
| Pinch (thumb + index close) | Left click |
| Fist while pinching | Start drag (hold left button) |
| Open hand after drag | Release drag |

## Architecture

```
USB Camera
    |
    v
Palm Detection (palm_detection_lite.hef, 192x192)
    |
    v
Palm Cropper -> Hand ROI (affine warp, 224x224)
    |
    v
Hand Landmark (hand_landmark_lite.hef, 21 keypoints)
    |
    v
Gesture Classification (C++)
    |
    v
Python Callback:
  - Extract index fingertip (keypoint 8)
  - Map to screen coordinates (mirrored, speed-scaled)
  - Exponential smoothing for stable cursor
  - Pinch detection (thumb-index distance)
  - pynput mouse control
    |
    v
Display (with overlay showing hand skeleton)
```

All inference and pre/post processing runs in C++ on the Hailo-8 NPU. The Python callback only reads the metadata and controls the mouse — it adds negligible latency.

## CLI Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--smoothing` | 0.4 | Cursor smoothing (0 = none, 1 = max). Higher = smoother but more lag. |
| `--speed` | 1.5 | Cursor speed multiplier. Higher = less hand movement needed. |
| `--pinch-threshold` | 0.06 | Thumb-to-index distance for click trigger (normalized). |
| `--no-click` | false | Disable click/drag — movement only. |
| `--palm-hef` | auto | Path to palm detection model. |
| `--hand-hef` | auto | Path to hand landmark model. |

## Tuning Tips

- **Cursor too jittery**: Increase `--smoothing` (try 0.6-0.8). Tradeoff: more lag.
- **Cursor too slow/fast**: Adjust `--speed`. 1.0 = 1:1 mapping, 2.0 = half the hand movement covers full screen.
- **Accidental clicks**: Increase `--pinch-threshold` (try 0.08-0.10).
- **Can't click**: Decrease `--pinch-threshold` (try 0.04).
- **Best camera position**: Mount camera at eye level, ~50-80cm from hand. Ensure good lighting.

## Customization

- **Add right-click**: Check for a different gesture (e.g., middle finger pinch) in the callback
- **Add scroll**: Map vertical hand movement during a specific gesture to scroll events
- **Zone-based actions**: Define screen zones that trigger specific actions when the cursor enters them
- **Multi-hand**: Track both hands — one for cursor, one for gestures
