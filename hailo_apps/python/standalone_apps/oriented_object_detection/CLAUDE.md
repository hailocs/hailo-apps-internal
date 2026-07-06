# Oriented Object Detection

## What This App Does
Detects objects with rotated bounding boxes using YOLO11 OBB (Oriented Bounding Box) on Hailo AI accelerators. Unlike standard detection which uses axis-aligned boxes, this app outputs rotated rectangles that tightly fit objects at arbitrary angles. This is ideal for aerial/satellite imagery, document analysis, and any scenario with rotated objects. The app uses DOTA dataset labels (15 classes including plane, ship, harbor, bridge, etc.) by default.

## Architecture
- **Type:** Standalone app
- **Inference:** HailoAsyncInference (async queue-based via `HailoInfer`, UINT8 input, FLOAT32 output)
- **Models:** yolo11s_obb (default for all architectures)
- **Hardware:** hailo8, hailo8l, hailo10h
- **Post-processing:** CPU-side native Python implementation of YOLO11 OBB postprocessing: DFL box decoding, sigmoid class scores, angle decoding (sigmoid to radians), rotated NMS using `cv2.rotatedRectangleIntersection`

## Key Files
| File | Purpose |
|------|---------|
| `oriented_object_detection.py` | Main script: CLI parsing, letterbox preprocessing, 3-thread pipeline |
| `oriented_object_detection_post_process.py` | Full OBB postprocessing: DFL decoding, anchor grid generation, rotated box extraction, rotated NMS, visualization with `cv2.polylines` |
| `config.json` | Model output tensor mapping, thresholds, and visualization parameters |

## How It Works
1. Parse CLI args and resolve HEF model path; load config.json for tensor mapping
2. Custom letterbox preprocessing with (114,114,114) padding
3. Spawn 3 threads: preprocess (with custom callback), infer, visualize
4. Post-processing groups model outputs by head type (cv2=bbox, cv3=class, cv4=angle) across 3 scales
5. DFL softmax decoding produces box coordinates; sigmoid + radian conversion for angles
6. Anchor grids generated for strides 8/16/32; boxes decoded to pixel coordinates with rotation
7. Rotated NMS filters overlapping detections using polygon intersection IoU
8. Rotated bounding boxes drawn with `cv2.polylines` and class labels

## Common Use Cases
- Aerial and satellite image analysis (vehicles, buildings, ships)
- Document layout analysis with rotated text regions
- Industrial inspection of rotated parts
- Any detection task where objects appear at arbitrary orientations

## How to Extend
- Custom labels: use `--labels <path>` for non-DOTA datasets
- Adjust thresholds: modify `scores_th` and `nms_iou_th` in `config.json`
- Change model: would require updating `obb_model_input_map` in config.json to match new model's output tensor names
- Add tracking: integrate BYTETracker (basic support exists in post-processing code)

## Related Apps
| App | When to use instead |
|-----|-------------------|
| `object_detection` | Objects are upright and axis-aligned boxes are sufficient |
| `tiling` (pipeline app) | Need to detect small objects in very high-resolution images |
| `instance_segmentation` | Need pixel-level masks rather than rotated boxes |
