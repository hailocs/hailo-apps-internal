# Skill: Build GStreamer Pipeline Application

Build a complete GStreamer pipeline app for real-time video processing on Hailo-8/8L/10H.

## When This Skill Is Loaded

- User wants **real-time video processing** (detection, pose, segmentation)
- User mentions: GStreamer, pipeline, stream, FPS, real-time video, tracking
- User needs a video app with **high throughput** rather than AI understanding

## Reference Implementations

The canonical pipeline app is `detection/`. Other examples: `pose_estimation/`, `instance_segmentation/`, `face_recognition/`.

**Do NOT read these source files.** This SKILL.md contains all patterns needed to build any pipeline app. The sections below cover: basic pipelines, frame overlays, custom backgrounds, pose extraction, detection data, and subclassing existing pipeline classes.

### Minimum Context for Any Pipeline App
Read this SKILL.md (full file, single read) + `common_pitfalls.md`. That's it. Build immediately.

## Build Process

### Step 1: Create App Directory

Create the app directory:

```
hailo_apps/python/<type>/<app_name>/
├── app.yaml              # App manifest (required)
├── run.sh                # Launch wrapper
├── __init__.py
├── <app_name>.py         # Main app
└── README.md             # Usage documentation (REQUIRED — never skip)
```

Create `app.yaml` with `type: pipeline` and `run.sh` wrapper.
Do NOT register in `defines.py` or `resources_config.yaml`.

### Step 2: Build Main App

```python
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst

import hailo  # Required for detection/landmark extraction in callbacks

from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.common.core import resolve_hef_path, handle_list_models_flag
from hailo_apps.python.core.common.parser import get_pipeline_parser
# If your app uses resolve_hef_path with an app name, register it in defines.py.
# Otherwise use a local string constant:
# APP_NAME = "my_pipeline_app"
from hailo_apps.python.core.gstreamer.gstreamer_app import GStreamerApp, app_callback_class
from hailo_apps.python.core.gstreamer.gstreamer_helper_pipelines import (
    SOURCE_PIPELINE,
    INFERENCE_PIPELINE,
    INFERENCE_PIPELINE_WRAPPER,
    DISPLAY_PIPELINE,
    TRACKER_PIPELINE,
    USER_CALLBACK_PIPELINE,
    QUEUE,
)
from hailo_apps.python.core.common.buffer_utils import (
    get_caps_from_pad,
    get_numpy_from_buffer,
)

logger = get_logger(__name__)

APP_NAME = "my_pipeline_app"


class UserAppCallback(app_callback_class):
    """Custom callback class for per-frame state."""
    def __init__(self):
        super().__init__()
        self.detection_count = 0


def app_callback(element, buffer, user_data):
    """Per-frame callback — runs on every GStreamer buffer."""
    # Access detections from buffer
    # user_data.detection_count += len(detections)
    return Gst.FlowReturn.OK


class MyPipelineApp(GStreamerApp):
    def __init__(self, app_callback, user_data, parser=None):
        parser = parser or get_pipeline_parser()
        handle_list_models_flag(parser, APP_NAME)
        args = parser.parse_args()
        super().__init__(args, user_data)

        self.hef_path = resolve_hef_path(args.hef_path, APP_NAME, self.arch)
        logger.info("HEF: %s", self.hef_path)

    def get_pipeline_string(self):
        return (
            SOURCE_PIPELINE(self.video_source, self.arch)
            + " ! "
            + INFERENCE_PIPELINE(
                hef_path=self.hef_path,
                batch_size=self.batch_size,
            )
            + " ! "
            + USER_CALLBACK_PIPELINE()
            + " ! "
            + DISPLAY_PIPELINE(video_sink=self.video_sink, sync=self.sync)
        )


def main():
    user_data = UserAppCallback()
    app = MyPipelineApp(app_callback, user_data)
    app.run()


if __name__ == "__main__":
    main()
```

### Step 4: Validate

```bash
python3 .hailo/scripts/validate_app.py hailo_apps/python/pipeline_apps/my_pipeline_app --smoke-test
```

## Critical Conventions

0. **USB camera input**: Always use `--input usb` for USB cameras — the framework auto-detects the correct device. **NEVER** hardcode `/dev/video0` — that is often the integrated webcam, not the USB camera. If you need a specific device, run `v4l2-ctl --list-devices` first.
1. **CLI parser**: `get_pipeline_parser()` (NOT `get_standalone_parser()`)
2. **Pipeline composition**: Use helper functions — `SOURCE_PIPELINE`, `INFERENCE_PIPELINE`, `DISPLAY_PIPELINE`
3. **Callback**: `app_callback(element, buffer, user_data)` — never call `user_data.increment()`
4. **Resolution preservation**: Use `INFERENCE_PIPELINE_WRAPPER` for full-res display
5. **Tracking**: `TRACKER_PIPELINE()` for ByteTrack
6. **Cascaded inference**: `CROPPER_PIPELINE()` for crop → second model
7. **VAAPI**: Add `QUEUE("vaapi_queue") + vaapi_convert_pipeline` for HW decode

## Common Patterns

| Pattern | Helper | Use Case |
|---|---|---|
| Basic inference | `INFERENCE_PIPELINE(hef_path=...)` | Single model |
| With tracking | `+ TRACKER_PIPELINE()` | Object tracking |
| With user callback | `+ USER_CALLBACK_PIPELINE()` | Per-frame processing |
| Cascaded | `CROPPER_PIPELINE(...)` | Face detection → recognition |
| Multi-source | Multiple `SOURCE_PIPELINE` + compositor | Dashboard view |
| Tiling | Custom tiling pipeline | Small object detection |

---

## Frame Overlay Pattern (use_frame + OpenCV Drawing)

When you need to draw on frames (overlays, game graphics, custom visualizations), use the `use_frame` pattern:

### 1. Enable use_frame in your callback class
```python
class UserAppCallback(app_callback_class):
    def __init__(self):
        super().__init__()
        self.use_frame = True  # Enables frame access in callback
```

**CRITICAL**: Setting `use_frame = True` in the callback class alone is NOT enough when subclassing a pipeline class (e.g., `GStreamerPoseEstimationApp`). `GStreamerApp.__init__()` overwrites `user_data.use_frame` from the CLI default (`False`). You MUST also force it in the app class:
```python
class MyApp(GStreamerPoseEstimationApp):
    def __init__(self, app_callback, user_data, parser=None):
        super().__init__(app_callback, user_data, parser)
        self.options_menu.use_frame = True  # starts display process
        user_data.use_frame = True          # enables frame extraction
```
Without this, `set_frame()` calls are silently ignored and only the raw camera feed is shown.

### 2. Get the frame in the callback
```python
import cv2
import hailo
from hailo_apps.python.core.common.buffer_utils import get_caps_from_pad, get_numpy_from_buffer

def app_callback(element, buffer, user_data):
    pad = element.get_static_pad("src")
    format, width, height = get_caps_from_pad(pad)

    frame = None
    if user_data.use_frame and format and width and height:
        # Signature: get_numpy_from_buffer(buffer, format, width, height)
        # Returns RGB numpy array (H, W, 3)
        frame = get_numpy_from_buffer(buffer, format, width, height)
```

### 3. Draw with OpenCV, convert RGB→BGR, then set_frame()
```python
    if user_data.use_frame and frame is not None:
        # Draw on the frame (frame is RGB from GStreamer)
        cv2.circle(frame, (x, y), 10, (0, 255, 0), -1)
        cv2.putText(frame, "Hello", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)

        # CRITICAL: Convert RGB → BGR before set_frame (OpenCV expects BGR)
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        user_data.set_frame(frame)

    return Gst.FlowReturn.OK
```

**Key rules:**
- `get_numpy_from_buffer(buffer, format, width, height)` — NOT `(buffer, pad, format)`
- Frame comes in **RGB** from GStreamer
- Must convert to **BGR** with `cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)` before `set_frame()`
- Always check `user_data.use_frame` and that `frame is not None`
- Pass `--use-frame` on CLI to enable (or set `self.use_frame = True` in callback class)

### Custom Background Pattern (games, virtual scenes)

When the user wants a **custom background image** (not the live camera feed), use `background.copy()` — **never blend** the camera feed with the background via `addWeighted` or similar.

```python
# ✅ CORRECT — background only, no camera feed visible
if self.background is not None:
    output = self.background.copy()
else:
    output = np.zeros_like(frame)

# Draw game elements on output...
# Draw hand/body markers from pose data on output...

output = cv2.cvtColor(output, cv2.COLOR_RGB2BGR)
user_data.set_frame(output)
```

```python
# ❌ WRONG — blends camera feed, user sees themselves + background = confusing
output = cv2.addWeighted(self.background, 0.4, frame, 0.6, 0)
```

**Rule**: If the user provides a background image or asks for a virtual scene, the camera feed is used **only for pose/detection data extraction** — it must NOT appear in the rendered output. The `frame` from `get_numpy_from_buffer()` is still needed to extract detections, but the display output should be `background.copy()` with game elements drawn on top.

---

## Detection Data Extraction in Callbacks

### Getting ROI and Detections
```python
import hailo

def app_callback(element, buffer, user_data):
    roi = hailo.get_roi_from_buffer(buffer)
    detections = roi.get_objects_typed(hailo.HAILO_DETECTION)

    for detection in detections:
        label = detection.get_label()        # e.g., "person", "car"
        confidence = detection.get_confidence()  # 0.0 - 1.0
        bbox = detection.get_bbox()          # Normalized bounding box
        # bbox.xmin(), bbox.ymin(), bbox.width(), bbox.height() — all normalized [0,1]
```

### Getting Track IDs (requires TRACKER_PIPELINE in pipeline)
```python
        track_id = 0
        track = detection.get_objects_typed(hailo.HAILO_UNIQUE_ID)
        if len(track) == 1:
            track_id = track[0].get_id()
```

### Getting Pose Landmarks (pose estimation models)
```python
        landmarks = detection.get_objects_typed(hailo.HAILO_LANDMARKS)
        if landmarks:
            points = landmarks[0].get_points()
            # Each point has .x() and .y() — normalized to bounding box
            # Convert to pixel coordinates:
            for point in points:
                pixel_x = int((point.x() * bbox.width() + bbox.xmin()) * frame_width)
                pixel_y = int((point.y() * bbox.height() + bbox.ymin()) * frame_height)
```

### Hailo Detection Types Reference
| Type | Constant | Method | Returns |
|---|---|---|---|
| Detection boxes | `hailo.HAILO_DETECTION` | `roi.get_objects_typed()` | List of detections |
| Track IDs | `hailo.HAILO_UNIQUE_ID` | `detection.get_objects_typed()` | List with single ID object |
| Pose landmarks | `hailo.HAILO_LANDMARKS` | `detection.get_objects_typed()` | List of landmark sets |
| Classification | `hailo.HAILO_CLASSIFICATION` | `detection.get_objects_typed()` | List of classifications |
| Masks | `hailo.HAILO_CONF_CLASS_MASK` | `detection.get_objects_typed()` | Segmentation masks |

---

## Reusing Existing Pipeline Classes

For apps that extend existing pipelines (e.g., a pose estimation game), **subclass the domain-specific pipeline class** instead of the base `GStreamerApp`:

```python
from hailo_apps.python.pipeline_apps.pose_estimation.pose_estimation_pipeline import (
    GStreamerPoseEstimationApp,
)

class MyPoseGame(GStreamerPoseEstimationApp):
    """Inherits full pose pipeline: SOURCE → INFERENCE → TRACKER → USER_CALLBACK → DISPLAY"""
    pass  # Pipeline is already configured — just write your callback

def app_callback(element, buffer, user_data):
    # All pose detection data is available here
    ...

def main():
    user_data = UserAppCallback()
    app = MyPoseGame(app_callback, user_data)  # No pipeline config needed
    app.run()
```

**Available pipeline classes to subclass:**
| Class | Module | Pipeline includes |
|---|---|---|
| `GStreamerPoseEstimationApp` | `pose_estimation.pose_estimation_pipeline` | Inference + Tracker + User Callback |
| `GStreamerDetectionApp` | `detection.detection_pipeline` | Inference + User Callback |
| `GStreamerInstanceSegmentationApp` | `instance_segmentation.instance_segmentation_pipeline` | Inference + User Callback |
| `GStreamerFaceRecognitionApp` | `face_recognition.face_recognition_pipeline` | Cascaded inference + Tracker |

When subclassing, you get the full pipeline for free — just provide your custom `app_callback` and `app_callback_class`.

