# Object Detection

## What This App Does
Performs real-time object detection on images, video files, or camera streams using Hailo AI accelerators. It processes each frame through a YOLO/SSD/CenterNet model with HailoRT postprocessing, draws bounding boxes with class labels and confidence scores, and optionally tracks objects across frames using BYTETracker. Tracking assigns persistent IDs to objects and can visualize motion trails.

## Architecture
- **Type:** Standalone app
- **Inference:** HailoAsyncInference (async queue-based via `HailoInfer`)
- **Models:** yolov8m (hailo8/hailo10h default), yolov8s (hailo8l default); extras include yolov5, yolov6, yolov7, yolov9, yolov10, yolov11 variants
- **Hardware:** hailo8, hailo8l, hailo10h
- **Post-processing:** CPU-side NMS decoding, bounding box denormalization, score thresholding, optional BYTETracker for multi-object tracking with trail visualization

## Key Files
| File | Purpose |
|------|---------|
| `object_detection.py` | Main script: CLI parsing, 3-thread pipeline (preprocess, infer, visualize) |
| `object_detection_post_process.py` | Post-processing: detection extraction, box denormalization, drawing, tracking integration |

## How It Works
1. Parse CLI args and resolve HEF model path (auto-downloads if needed)
2. Initialize input source (camera, video file, or image folder)
3. Spawn three threads: preprocess (resize frames), infer (async Hailo inference), visualize (post-process and display)
4. Post-processing extracts detections from model output, applies score threshold and max-box limit
5. If tracking enabled, BYTETracker assigns persistent IDs across frames; optionally draws motion trails
6. Results displayed via OpenCV window and/or saved to output directory

## Common Use Cases
- Real-time object detection from USB or RPi cameras
- Batch processing of image folders
- Object counting and tracking in video streams
- Prototyping detection pipelines without GStreamer/TAPPAS

## How to Extend
- Swap model: use `--hef-path <model_name>` (e.g., `yolov11m`, `yolov5s`); use `--list-models` to see all options
- Change input source: `--input usb`, `--input /dev/video0`, `--input video.mp4`, or an image folder
- Custom labels: provide `--labels <path_to_labels.txt>` for non-COCO models
- Adjust detection thresholds: edit `config.json` (`score_thres`, `max_boxes_to_draw`, tracker parameters)
- Add custom post-processing: modify `inference_result_handler` in `object_detection_post_process.py`

## Related Apps
| App | When to use instead |
|-----|-------------------|
| `detection` (pipeline app) | Need GStreamer pipeline with RTSP, multi-source, or overlay elements |
| `instance_segmentation` | Need per-object segmentation masks in addition to bounding boxes |
| `oriented_object_detection` | Objects appear at arbitrary angles (aerial/satellite imagery) |
| `tiling` (pipeline app) | Detecting small objects in high-resolution images |
