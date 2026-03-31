# GStreamer Pipeline Patterns

> How to build and compose GStreamer pipelines using the hailo-apps framework.

## Pipeline String Composition

All pipelines are built by **composing string fragments** from helper functions:

```python
from hailo_apps.python.core.gstreamer.gstreamer_helper_pipelines import (
    SOURCE_PIPELINE,
    INFERENCE_PIPELINE,
    DISPLAY_PIPELINE,
    USER_CALLBACK_PIPELINE,
    TRACKER_PIPELINE,
    QUEUE,
)

class MyApp(GStreamerApp):
    def get_pipeline_string(self):
        source = SOURCE_PIPELINE(self.video_source, self.video_width, self.video_height)
        inference = INFERENCE_PIPELINE(hef_path=self.hef_path, post_process_so=so_path)
        callback = USER_CALLBACK_PIPELINE()
        display = DISPLAY_PIPELINE(video_sink=self.video_sink, sync=self.sync)
        return f"{source} ! {inference} ! {callback} ! {display}"
```

## Available Pipeline Fragments

### Source Pipeline
```python
SOURCE_PIPELINE(
    video_source,        # Camera index, file path, or RTSP URL
    video_width=640,     # Output width
    video_height=480,    # Output height
    video_format="RGB",  # Pixel format
    name="source",       # Element name
)
# Supports: USB camera, RPi camera, file, RTSP, X11 screen capture
```

### Inference Pipeline
```python
INFERENCE_PIPELINE(
    hef_path,           # Path to HEF model
    post_process_so,    # Path to postprocess .so library
    batch_size=1,       # Inference batch size
    config_path=None,   # Optional JSON config for postprocess
    post_function_name=None,  # Function name in .so
    additional_params="",     # Extra hailonet params
)
```

### Display Pipeline
```python
DISPLAY_PIPELINE(
    video_sink="xvimagesink",  # Display backend
    sync="true",               # Sync to clock
    show_fps=False,            # Show FPS overlay
)
```

### Tracker Pipeline
```python
TRACKER_PIPELINE(
    class_id=-1,              # Track specific class (-1 = all)
    kalman_dist_thr=0.7,      # Kalman filter distance threshold
    iou_thr=0.8,              # IoU threshold
    init_iou_thr=0.9,         # Initial IoU threshold
    keep_tracked=True,         # Keep tracked objects visible
)
```

### Cascaded Inference (Cropper + Second Network)
```python
CROPPER_PIPELINE(
    inner_pipeline=INFERENCE_PIPELINE(...),  # Second-stage inference
    so_path="libcropper.so",   # Cropper shared library
    function_name="crop_func", # Function in .so
)
```

### Tiled Inference
```python
TILE_CROPPER_PIPELINE(
    inner_pipeline=INFERENCE_PIPELINE(...),
    tiles_along_x_axis=2,
    tiles_along_y_axis=2,
    overlap_x_ratio=0.1,
    overlap_y_ratio=0.1,
)
```

## Pipeline Architecture Patterns

### Single Network (Detection, Classification, Segmentation)
```
Source → Queue → Inference → Queue → Callback → Display
```

### Wrapped Inference (Preserve Original Resolution)
```
Source → Queue → [Cropper → Inference → Aggregator] → Queue → Callback → Display
```
Uses `INFERENCE_PIPELINE_WRAPPER()` to scale down for inference, then overlay results on original resolution.

### Cascaded Networks (Detection → Second Stage)
```
Source → Detection → [Cropper → Classification → Aggregator] → Callback → Display
```
First network detects ROIs, second network processes crops.

### Parallel Networks (Tee + Muxer)
```
Source → Tee ─→ Queue → Network A ─→ Muxer → Callback → Display
              └→ Queue → Network B ─┘
```

## Callback Pattern

```python
from hailo_apps.python.core.gstreamer.gstreamer_app import app_callback_class

class MyUserData(app_callback_class):
    def __init__(self):
        super().__init__()
        self.custom_counter = 0

def app_callback(element, buffer, user_data):
    """Called for every frame. Framework auto-increments frame count."""
    import hailo
    roi = hailo.get_roi_from_buffer(buffer)
    detections = roi.get_objects_typed(hailo.HAILO_DETECTION)
    for det in detections:
        label = det.get_label()
        confidence = det.get_confidence()
        bbox = det.get_bbox()
    return Gst.PadProbeReturn.OK
```

## GStreamer Elements Reference

| Element | Purpose |
|---|---|
| `hailonet` | Run inference on Hailo accelerator |
| `hailofilter` | Apply postprocessing .so library |
| `hailooverlay` | Draw detections/labels on frame |
| `hailocropper` | Crop ROIs for second-stage inference |
| `hailoaggregator` | Merge cropped results back |
| `hailotilecropper` | Tile-based inference splitting |
| `hailotileaggregator` | Merge tiled results |
| `hailomuxer` | Merge parallel inference branches |
| `hailotracker` | Object tracking (ByteTrack) |
| `identity` | Pass-through for Python callback injection |

## Common GStreamer Arguments

All pipeline apps inherit these CLI arguments:
- `--input`: Video source (usb, rpi, file path, rtsp://)
- `--hef-path`: Override model HEF path
- `--show-fps`: Display FPS counter
- `--disable-sync`: Run as fast as possible
- `--use-frame`: Enable numpy frame access in callback
- `--enable-watchdog`: Auto-restart on pipeline stall
- `--dump-dot`: Generate Graphviz pipeline diagram

