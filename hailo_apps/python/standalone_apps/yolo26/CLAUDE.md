# YOLO26 — Split HEF + ONNX Postprocessing

## What This App Does
Two standalone example apps built on the 2026 Ultralytics YOLO26 release of NMS-free networks, using a split pipeline: the "neural" part runs as a HEF on the Hailo device, and the "postprocessing" part runs on the host via onnxruntime. This makes integrating new networks convenient — split the ONNX, compile the first half to a HEF, and apply the second half at runtime. Covers **object detection** (with optional ByteTrack tracking) and **pose estimation** (with skeleton-trail and Ultralytics AI-Gym rep-counting demos).

## Architecture
- **Type:** Standalone app (HailoRT inference + OpenCV), two sub-apps
- **Pattern:** Input → HEF (neural part) on device → ONNX postprocessing (DFL / decode) on host via onnxruntime → draw
- **Models:** Object detection: YOLO26 (e.g. `yolov26n`); Pose: `yolov26n_pose` / `yolov26s_pose` / `yolov26m_pose`. Model name auto-resolves/downloads the correct HEF; sidecar postprocess ONNX is lazy-downloaded alongside the HEF
- **Hardware:** hailo8 (HailoRT 4.23.0), hailo10h (HailoRT 5.3.0)
- **Postprocess:** Host-side ONNX (onnxruntime) — second half of the split ONNX; `--full-onnx`/`--neural-onnx-ref` can bypass the HEF for debugging/benchmarking

## Key Files
| File | Purpose |
|------|---------|
| `object_detection/object_detection_onnx_postproc.py` | Object-detection entry point (`-n` model, `-i` input, `--track`, `--draw-trail`, …) |
| `object_detection/object_detection_utils.py` | Detection drawing, ByteTrack helpers, I/O utilities |
| `object_detection/config.json` | Visualization + tracker parameters (score_thres, max boxes, ByteTrack settings) |
| `object_detection/onnx/` | `extract_postprocessing.py` (ONNX splitter), per-model ONNX configs, `test_hef_vs_onnx.py` |
| `pose_estimation/pose_estimation_onnx_postproc.py` | Pose entry point (`--aigym`, `--pose-trail`, `--mute-background`, `--neural-onnx-ref`, …) |
| `pose_estimation/pose_estimation_utils.py` | Keypoint drawing, skeleton/joint rendering |
| `pose_estimation/aigym.py` | Ultralytics AI-Gym integration — angle-based exercise rep counting |
| `pose_estimation/onnx/` | Per-model pose ONNX postprocess configs |

## How to Run
```bash
source setup_env.sh
# Object detection on a USB camera with tracking:
cd hailo_apps/python/standalone_apps/yolo26/object_detection
./object_detection_onnx_postproc.py -i usb --track
# or with an explicit model:
./object_detection_onnx_postproc.py -n yolov26n -i bus.jpg

# Pose estimation with a fading skeleton trail:
cd hailo_apps/python/standalone_apps/yolo26/pose_estimation
./pose_estimation_onnx_postproc.py -i usb --hef yolo26m_pose --pose-trail 10
# AI-Gym squat rep counting:
./pose_estimation_onnx_postproc.py -i grok-squats.mp4 --hef yolo26m_pose --aigym squats
```
Common flags: `-n/--hef-path` (model name or HEF path), `-i/--input` (image/video/dir/`usb`/`rpi`), `--save-output`, `--show-fps`, `--no-display`, `--list-models`. See each sub-app README for the full list.

## How to Extend
- **New network:** Use `onnx/extract_postprocessing.py` to split a YOLO26 ONNX into neural + postprocess parts, compile the neural part to a HEF (DFC), and drop the postprocess ONNX alongside it — no app code changes needed.
- **Debug / benchmark:** Use `--full-onnx` (detection) or `--neural-onnx-ref <path>` (pose) to bypass the HEF and run the reference neural ONNX on the host, isolating pipeline vs. compilation/degradation issues.
- **Tune visualization/tracking:** Edit `object_detection/config.json` (`score_thres`, `max_boxes_to_draw`, ByteTrack `track_thresh`/`track_buffer`/`match_thresh`, …).
