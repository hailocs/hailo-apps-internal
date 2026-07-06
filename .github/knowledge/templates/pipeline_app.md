# Pipeline App Template

## Overview

Pipeline apps are real-time GStreamer video processing applications that run on Hailo-8, Hailo-8L, or Hailo-10H accelerators. They use the TAPPAS GStreamer plugin ecosystem for hardware-accelerated inference, post-processing, tracking, and overlay rendering.

**When to use this type:**
- Real-time video processing from cameras, RTSP streams, or video files
- You need GStreamer pipeline features: hardware decoding, overlay rendering, tracking
- You need the `hailonet` element for efficient on-device inference
- Your app processes a continuous video stream (not batch images)

**When NOT to use this type:**
- Simple batch inference on images (use standalone app instead)
- GenAI / LLM / VLM workloads on Hailo-10H (use genai app instead)
- Quick prototyping without TAPPAS dependency (use standalone app instead)

## File Structure

A pipeline app consists of these files in `hailo_apps/python/pipeline_apps/<your_app>/`:

```
your_app/
  __init__.py              # Empty file, makes this a Python package
  your_app_pipeline.py     # Pipeline class (subclass of GStreamerApp)
  your_app.py              # Callback function and main entry point
```

Additionally, you may need:
- An entry in `hailo_apps/config/resources_config.yaml` for model/resource definitions
- An entry in `hailo_apps/config/test_definition_config.yaml` for test integration
- A CLI entry point in `pyproject.toml` under `[project.scripts]`

## Template: `__init__.py`

```python
# [CUSTOMIZE: This file is intentionally empty. It marks the directory as a Python package.]
```

## Template: `your_app_pipeline.py`

```python
# region imports
from pathlib import Path

import setproctitle

from hailo_apps.python.core.common.core import (
    get_pipeline_parser,       # Standard CLI argument parser for pipeline apps
    get_resource_path,         # Resolves resource file paths (postprocess .so, configs)
    handle_list_models_flag,   # Handles --list-models before full init
    resolve_hef_path,          # Smart HEF lookup with auto-download
)
from hailo_apps.python.core.common.defines import (
    # [CUSTOMIZE: Import your app's constants from defines.py. You will need to add them there first.]
    # Example constants you need to define:
    #   YOUR_APP_TITLE = "Hailo Your App"
    #   YOUR_APP_PIPELINE = "your_app"              # Must match resources_config.yaml key
    #   YOUR_APP_POSTPROCESS_FUNCTION = "your_func"  # C++ postprocess function name
    #   YOUR_APP_POSTPROCESS_SO_FILENAME = "libyour_post.so"
    RESOURCES_SO_DIR_NAME,
)
from hailo_apps.python.core.common.hef_utils import get_hef_labels_json
from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.gstreamer.gstreamer_app import (
    GStreamerApp,           # Base class for all pipeline apps
    app_callback_class,     # Base class for callback user data
    dummy_callback,         # No-op callback (used when running pipeline without custom logic)
)
from hailo_apps.python.core.gstreamer.gstreamer_helper_pipelines import (
    DISPLAY_PIPELINE,               # hailooverlay + fpsdisplaysink
    INFERENCE_PIPELINE,             # hailonet + hailofilter (inference + postprocess)
    INFERENCE_PIPELINE_WRAPPER,     # Wraps inference to preserve original resolution
    SOURCE_PIPELINE,                # Video source (file, USB camera, RTSP, RPi camera)
    TRACKER_PIPELINE,               # HailoTracker for object tracking across frames
    USER_CALLBACK_PIPELINE,         # Identity element that triggers your Python callback
    # [CUSTOMIZE: Import additional helpers as needed:]
    # CROPPER_PIPELINE,             # For cascaded networks (crop detections, run 2nd model)
    # TILE_CROPPER_PIPELINE,        # For tiled inference on high-res images
    # FILE_SINK_PIPELINE,           # For saving output to video file
    # OVERLAY_PIPELINE,             # Standalone overlay (without display sink)
)

hailo_logger = get_logger(__name__)
# endregion imports


# [CUSTOMIZE: Rename this class to match your app, e.g. GStreamerPoseEstimationApp]
class GStreamerYourApp(GStreamerApp):
    def __init__(self, app_callback, user_data, parser=None):
        # --- Argument Parsing ---
        # The parser provides standard CLI args: --input, --hef-path, --arch, --use-frame,
        # --show-fps, --disable-sync, --batch-size, --width, --height, etc.
        if parser is None:
            parser = get_pipeline_parser()

        # [CUSTOMIZE: Add your app-specific CLI arguments here]
        parser.add_argument(
            "--labels-json",
            default=None,
            help="Path to custom labels JSON file",
        )

        # Handle --list-models flag before full initialization (exits early if flag is set)
        # [CUSTOMIZE: Replace YOUR_APP_PIPELINE with your pipeline name constant]
        handle_list_models_flag(parser, "your_app")

        hailo_logger.info("Initializing Your App...")

        # --- Parent Class Init ---
        # This parses args, detects architecture, sets up video source, etc.
        # After this call, you have access to: self.arch, self.video_source,
        # self.frame_rate, self.sync, self.show_fps, self.batch_size,
        # self.video_width, self.video_height, self.hef_path, self.video_sink
        super().__init__(parser, user_data)

        # --- Model Configuration ---
        # [CUSTOMIZE: Set batch_size appropriate for your model. Detection uses 2, pose uses 2.]
        if self.batch_size == 1:
            self.batch_size = 2

        # [CUSTOMIZE: Set NMS thresholds appropriate for your model]
        nms_score_threshold = 0.3
        nms_iou_threshold = 0.45

        # --- Resource Resolution ---
        # Resolve HEF path: checks CLI arg, then resources_config.yaml, auto-downloads if needed
        # [CUSTOMIZE: Replace "your_app" with your pipeline name from resources_config.yaml]
        self.hef_path = resolve_hef_path(
            self.hef_path,
            app_name="your_app",
            arch=self.arch
        )

        # Resolve postprocess .so path
        # [CUSTOMIZE: Replace with your postprocess .so filename and function name]
        self.post_process_so = get_resource_path(
            "your_app", RESOURCES_SO_DIR_NAME, self.arch, "libyour_postprocess.so"
        )
        self.post_function_name = "your_postprocess_function"

        # Auto-detect labels JSON from HEF file (or use user-provided one)
        self.labels_json = self.options_menu.labels_json
        if self.labels_json is None:
            self.labels_json = get_hef_labels_json(self.hef_path)

        hailo_logger.info(
            "Resources | hef=%s | post_so=%s | labels_json=%s",
            self.hef_path, self.post_process_so, self.labels_json,
        )

        # --- Validate Resources ---
        if self.hef_path is None or not Path(self.hef_path).exists():
            hailo_logger.error("HEF path is invalid or missing: %s", self.hef_path)
        if self.post_process_so is None or not Path(self.post_process_so).exists():
            hailo_logger.error("Post-process .so is invalid or missing: %s", self.post_process_so)

        # Store the callback reference
        self.app_callback = app_callback

        # Build threshold string for hailonet additional_params
        # [CUSTOMIZE: Adjust thresholds and output format for your model]
        self.thresholds_str = (
            f"nms-score-threshold={nms_score_threshold} "
            f"nms-iou-threshold={nms_iou_threshold} "
            f"output-format-type=HAILO_FORMAT_TYPE_FLOAT32"
        )

        # Set process title (visible in `ps` and `top`)
        # [CUSTOMIZE: Set a descriptive process title]
        setproctitle.setproctitle("Hailo Your App")

        # Create the GStreamer pipeline (calls get_pipeline_string() below)
        self.create_pipeline()

    def get_pipeline_string(self):
        """
        Build and return the GStreamer pipeline string.

        This is the core method where you define the data flow. The pipeline is
        a chain of GStreamer elements connected with '!'. Use the helper functions
        to build each stage.

        Common pipeline patterns:
          1. Simple:    source -> inference -> callback -> display
          2. Wrapped:   source -> inference_wrapper(inference) -> callback -> display
          3. Tracked:   source -> inference_wrapper(inference) -> tracker -> callback -> display
          4. Cascaded:  source -> inference1 -> cropper(inference2) -> callback -> display
          5. Tiled:     source -> tile_cropper(inference) -> callback -> display
        """

        # --- Source Stage ---
        # Handles: file, USB camera, RPi camera, RTSP, screen capture
        source_pipeline = SOURCE_PIPELINE(
            video_source=self.video_source,
            video_width=self.video_width,
            video_height=self.video_height,
            frame_rate=self.frame_rate,
            sync=self.sync,
        )

        # --- Inference Stage ---
        # hailonet (runs the HEF on the accelerator) + hailofilter (C++ postprocess)
        inference_pipeline = INFERENCE_PIPELINE(
            hef_path=self.hef_path,
            post_process_so=self.post_process_so,
            post_function_name=self.post_function_name,
            batch_size=self.batch_size,
            config_json=self.labels_json,
            additional_params=self.thresholds_str,
        )

        # --- Inference Wrapper (Resolution Preservation) ---
        # Wraps inference with hailocropper/hailoaggregator so the original frame
        # resolution is preserved. Inference runs on a scaled-down copy; results
        # are mapped back to the original frame.
        # [CUSTOMIZE: Remove wrapper if you don't need resolution preservation
        #  and want lower latency. Connect inference_pipeline directly instead.]
        inference_pipeline_wrapper = INFERENCE_PIPELINE_WRAPPER(inference_pipeline)

        # --- Tracker Stage (Optional) ---
        # Assigns persistent IDs to detections across frames.
        # class_id: which detection class to track (-1 = all, 1 = person in COCO)
        # [CUSTOMIZE: Remove this line if you don't need tracking.
        #  Change class_id to match the class you want to track.]
        tracker_pipeline = TRACKER_PIPELINE(class_id=-1)

        # --- User Callback Stage ---
        # An identity element that triggers your Python callback on every frame.
        # The callback receives the buffer with all metadata (detections, landmarks, etc.)
        user_callback_pipeline = USER_CALLBACK_PIPELINE()

        # --- Display Stage ---
        # hailooverlay (draws bboxes/labels) + fpsdisplaysink (shows video)
        display_pipeline = DISPLAY_PIPELINE(
            video_sink=self.video_sink, sync=self.sync, show_fps=self.show_fps
        )

        # --- Assemble Pipeline ---
        # [CUSTOMIZE: Modify this chain to match your desired architecture.
        #  Remove tracker_pipeline if not needed. Add CROPPER_PIPELINE for cascaded models.]
        pipeline_string = (
            f"{source_pipeline} ! "
            f"{inference_pipeline_wrapper} ! "
            f"{tracker_pipeline} ! "
            f"{user_callback_pipeline} ! "
            f"{display_pipeline}"
        )
        hailo_logger.debug("Pipeline string: %s", pipeline_string)
        return pipeline_string


def main():
    """Entry point when running the pipeline without a custom callback."""
    hailo_logger.info("Starting Your App...")
    user_data = app_callback_class()
    app_callback = dummy_callback
    # [CUSTOMIZE: Replace GStreamerYourApp with your class name]
    app = GStreamerYourApp(app_callback, user_data)
    app.run()


if __name__ == "__main__":
    main()
```

## Template: `your_app.py` (Callback File)

```python
# region imports
import os
os.environ["GST_PLUGIN_FEATURE_RANK"] = "vaapidecodebin:NONE"

import gi
gi.require_version("Gst", "1.0")
import cv2
import hailo
from gi.repository import Gst

# [CUSTOMIZE: Import your pipeline class]
from hailo_apps.python.pipeline_apps.your_app.your_app_pipeline import GStreamerYourApp
from hailo_apps.python.core.common.buffer_utils import (
    get_caps_from_pad,
    get_numpy_from_buffer,
)
from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.gstreamer.gstreamer_app import app_callback_class

hailo_logger = get_logger(__name__)
# endregion imports


# -----------------------------------------------------------------------------------------------
# User-defined class to be used in the callback function
# -----------------------------------------------------------------------------------------------

# [CUSTOMIZE: Add any state you need to persist across frames]
class user_app_callback_class(app_callback_class):
    def __init__(self):
        super().__init__()
        # [CUSTOMIZE: Add your custom state variables here]
        # Frame counting is automatic via get_count() -- do NOT call increment() yourself.
        self.total_detections = 0


# -----------------------------------------------------------------------------------------------
# User-defined callback function
# -----------------------------------------------------------------------------------------------

def app_callback(element, buffer, user_data):
    """
    Called for every frame processed by the pipeline.

    IMPORTANT: This callback must be NON-BLOCKING. If you need to do heavy processing,
    dispatch to a separate thread or process.

    Args:
        element: The GStreamer identity element that triggers this callback.
        buffer: The GStreamer buffer containing the video frame and all AI metadata.
        user_data: Your user_app_callback_class instance (persists across frames).
    """
    if buffer is None:
        hailo_logger.warning("Received None buffer.")
        return

    # Frame count is auto-incremented by the framework -- just read it
    frame_idx = user_data.get_count()

    # --- Get frame dimensions from pad caps ---
    pad = element.get_static_pad("src")
    format, width, height = get_caps_from_pad(pad)

    # --- (Optional) Extract the raw video frame as a numpy array ---
    # Only works when --use-frame flag is passed at runtime.
    # This adds CPU overhead, so only enable if you need pixel-level processing.
    frame = None
    if user_data.use_frame and format is not None and width is not None and height is not None:
        frame = get_numpy_from_buffer(buffer, format, width, height)

    # --- Extract AI metadata from the buffer ---
    # The ROI (Region of Interest) contains all inference results attached to this frame.
    roi = hailo.get_roi_from_buffer(buffer)

    # [CUSTOMIZE: Extract the metadata type relevant to your model]

    # For DETECTION models (YOLO, SSD, etc.):
    detections = roi.get_objects_typed(hailo.HAILO_DETECTION)
    for detection in detections:
        label = detection.get_label()
        confidence = detection.get_confidence()
        bbox = detection.get_bbox()  # HailoBBox with xmin, ymin, width, height (normalized 0-1)

        # Get tracker ID (if TRACKER_PIPELINE is in your pipeline)
        track_id = 0
        track = detection.get_objects_typed(hailo.HAILO_UNIQUE_ID)
        if len(track) == 1:
            track_id = track[0].get_id()

        # [CUSTOMIZE: Add your detection processing logic here]
        # Example: count specific classes, trigger alerts, log events, etc.

    # For CLASSIFICATION models:
    # classifications = roi.get_objects_typed(hailo.HAILO_CLASSIFICATION)
    # for classification in classifications:
    #     label = classification.get_label()
    #     confidence = classification.get_confidence()

    # For LANDMARKS (pose estimation):
    # detections = roi.get_objects_typed(hailo.HAILO_DETECTION)
    # for detection in detections:
    #     landmarks = detection.get_objects_typed(hailo.HAILO_LANDMARKS)
    #     for lm in landmarks:
    #         points = lm.get_points()  # List of (x, y) pairs

    # --- (Optional) Draw on the frame with OpenCV ---
    # Only active when --use-frame is passed. The frame is displayed in a separate window.
    if user_data.use_frame and frame is not None:
        cv2.putText(
            frame,
            f"Frame: {frame_idx} Detections: {len(detections)}",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0, 255, 0),
            2,
        )
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        user_data.set_frame(frame)

    # [CUSTOMIZE: Print or log your results]
    if frame_idx % 30 == 0:  # Print every 30 frames to avoid flooding
        print(f"Frame {frame_idx}: {len(detections)} detections")

    return


def main():
    """Entry point for running the app with a custom callback."""
    hailo_logger.info("Starting Your App with callback.")
    user_data = user_app_callback_class()
    # [CUSTOMIZE: Replace GStreamerYourApp with your pipeline class]
    app = GStreamerYourApp(app_callback, user_data)
    app.run()


if __name__ == "__main__":
    main()
```

## Customization Guide

### How to Swap Models

1. Use `--hef-path <model_name>` to specify a model by name (auto-downloaded from resources_config.yaml)
2. Use `--hef-path /path/to/model.hef` for a custom local HEF file
3. Use `--list-models` to see all available models for your app and architecture
4. To add a new default model, update `hailo_apps/config/resources_config.yaml`

### How to Change Input/Output

- **USB Camera:** `--input usb` or `--input /dev/video0`
- **Video file:** `--input /path/to/video.mp4`
- **RTSP stream:** `--input rtsp://host:port/stream`
- **RPi Camera:** `--input rpi`
- **Resolution:** `--width 1920 --height 1080`
- **Frame rate:** `--frame-rate 15`
- **Save to file:** Replace `DISPLAY_PIPELINE` with `FILE_SINK_PIPELINE("output.mkv")` in your pipeline string

### How to Add Features

- **Remove tracking:** Delete the `TRACKER_PIPELINE` line and its `! ` connector in `get_pipeline_string()`
- **Add tracking:** Insert `TRACKER_PIPELINE(class_id=-1) ! ` before `USER_CALLBACK_PIPELINE`
- **Cascaded models (e.g., detect then classify):** Use `CROPPER_PIPELINE(inner_pipeline, so_path, function_name)` after the first inference stage
- **Tiled inference (small object detection):** Replace `INFERENCE_PIPELINE_WRAPPER` with `TILE_CROPPER_PIPELINE(inference_pipeline)`
- **Parallel models:** Use `tee name=t` to split the stream and `hailomuxer` to merge results
- **Custom overlay:** Use `hailooverlay_community` element for per-detection colors, sprites, and label filtering

### How to Add a CLI Entry Point

Add to `pyproject.toml` under `[project.scripts]`:
```toml
hailo-your-app = "hailo_apps.python.pipeline_apps.your_app.your_app:main"
```

### Common Pitfalls

- **Blocking callback:** Your callback runs in the GStreamer streaming thread. Any blocking operation (network call, heavy computation, file I/O) will stall the entire pipeline. Use a thread pool or queue for heavy work.
- **Do NOT call `user_data.increment()`:** Frame counting is automatic. Calling it manually double-counts.
- **Missing `source setup_env.sh`:** Always source the environment before running. Without it, TAPPAS plugin paths are not set.
- **Missing postprocess .so:** Run `hailo-compile-postprocess` after cloning the repo to build C++ plugins.
- **Wrong class_id in tracker:** Use `-1` to track all classes, or the specific class index from your labels.

## Checklist

- [ ] Created `__init__.py` in your app directory
- [ ] Pipeline class subclasses `GStreamerApp` and overrides `get_pipeline_string()`
- [ ] Called `self.create_pipeline()` at the end of `__init__`
- [ ] HEF model is registered in `resources_config.yaml` (or you use `--hef-path` directly)
- [ ] Postprocess `.so` file exists and is compiled (`hailo-compile-postprocess`)
- [ ] App constants added to `hailo_apps/python/core/common/defines.py`
- [ ] Callback is non-blocking
- [ ] Tested with `--input usb` (camera) and a video file
- [ ] (Optional) CLI entry point added to `pyproject.toml`
- [ ] (Optional) Test definition added to `test_definition_config.yaml`
