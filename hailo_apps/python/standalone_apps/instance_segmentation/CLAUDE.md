# Instance Segmentation

## What This App Does
Performs instance segmentation on images, video files, or camera streams using Hailo AI accelerators. For each detected object, the app draws a segmentation mask overlay, bounding box, class label, and confidence score. It supports YOLOv5-seg, YOLOv8-seg, and FastSAM model architectures, with optional BYTETracker-based object tracking across frames.

## Architecture
- **Type:** Standalone app
- **Inference:** HailoAsyncInference (async queue-based via `HailoInfer`, FLOAT32 output)
- **Models:** yolov5m_seg (hailo8/hailo10h default), yolov5n_seg (hailo8l default); extras include yolov5*_seg, yolov8*_seg, yolov5m_seg_with_nms, fast_sam_s
- **Hardware:** hailo8, hailo8l, hailo10h
- **Post-processing:** CPU-side mask refinement, NMS, segmentation overlay blending; models with built-in NMS (e.g., yolov5m_seg_with_nms) achieve significantly higher FPS

## Key Files
| File | Purpose |
|------|---------|
| `instance_segmentation.py` | Main script: CLI parsing, 3-thread pipeline, model-type selection |
| `post_process/postprocessing.py` | Post-processing: segmentation mask generation, box drawing, tracking |

## How It Works
1. Parse CLI args including `--model-type` (v5, v8, or fast) and resolve HEF path
2. Initialize input source and create 3-thread pipeline (preprocess, infer, visualize)
3. Model outputs are decoded according to architecture type (v5/v8/fast)
4. Post-processing generates per-instance segmentation masks and overlays them on the original frame
5. If tracking enabled, BYTETracker assigns persistent IDs across frames
6. Results displayed and/or saved to output directory

## Common Use Cases
- Per-object segmentation for scene understanding
- Distinguishing overlapping objects of the same class
- Video analytics with instance-level tracking
- Comparing model architectures (v5 vs v8 vs FastSAM) for specific use cases

## How to Extend
- Swap model: use `--hef-path <model_name>` with matching `--model-type` (v5/v8/fast)
- Adjust mask visualization: modify `mask_thresh` and `mask_alpha` in `config.json`
- Custom labels: provide `--labels <path>` for non-COCO models
- Add tracking: use `--track` flag for BYTETracker integration

## Related Apps
| App | When to use instead |
|-----|-------------------|
| `object_detection` | Only need bounding boxes without segmentation masks |
| `instance_segmentation` (pipeline app) | Need GStreamer pipeline with RTSP or overlay elements |
| `pose_estimation` | Need human body keypoint detection instead of masks |
