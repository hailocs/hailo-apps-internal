# Pose Estimation

## What This App Does
Real-time human pose estimation that detects people and their body keypoints (joints) using YOLOv8 pose models. The pipeline wraps inference in a resolution-preserving cropper, adds tracking to maintain consistent person IDs across frames, and overlays skeleton visualizations on the video. The callback demonstrates accessing 17 COCO keypoints (nose, eyes, ears, shoulders, elbows, wrists, hips, knees, ankles) with their coordinates.

This is useful for human activity recognition, exercise form analysis, gesture-based interfaces, and any application requiring body pose understanding.

## Architecture
- **Type:** Pipeline app
- **Pattern:** source -> inference_wrapper -> tracker -> callback -> display
- **Models:**
  - hailo8: `yolov8m_pose` (default), extra: yolov8s_pose
  - hailo8l: `yolov8s_pose` (default)
  - hailo10h: `yolov8m_pose` (default), extra: yolov8s_pose
- **Hardware:** hailo8, hailo8l, hailo10h
- **Postprocess:** TAPPAS pose estimation postprocess .so (resolved via `POSE_ESTIMATION_POSTPROCESS_SO_FILENAME`)

## Key Files
| File | Purpose |
|------|---------|
| `pose_estimation.py` | Main entry point, callback accessing landmarks and drawing eye positions |
| `pose_estimation_pipeline.py` | `GStreamerPoseEstimationApp` subclass, pipeline definition |

## Pipeline Structure
```
SOURCE_PIPELINE
  -> INFERENCE_PIPELINE_WRAPPER(INFERENCE_PIPELINE)  # preserves original resolution
    -> TRACKER_PIPELINE(class_id=0)                  # tracks class 0
      -> USER_CALLBACK_PIPELINE
        -> DISPLAY_PIPELINE
```

Key parameters:
- `batch_size=2`
- Tracker tracks `class_id=0`

## Callback Data Available
```python
roi = hailo.get_roi_from_buffer(buffer)
detections = roi.get_objects_typed(hailo.HAILO_DETECTION)
for detection in detections:
    label = detection.get_label()           # "person"
    bbox = detection.get_bbox()             # HailoBBox
    confidence = detection.get_confidence()
    track = detection.get_objects_typed(hailo.HAILO_UNIQUE_ID)
    track_id = track[0].get_id() if len(track) == 1 else 0

    landmarks = detection.get_objects_typed(hailo.HAILO_LANDMARKS)
    if landmarks:
        points = landmarks[0].get_points()
        # 17 keypoints: nose(0), left_eye(1), right_eye(2), left_ear(3), right_ear(4),
        # left_shoulder(5), right_shoulder(6), left_elbow(7), right_elbow(8),
        # left_wrist(9), right_wrist(10), left_hip(11), right_hip(12),
        # left_knee(13), right_knee(14), left_ankle(15), right_ankle(16)
        point = points[keypoint_index]
        x = int((point.x() * bbox.width() + bbox.xmin()) * width)
        y = int((point.y() * bbox.height() + bbox.ymin()) * height)
```

Landmark coordinates are normalized relative to the detection bounding box. To get pixel coordinates, scale by bbox dimensions and offset, then multiply by frame dimensions.

## Common Use Cases
- Exercise form analysis and fitness tracking
- Fall detection for elderly care
- Human-computer interaction via body gestures
- Sports analytics and motion capture
- Occupational safety (posture monitoring)

## How to Extend
- **Swap models:** Use `--hef-path <path>` or `--list-models`; yolov8s_pose is faster, yolov8m_pose is more accurate
- **Access all keypoints:** Use the `get_keypoints()` dictionary in `pose_estimation.py` for named access
- **Compute angles:** Calculate joint angles from keypoint pairs for activity recognition
- **Remove tracking:** Remove `TRACKER_PIPELINE` from `get_pipeline_string()` if persistent IDs aren't needed
- **Change input:** `--input /dev/video0` for webcam, `--input rtsp://...` for network stream

## Related Apps
| App | When to use instead |
|-----|-------------------|
| detection | If you only need bounding boxes without body keypoints |
| gesture_detection | If you need hand gesture recognition (palm + hand landmarks) |
| instance_segmentation | If you need per-pixel body segmentation masks |
