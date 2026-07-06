# Lane Detection

## What This App Does
Detects lane markings in driving video using the UFLDv2 (Ultra Fast Lane Detection v2) model on Hailo accelerators. The app processes an input video, identifies up to 4 lane lines (2 row-based center lanes and 2 column-based edge lanes), and outputs an annotated video with green dots marking the detected lane coordinates. This app is currently in beta.

## Architecture
- **Type:** Standalone app
- **Inference:** HailoAsyncInference (async queue-based via `HailoInfer`, FLOAT32 output)
- **Models:** ufld_v2_tu (hailo8 and hailo10h only; not available on hailo8l)
- **Hardware:** hailo8, hailo10h
- **Post-processing:** CPU-side UFLDv2 decoding with softmax, grid-based lane coordinate extraction, video output with ffmpeg H.264 conversion

## Key Files
| File | Purpose |
|------|---------|
| `lane_detection.py` | Main script: video I/O, 3-thread pipeline, CLI argument parsing |
| `lane_detection_utils.py` | `UFLDProcessing` class: resize/crop preprocessing, softmax, coordinate extraction from model output tensors |

## How It Works
1. Parse CLI args and resolve HEF model path
2. Read input video metadata (width, height, frame count)
3. Initialize `UFLDProcessing` with grid parameters (100x100 cells, 56 rows, 41 columns, 4 lanes, 0.8 crop ratio)
4. Spawn 3 threads: preprocess (resize + crop to model input), infer (async Hailo), postprocess (decode lanes + write video)
5. Post-processing slices the output tensor into row/column localization and existence arrays
6. Softmax-weighted coordinate decoding produces lane point coordinates
7. Lane points drawn as green circles on frames; output video saved with optional H.264 conversion

## Common Use Cases
- Lane departure warning prototyping
- Driving video annotation for ADAS development
- Lane detection accuracy evaluation on custom driving videos

## How to Extend
- Swap model: currently only ufld_v2_tu is supported
- Adjust lane parameters: modify `num_lanes`, `crop_ratio`, grid dimensions in the main script
- Change visualization: modify circle radius or color in `postprocess_output`
- Process camera input: would require modifications to the video-only pipeline

## Related Apps
| App | When to use instead |
|-----|-------------------|
| `object_detection` | Need to detect vehicles/pedestrians rather than lane markings |
| `pose_estimation` | Need human body keypoint detection |
