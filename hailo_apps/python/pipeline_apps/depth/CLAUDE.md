# Depth Estimation

## What This App Does
Monocular depth estimation that produces a per-pixel depth map from a single camera view using the SCDepthV3 model. The pipeline wraps inference in a resolution-preserving cropper and outputs a depth mask that the overlay element renders as a color-mapped depth visualization. The callback demonstrates accessing the depth data and computing average depth statistics.

This enables distance-aware applications using a standard camera -- no stereo camera or LiDAR required.

## Architecture
- **Type:** Pipeline app
- **Pattern:** source -> inference_wrapper -> callback -> display (no tracker)
- **Models:**
  - hailo8: `scdepthv3` (default)
  - hailo8l: `scdepthv3` (default)
  - hailo10h: `scdepthv3` (default)
- **Hardware:** hailo8, hailo8l, hailo10h
- **Postprocess:** TAPPAS depth postprocess .so (resolved via `DEPTH_POSTPROCESS_SO_FILENAME`)

## Key Files
| File | Purpose |
|------|---------|
| `depth.py` | Main entry point, callback computing average depth from depth mask |
| `depth_pipeline.py` | `GStreamerDepthApp` subclass, pipeline definition |

## Pipeline Structure
```
SOURCE_PIPELINE
  -> INFERENCE_PIPELINE_WRAPPER(INFERENCE_PIPELINE, name="inference_wrapper_depth")
    -> USER_CALLBACK_PIPELINE
      -> DISPLAY_PIPELINE
```

Key parameters:
- No tracker (depth estimation doesn't produce detections)
- Inference pipeline named `depth_inference`
- Wrapper named `inference_wrapper_depth`

## Callback Data Available
```python
roi = hailo.get_roi_from_buffer(buffer)
depth_mat = roi.get_objects_typed(hailo.HAILO_DEPTH_MASK)
if len(depth_mat) > 0:
    depth_data = depth_mat[0].get_data()  # raw depth values
    # Compute statistics:
    depth_values = np.array(depth_data).flatten()
    m_depth_values = depth_values[depth_values <= np.percentile(depth_values, 95)]
    average_depth = np.mean(m_depth_values)
```

The depth mask provides relative depth values (not absolute meters). Higher values = farther away.

## Common Use Cases
- Obstacle avoidance for robots and drones
- Relative distance estimation in video scenes
- Depth-aware photo effects (bokeh, refocusing)
- Scene structure understanding
- Navigation assistance for visually impaired

## How to Extend
- **Depth-based alerting:** Threshold depth values to detect objects within a certain range
- **Region-of-interest depth:** Crop the depth map to specific areas for targeted depth analysis
- **Combine with detection:** Add a detection stage before depth to get per-object depth estimates
- **Change input:** `--input /dev/video0` for live camera, `--input walk_in_room.mp4` for demo video
- **Swap models:** Use `--hef-path <path>` or `--list-models`

## Related Apps
| App | When to use instead |
|-----|-------------------|
| detection | If you need object bounding boxes instead of depth maps |
| instance_segmentation | If you need per-object pixel masks rather than depth |
| pose_estimation | If you need 3D body joint positions |
