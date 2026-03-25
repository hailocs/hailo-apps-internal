# Skill: Create GStreamer Pipeline Application

> Build a real-time video processing application using the GStreamer pipeline framework.

## When to Use This Skill

- User needs **real-time video inference** at 30+ FPS
- User wants **object detection, pose estimation, segmentation** on live video
- User needs **object tracking** across frames
- User wants to build on existing TAPPAS/GStreamer infrastructure

## Reference Implementation

Study these before building:
- `hailo_apps/python/core/gstreamer/gstreamer_app.py` — Base class
- `hailo_apps/python/core/gstreamer/gstreamer_helper_pipelines.py` — Pipeline string factory
- Any existing pipeline app in `hailo_apps/python/pipeline_apps/`

## Step-by-Step Build Process

### Step 1: Register App Constants in `defines.py`

```python
# In hailo_apps/python/core/common/defines.py
MY_PIPELINE_APP = "my_pipeline"
MY_PIPELINE_APP_TITLE = "My Pipeline App"
MY_PIPELINE_MODEL_NAME_H8 = "yolov8s"
MY_PIPELINE_MODEL_NAME_H8L = "yolov8s"
MY_PIPELINE_POSTPROCESS_SO = "libyolo_hailortpp_postprocess.so"
MY_PIPELINE_POSTPROCESS_FUNC = "yolov8s"
```

### Step 2: Create App Files

```
pipeline_apps/my_pipeline/
├── __init__.py
├── my_pipeline.py
└── README.md
```

### Step 3: Implement Pipeline

```python
from hailo_apps.python.core.gstreamer.gstreamer_app import GStreamerApp, app_callback_class
from hailo_apps.python.core.gstreamer.gstreamer_helper_pipelines import (
    SOURCE_PIPELINE, INFERENCE_PIPELINE, DISPLAY_PIPELINE,
    USER_CALLBACK_PIPELINE, QUEUE
)

class MyUserData(app_callback_class):
    def __init__(self):
        super().__init__()
        self.detection_count = 0

def app_callback(element, buffer, user_data):
    import hailo
    roi = hailo.get_roi_from_buffer(buffer)
    detections = roi.get_objects_typed(hailo.HAILO_DETECTION)
    user_data.detection_count += len(detections)
    return Gst.PadProbeReturn.OK

class MyPipelineApp(GStreamerApp):
    def __init__(self, args, user_data):
        super().__init__(args, user_data)
        self.hef_path = resolve_hef_path(args.hef_path, MY_PIPELINE_APP, self.arch)

    def get_pipeline_string(self):
        source = SOURCE_PIPELINE(self.video_source, self.video_width, self.video_height)
        inference = INFERENCE_PIPELINE(hef_path=self.hef_path, post_process_so=so_path)
        callback = USER_CALLBACK_PIPELINE()
        display = DISPLAY_PIPELINE(video_sink=self.video_sink, sync=self.sync)
        return f"{source} ! {QUEUE('q1')} ! {inference} ! {QUEUE('q2')} ! {callback} ! {display}"
```

### Step 4: Add Entry Point

```python
if __name__ == "__main__":
    user_data = MyUserData()
    args = get_pipeline_parser().parse_args()
    app = MyPipelineApp(args, user_data)
    app.run()
```

## Pipeline Composition Patterns

### With Tracker
```python
pipeline = f"{source} ! {inference} ! {TRACKER_PIPELINE()} ! {callback} ! {display}"
```

### With Resolution Preservation (Wrapper)
```python
from hailo_apps.python.core.gstreamer.gstreamer_helper_pipelines import INFERENCE_PIPELINE_WRAPPER

wrapped = INFERENCE_PIPELINE_WRAPPER(
    INFERENCE_PIPELINE(hef_path=self.hef_path, post_process_so=so_path)
)
pipeline = f"{source} ! {wrapped} ! {callback} ! {display}"
```

### Cascaded (Detection → Classification)
```python
second_stage = INFERENCE_PIPELINE(hef_path=classifier_hef, post_process_so=classifier_so)
cascade = CROPPER_PIPELINE(second_stage, cropper_so, cropper_func)
pipeline = f"{source} ! {detection} ! {cascade} ! {callback} ! {display}"
```

## Callback Best Practices

1. **Never call `user_data.increment()`** — framework does this automatically
2. **Use `user_data.get_count()`** to check frame number
3. **Keep callbacks fast** — offload heavy work to threads
4. **Use `user_data.set_frame(frame)`** if you need to pass frames between callback and main thread
