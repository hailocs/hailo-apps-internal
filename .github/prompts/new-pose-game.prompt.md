````markdown
# Prompt: Create Pose Estimation Game

> Template for building interactive games using pose estimation on Hailo.

## Instructions for Agent

You are building a **pose estimation game** — an interactive GStreamer pipeline app that uses body keypoints for gameplay mechanics.

### Required Context (Read These First)
1. `.github/skills/hl-build-pipeline-app/SKILL.md` — Pipeline app skill (includes Frame Overlay, Detection Data Extraction, Reusing Pipeline Classes sections)
2. `.github/toolsets/pose-keypoints.md` — COCO keypoint indices, skeleton connections, coordinate transform
3. `.github/toolsets/core-framework-api.md` — Framework API (buffer_utils, get_pipeline_parser)
4. `.github/memory/common_pitfalls.md` — RGB→BGR for set_frame(), OpenCV patterns

### Architecture

```
┌──────────────────────────────────────────────────────────────┐
│ GStreamerPoseEstimationApp (inherited pipeline)               │
│   SOURCE → INFERENCE → TRACKER → USER_CALLBACK → DISPLAY     │
│                                       │                       │
│                              app_callback()                   │
│                              ┌────────┴────────┐              │
│                              │ 1. Extract poses │              │
│                              │ 2. Game logic    │              │
│                              │ 3. Draw overlay  │              │
│                              │ 4. set_frame()   │              │
│                              └─────────────────┘              │
└──────────────────────────────────────────────────────────────┘
```

### Build Steps

1. **Subclass `GStreamerPoseEstimationApp`** — inherits full pose pipeline (no pipeline config needed)
2. **Create `app_callback_class` subclass** — holds game state (score, objects, timers)
3. **Write `app_callback`**:
   a. Get frame: `get_caps_from_pad()` + `get_numpy_from_buffer(buffer, format, width, height)`
   b. Get detections: `hailo.get_roi_from_buffer(buffer)` → `roi.get_objects_typed(hailo.HAILO_DETECTION)`
   c. Get keypoints: `detection.get_objects_typed(hailo.HAILO_LANDMARKS)` → `landmarks[0].get_points()`
   d. Convert coordinates: `pixel_x = int((point.x() * bbox.width() + bbox.xmin()) * width)`
   e. Run game logic (collision detection, scoring, spawning)
   f. Draw with OpenCV on the RGB frame
   g. Convert: `cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)` → `user_data.set_frame(frame)`
4. **Add `app.yaml`** with `type: pipeline`
5. **Add `run.sh`** wrapper
6. **Validate** with `python3 .github/scripts/validate_app.py <dir> --smoke-test`

### Key Imports

```python
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst
import cv2
import numpy as np
import hailo

from hailo_apps.python.pipeline_apps.pose_estimation.pose_estimation_pipeline import (
    GStreamerPoseEstimationApp,
)
from hailo_apps.python.core.common.buffer_utils import get_caps_from_pad, get_numpy_from_buffer
from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.gstreamer.gstreamer_app import app_callback_class
```

### Game State Pattern

```python
class GameCallback(app_callback_class):
    def __init__(self):
        super().__init__()
        self.use_frame = True  # MUST be True for overlay drawing
        self.score = 0
        self.game_objects = []  # Falling items, targets, etc.
        self.last_update = time.time()
        self.player_positions = {}  # track_id → {keypoint: (x, y)}
```

### Collision Detection Pattern

```python
def check_collision(hand_x, hand_y, obj_x, obj_y, radius=30):
    distance = ((hand_x - obj_x) ** 2 + (hand_y - obj_y) ** 2) ** 0.5
    return distance < radius
```

### Customization Variables

| Variable | Description |
|---|---|
| `{app_name}` | Game directory name (e.g., `snowflake_catch`) |
| `{game_mechanic}` | catch, dodge, hit, balance, dance |
| `{keypoints_used}` | wrists, ankles, nose, full body |
| `{visual_theme}` | winter, space, underwater, retro |
| `{scoring_rule}` | point per catch, time survived, accuracy |
````
