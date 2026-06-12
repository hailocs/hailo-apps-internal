# Pose Estimation

## What This App Does
Performs human pose estimation on images, video files, or camera streams using YOLOv8-pose models on Hailo AI accelerators. For each detected person, the app draws a bounding box, confidence score, 17 body keypoints (COCO format), and skeleton connections between joints. The app handles multi-scale detection with DFL (Distribution Focal Loss) decoding and NMS entirely on the CPU side.

## Architecture
- **Type:** Standalone app
- **Inference:** HailoAsyncInference (async queue-based via `HailoInfer`, FLOAT32 output)
- **Models:** yolov8m_pose (hailo8/hailo10h default), yolov8s_pose (hailo8l default)
- **Hardware:** hailo8, hailo8l, hailo10h
- **Post-processing:** CPU-side multi-scale decoding (strides 8/16/32), DFL box regression, softmax, NMS, keypoint coordinate mapping back to original image space

## Key Files
| File | Purpose |
|------|---------|
| `pose_estimation.py` | Main script: CLI parsing, 3-thread pipeline (preprocess, infer, visualize) |
| `pose_estimation_utils.py` | `PoseEstPostProcessing` class: DFL decoding, NMS, keypoint extraction, skeleton drawing with 16 joint pairs |

## How It Works
1. Parse CLI args (including `--class-num` for custom models) and resolve HEF path
2. Initialize input source and create 3-thread pipeline
3. Model outputs 9 tensors at 3 scales (20x20, 40x40, 80x80): box regression, class scores, and keypoints
4. Post-processing decodes boxes using DFL softmax over regression bins, extracts keypoints
5. NMS filters overlapping detections; coordinates mapped from model space back to original image space (accounting for letterbox padding)
6. Visualization draws bounding boxes, keypoint dots, and skeleton lines (16 joint pairs)

## Common Use Cases
- Human activity recognition and motion analysis
- Fitness or sports pose tracking
- People counting with pose awareness
- Gesture-based interaction prototyping

## How to Extend
- Swap model: use `--hef-path yolov8s_pose` for lighter model
- Custom class count: use `--class-num` for models trained on different datasets
- Adjust thresholds: modify `score_threshold`, `nms_iou_thresh`, `detection_threshold`, `joint_threshold` in the code
- Add tracking: integrate BYTETracker similar to the object_detection app

## Related Apps
| App | When to use instead |
|-----|-------------------|
| `object_detection` | Only need person bounding boxes without keypoints |
| `gesture_detection` (pipeline app) | Need hand gesture recognition specifically |
| `pose_estimation` (pipeline app) | Need GStreamer pipeline with RTSP or overlay elements |
