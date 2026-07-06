# Face Landmarks Detection

## What This App Does
Real-time 468-point face mesh landmark detection. Detects faces with SCRFD, then crops each face and runs a face-landmarks model for the detailed MediaPipe 3D mesh. Two pipeline modes: a GStreamer cascade (all inference on Hailo, CPU only draws) or a Python `InferVStreams` callback mode.

## Architecture
- **Type:** Pipeline app (cascaded multi-model)
- **Pattern:** Detection → tracker → crop → landmark inference → callback → display
- **Models:** SCRFD face detection (scrfd_10g; scrfd_2.5g on hailo8l) + `face_landmarks_lite` (468-point mesh, 192×192)
- **Hardware:** hailo8, hailo8l (scrfd_2.5g), hailo10h
- **Postprocess:** C++ `face_landmarks_postprocess.so` (+ optional align `.so`) for GStreamer mode; Python drawing in the callback

## Key Files
| File | Purpose |
|------|---------|
| `face_landmarks.py` | Entry point + callback for GStreamer cascade mode (extracts landmarks, draws color-coded mesh zones) |
| `face_landmarks_pipeline.py` | `GStreamerApp` subclass with two modes (`gstreamer` cascade; `python` InferVStreams) |
| `face_landmarks_standalone.py` | Standalone inference example (no GStreamer) |
| `hailo_scrfd.py` | SCRFD detection utilities |
| `postprocess/` | C++ postprocess source — build with `./build.sh` before GStreamer mode |

## How to Run
```bash
source setup_env.sh
python -m community.apps.pipeline_apps.face_landmarks.face_landmarks --input usb
# or: bash community/apps/pipeline_apps/face_landmarks/run.sh --input usb
```
Optional: `--pipeline-mode gstreamer|python`, `--show-fps`. GStreamer mode requires building the postprocess first: `cd postprocess && ./build.sh`.

## How to Extend
- Add a downstream submodel on the landmarks (eye-gaze, age/gender) or export landmarks to JSON for AR/animation.
- Switch `--pipeline-mode python` when you need flexible per-frame logic instead of the all-on-device cascade.
