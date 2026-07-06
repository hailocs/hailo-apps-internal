# Gesture-Controlled Mouse

## What This App Does
Controls the computer mouse with hand gestures. Tracks the palm center (wrist + 4 MCP joints) from MediaPipe hand landmarks to move the cursor (with exponential smoothing); a pinch gesture triggers clicks and drags via `pynput`.

## Architecture
- **Type:** Pipeline app (cascaded multi-model)
- **Pattern:** Palm detection → hand cropper → hand landmark → gesture classification → Python callback for mouse control
- **Models:** `palm_detection_lite.hef` (192×192) + `hand_landmark_lite.hef` (224×224) — MediaPipe Blaze
- **Hardware:** hailo8, hailo8l, hailo10h
- **Postprocess:** C++ `.so` filters (palm detect, croppers, affine warp, hand landmark, gesture classification)

## Key Files
| File | Purpose |
|------|---------|
| `gesture_mouse.py` | Entry point + callback: maps landmarks to cursor position, handles click/drag via `pynput` |
| `gesture_mouse_pipeline.py` | `GStreamerApp` subclass: builds the full C++ palm → hand → gesture pipeline |

## How to Run
```bash
source setup_env.sh
python community/apps/pipeline_apps/gesture_mouse/gesture_mouse.py --input usb
```
Optional: `--smoothing 0.4`, `--speed 1.5`, `--pinch-threshold 0.06`.

## How to Extend
- Add right-click by detecting a distinct pinch (e.g. middle-finger) or a held gesture state.
- Add zone-based actions: map screen regions to app-specific commands triggered by gestures.
