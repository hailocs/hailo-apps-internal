````markdown
# Toolset: COCO Pose Keypoints Reference

> 17 COCO keypoints used by pose estimation models (YOLOv8-pose, movenet, etc.)

## Keypoint Index Table

| Index | Name | Body Part |
|---|---|---|
| 0 | nose | Head |
| 1 | left_eye | Head |
| 2 | right_eye | Head |
| 3 | left_ear | Head |
| 4 | right_ear | Head |
| 5 | left_shoulder | Upper Body |
| 6 | right_shoulder | Upper Body |
| 7 | left_elbow | Upper Body |
| 8 | right_elbow | Upper Body |
| 9 | left_wrist | Hands |
| 10 | right_wrist | Hands |
| 11 | left_hip | Lower Body |
| 12 | right_hip | Lower Body |
| 13 | left_knee | Lower Body |
| 14 | right_knee | Lower Body |
| 15 | left_ankle | Feet |
| 16 | right_ankle | Feet |

## Keypoint Dictionary (Python)

```python
KEYPOINTS = {
    "nose": 0,
    "left_eye": 1,
    "right_eye": 2,
    "left_ear": 3,
    "right_ear": 4,
    "left_shoulder": 5,
    "right_shoulder": 6,
    "left_elbow": 7,
    "right_elbow": 8,
    "left_wrist": 9,
    "right_wrist": 10,
    "left_hip": 11,
    "right_hip": 12,
    "left_knee": 13,
    "right_knee": 14,
    "left_ankle": 15,
    "right_ankle": 16,
}
```

## Skeleton Connections (Drawing Lines Between Joints)

```python
SKELETON_CONNECTIONS = [
    # Head
    ("left_ear", "left_eye"),
    ("right_ear", "right_eye"),
    ("left_eye", "nose"),
    ("right_eye", "nose"),
    # Upper body
    ("left_shoulder", "right_shoulder"),
    ("left_shoulder", "left_elbow"),
    ("right_shoulder", "right_elbow"),
    ("left_elbow", "left_wrist"),
    ("right_elbow", "right_wrist"),
    # Torso
    ("left_shoulder", "left_hip"),
    ("right_shoulder", "right_hip"),
    ("left_hip", "right_hip"),
    # Lower body
    ("left_hip", "left_knee"),
    ("right_hip", "right_knee"),
    ("left_knee", "left_ankle"),
    ("right_knee", "right_ankle"),
]
```

## Coordinate Transform: Normalized → Pixel

Landmark points from `hailo.HAILO_LANDMARKS` are **normalized to the bounding box**. To convert to pixel coordinates:

```python
# bbox from detection.get_bbox()
# point from landmarks[0].get_points()[keypoint_index]
# width, height from get_caps_from_pad()

pixel_x = int((point.x() * bbox.width() + bbox.xmin()) * width)
pixel_y = int((point.y() * bbox.height() + bbox.ymin()) * height)
```

**Explanation:**
1. `point.x()` / `point.y()` → normalized within the bounding box [0, 1]
2. Multiply by `bbox.width()` / `bbox.height()` → scale to bbox size
3. Add `bbox.xmin()` / `bbox.ymin()` → offset to bbox position in frame
4. Multiply by frame `width` / `height` → convert to pixel coordinates

## Useful Body Part Groups

```python
# Hands (for gesture/interaction games)
HAND_KEYPOINTS = [9, 10]  # left_wrist, right_wrist

# Head (for head tracking)
HEAD_KEYPOINTS = [0, 1, 2, 3, 4]  # nose, eyes, ears

# Feet (for step/dance games)
FEET_KEYPOINTS = [15, 16]  # left_ankle, right_ankle

# Full arms (for arm movement tracking)
LEFT_ARM = [5, 7, 9]   # shoulder, elbow, wrist
RIGHT_ARM = [6, 8, 10]  # shoulder, elbow, wrist

# Full legs (for running/kick detection)
LEFT_LEG = [11, 13, 15]   # hip, knee, ankle
RIGHT_LEG = [12, 14, 16]  # hip, knee, ankle
```

## Complete Extraction Pattern

```python
import hailo
from hailo_apps.python.core.common.buffer_utils import get_caps_from_pad, get_numpy_from_buffer

def app_callback(element, buffer, user_data):
    pad = element.get_static_pad("src")
    format, width, height = get_caps_from_pad(pad)

    frame = None
    if user_data.use_frame and format and width and height:
        frame = get_numpy_from_buffer(buffer, format, width, height)

    roi = hailo.get_roi_from_buffer(buffer)
    detections = roi.get_objects_typed(hailo.HAILO_DETECTION)

    for detection in detections:
        if detection.get_label() != "person":
            continue

        bbox = detection.get_bbox()

        # Get track ID
        track_id = 0
        track = detection.get_objects_typed(hailo.HAILO_UNIQUE_ID)
        if len(track) == 1:
            track_id = track[0].get_id()

        # Get pose landmarks
        landmarks = detection.get_objects_typed(hailo.HAILO_LANDMARKS)
        if not landmarks:
            continue

        points = landmarks[0].get_points()

        # Extract specific keypoints
        left_wrist = points[9]
        right_wrist = points[10]

        # Convert to pixel coordinates
        lw_x = int((left_wrist.x() * bbox.width() + bbox.xmin()) * width)
        lw_y = int((left_wrist.y() * bbox.height() + bbox.ymin()) * height)
        rw_x = int((right_wrist.x() * bbox.width() + bbox.xmin()) * width)
        rw_y = int((right_wrist.y() * bbox.height() + bbox.ymin()) * height)

        # Draw on frame
        if frame is not None:
            cv2.circle(frame, (lw_x, lw_y), 10, (0, 255, 0), -1)
            cv2.circle(frame, (rw_x, rw_y), 10, (0, 0, 255), -1)

    if user_data.use_frame and frame is not None:
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        user_data.set_frame(frame)

    return Gst.FlowReturn.OK
```
````
