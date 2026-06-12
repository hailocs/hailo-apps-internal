# Standalone App Template

## Overview

Standalone apps are lightweight Python scripts that use the HailoRT API directly for inference -- no GStreamer or TAPPAS required. They use a 3-thread architecture (preprocess, infer, visualize) with queue-based data flow and `HailoAsyncInference` for efficient async inference on Hailo accelerators.

**When to use this type:**
- Batch processing of images or video files
- Quick prototyping and learning the HailoRT API
- Environments where GStreamer/TAPPAS is not installed
- CPU-side post-processing with full Python control
- Single-script apps with minimal dependencies

**When NOT to use this type:**
- Real-time camera pipelines needing hardware decoding, overlay, or tracking (use pipeline app)
- GenAI / LLM / VLM workloads on Hailo-10H (use genai app)
- You need the TAPPAS `hailooverlay` or `hailotracker` elements (use pipeline app)

## File Structure

A standalone app lives in `hailo_apps/python/standalone_apps/<your_app>/`:

```
your_app/
  __init__.py                      # Empty, makes this a Python package
  your_app.py                      # Main script: CLI, threads, inference loop
  your_app_post_process.py         # Post-processing: decode model output, draw results
  config.json                      # (Optional) Visualization and tracker parameters
```

## Template: `your_app.py`

```python
#!/usr/bin/env python3
"""
[CUSTOMIZE: Brief description of what this app does.]

Usage:
    python -m hailo_apps.python.standalone_apps.your_app.your_app --input video.mp4
    python -m hailo_apps.python.standalone_apps.your_app.your_app --input usb --show-fps
"""
import os
import sys
import queue
import threading
from functools import partial
from types import SimpleNamespace
from pathlib import Path
import collections
import numpy as np

# Handle both installed-package and direct-script execution
try:
    from hailo_apps.python.core.common.hailo_inference import HailoInfer
    from hailo_apps.python.core.common.toolbox import (
        init_input_source,      # Opens video file, camera, or image folder
        get_labels,             # Loads label file (text, one label per line)
        load_json_file,         # Loads JSON config (thresholds, visualization params)
        preprocess,             # Preprocess thread: reads frames, resizes, queues them
        visualize,              # Visualize thread: draws results, displays/saves output
        select_cap_processing_mode,
        FrameRateTracker,       # Tracks and prints FPS statistics
    )
    from hailo_apps.python.core.common.defines import (
        MAX_INPUT_QUEUE_SIZE,   # Default: 100
        MAX_OUTPUT_QUEUE_SIZE,  # Default: 100
        MAX_ASYNC_INFER_JOBS,   # Default: 3 (concurrent async inference jobs)
    )
    from hailo_apps.python.core.common.parser import get_standalone_parser
    from hailo_apps.python.core.common.hailo_logger import get_logger, init_logging, level_from_args
    from hailo_apps.python.core.common.core import handle_and_resolve_args

    # [CUSTOMIZE: Import your post-processing function]
    from hailo_apps.python.standalone_apps.your_app.your_app_post_process import inference_result_handler

except ImportError:
    # Fallback for running as a plain script outside the package
    repo_root = None
    for p in Path(__file__).resolve().parents:
        if (p / "hailo_apps" / "config" / "config_manager.py").exists():
            repo_root = p
            break
    if repo_root is not None:
        sys.path.insert(0, str(repo_root))
    # Re-import after fixing path (same imports as above)
    from hailo_apps.python.core.common.hailo_inference import HailoInfer
    from hailo_apps.python.core.common.toolbox import (
        init_input_source, get_labels, load_json_file,
        preprocess, visualize, select_cap_processing_mode, FrameRateTracker,
    )
    from hailo_apps.python.core.common.defines import (
        MAX_INPUT_QUEUE_SIZE, MAX_OUTPUT_QUEUE_SIZE, MAX_ASYNC_INFER_JOBS,
    )
    from hailo_apps.python.core.common.parser import get_standalone_parser
    from hailo_apps.python.core.common.hailo_logger import get_logger, init_logging, level_from_args
    from hailo_apps.python.core.common.core import handle_and_resolve_args
    from hailo_apps.python.standalone_apps.your_app.your_app_post_process import inference_result_handler


APP_NAME = Path(__file__).stem
logger = get_logger(__name__)


def parse_args():
    """
    Parse CLI arguments. The base parser provides:
      --input (-i)       : Video file, "usb", "camera", or image folder path
      --hef-path         : Path to HEF model (name or full path, auto-downloads)
      --batch-size (-b)  : Inference batch size (default: 1)
      --output-dir (-o)  : Directory for saving output
      --save-output (-s) : Enable saving output
      --show-fps         : Display FPS counter
      --frame-rate       : Target frame rate
      --no-display       : Run headless (no OpenCV window)
      --list-models      : Show available models and exit
      --list-inputs      : Show available demo inputs and exit
      --arch             : Override architecture detection
    """
    parser = get_standalone_parser()
    parser.description = "[CUSTOMIZE: Description of your app]"

    # [CUSTOMIZE: Add your app-specific arguments]
    parser.add_argument(
        "--track",
        action="store_true",
        help="Enable object tracking (BYTETracker) for persistent IDs across frames.",
    )
    parser.add_argument(
        "--labels", "-l",
        type=str,
        default=None,
        help="Path to labels text file (one label per line). Default: auto-detected from model.",
    )

    args = parser.parse_args()
    return args


def run_inference_pipeline(
    net,               # HEF path (str or Path)
    input_src,         # Input source string
    batch_size,        # Batch size for inference
    labels,            # Path to labels file (or None)
    output_dir,        # Output directory for saved results
    save_output=False,
    camera_resolution="sd",
    output_resolution=None,
    enable_tracking=False,
    show_fps=False,
    frame_rate=None,
    no_display=False,
) -> None:
    """
    Main inference pipeline: sets up 3 threads and runs until input is exhausted.

    Architecture:
        preprocess_thread --> input_queue --> infer_thread --> output_queue --> visualize_thread

    The preprocess thread reads frames, resizes them to model input size, and queues them.
    The infer thread runs async inference on the Hailo device.
    The visualize thread applies post-processing, draws results, and displays/saves output.
    """

    # --- Load Configuration ---
    labels = get_labels(labels)
    # [CUSTOMIZE: Create a config.json in your app directory with visualization params,
    #  thresholds, tracker config, etc. Load it here.]
    config_data = load_json_file("config.json")

    # --- Initialize Input Source ---
    # cap: OpenCV VideoCapture (for video/camera), images: list of paths (for image folder)
    cap, images, input_type = init_input_source(input_src, batch_size, camera_resolution)
    cap_processing_mode = None
    if cap is not None:
        cap_processing_mode = select_cap_processing_mode(input_type, save_output, frame_rate)

    stop_event = threading.Event()

    # --- (Optional) FPS Tracking ---
    fps_tracker = None
    if show_fps:
        fps_tracker = FrameRateTracker()

    # --- (Optional) BYTETracker for Object Tracking ---
    # [CUSTOMIZE: Remove this section if your app doesn't need tracking]
    tracker = None
    if enable_tracking:
        from hailo_apps.python.core.tracker.byte_tracker import BYTETracker
        tracker_config = config_data.get("visualization_params", {}).get("tracker", {})
        tracker = BYTETracker(SimpleNamespace(**tracker_config))

    # --- Set Up Queues ---
    input_queue = queue.Queue(MAX_INPUT_QUEUE_SIZE)
    output_queue = queue.Queue(MAX_OUTPUT_QUEUE_SIZE)

    # --- Create Post-Processing Callback ---
    # This function is called for each inference result in the visualize thread.
    # [CUSTOMIZE: Pass your app-specific parameters to the post-processing function]
    post_process_callback_fn = partial(
        inference_result_handler,
        labels=labels,
        config_data=config_data,
        tracker=tracker,
    )

    # --- Initialize Hailo Inference ---
    hailo_inference = HailoInfer(net, batch_size)
    height, width, _ = hailo_inference.get_input_shape()
    # height, width are the model's expected input dimensions

    # --- Launch Threads ---
    preprocess_thread = threading.Thread(
        target=preprocess,
        args=(images, cap, frame_rate, batch_size, input_queue,
              width, height, cap_processing_mode, None, stop_event)
    )
    postprocess_thread = threading.Thread(
        target=visualize,
        args=(output_queue, cap, save_output, output_dir,
              post_process_callback_fn, fps_tracker, output_resolution,
              frame_rate, False, stop_event, no_display)
    )
    infer_thread = threading.Thread(
        target=infer,
        args=(hailo_inference, input_queue, output_queue, stop_event)
    )

    preprocess_thread.start()
    postprocess_thread.start()
    infer_thread.start()

    if show_fps:
        fps_tracker.start()

    try:
        preprocess_thread.join()
        infer_thread.join()
        postprocess_thread.join()
    except KeyboardInterrupt:
        logger.info("Interrupted (Ctrl+C). Shutting down...")
        stop_event.set()
    finally:
        if show_fps:
            logger.info(fps_tracker.frame_rate_summary())
        logger.success("Processing completed successfully.")
        if save_output or input_type == "images":
            logger.info(f"Saved outputs to '{output_dir}'.")


def infer(hailo_inference, input_queue, output_queue, stop_event):
    """
    Inference loop: pulls batches from input_queue, runs async inference,
    pushes results to output_queue.

    Each input_queue item is a tuple: (original_frames, preprocessed_frames)
    Each output_queue item is a tuple: (original_frame, model_output)
    """
    pending_jobs = collections.deque()

    while True:
        next_batch = input_queue.get()
        if not next_batch:
            break  # Sentinel value signals end of input

        if stop_event.is_set():
            continue

        input_batch, preprocessed_batch = next_batch

        inference_callback_fn = partial(
            inference_callback,
            input_batch=input_batch,
            output_queue=output_queue
        )

        # Limit concurrent async jobs to avoid memory pressure
        while len(pending_jobs) >= MAX_ASYNC_INFER_JOBS:
            pending_jobs.popleft().wait(10000)

        # Run async inference on the Hailo device
        job = hailo_inference.run(preprocessed_batch, inference_callback_fn)
        pending_jobs.append(job)

    # Signal end of inference to visualize thread
    hailo_inference.close()
    output_queue.put(None)


def inference_callback(completion_info, bindings_list, input_batch, output_queue):
    """
    Called when async inference completes. Extracts model output and queues it.

    Args:
        completion_info: Hailo completion info (check .exception for errors)
        bindings_list: List of output bindings (one per batch item)
        input_batch: Original input frames (for visualization)
        output_queue: Queue to push (frame, result) tuples
    """
    if completion_info.exception:
        logger.error(f"Inference error: {completion_info.exception}")
    else:
        for i, bindings in enumerate(bindings_list):
            # Single-output models return a flat buffer
            if len(bindings._output_names) == 1:
                result = bindings.output().get_buffer()
            else:
                # Multi-output models return a dict of named outputs
                result = {
                    name: np.expand_dims(bindings.output(name).get_buffer(), axis=0)
                    for name in bindings._output_names
                }
            output_queue.put((input_batch[i], result))


def main() -> None:
    """Main entry point."""
    args = parse_args()
    init_logging(level=level_from_args(args))
    # handle_and_resolve_args validates and resolves HEF path, input, output_dir
    handle_and_resolve_args(args, APP_NAME)
    run_inference_pipeline(
        args.hef_path,
        args.input,
        args.batch_size,
        args.labels,
        args.output_dir,
        args.save_output,
        args.camera_resolution,
        args.output_resolution,
        args.track,
        args.show_fps,
        args.frame_rate,
        args.no_display,
    )


if __name__ == "__main__":
    main()
```

## Template: `your_app_post_process.py`

```python
"""
[CUSTOMIZE: Post-processing module for your standalone app.]

This module decodes raw model output into structured results (bounding boxes,
class labels, scores, etc.) and draws them on the original frame.
"""
import cv2
import numpy as np
from typing import Optional

from hailo_apps.python.core.common.hailo_logger import get_logger

logger = get_logger(__name__)


def inference_result_handler(
    frame: np.ndarray,
    result,
    labels: list,
    config_data: dict,
    tracker=None,
    **kwargs,
) -> np.ndarray:
    """
    Process a single inference result and draw it on the frame.

    This function is called by the visualize thread for each (frame, result) pair.

    Args:
        frame: Original input frame (BGR, uint8, original resolution).
        result: Raw model output -- either a numpy array (single output) or
                a dict of {name: numpy_array} (multi-output model).
        labels: List of class label strings (index-aligned with model output).
        config_data: Dict from config.json with visualization params, thresholds, etc.
        tracker: Optional BYTETracker instance for object tracking.

    Returns:
        np.ndarray: The frame with visualizations drawn on it.
    """
    # --- Extract Config ---
    vis_params = config_data.get("visualization_params", {})
    score_threshold = vis_params.get("score_thres", 0.5)
    max_boxes = vis_params.get("max_boxes_to_draw", 50)

    # --- Decode Model Output ---
    # [CUSTOMIZE: This is model-specific. The example below is for a typical
    #  detection model that outputs [batch, num_detections, 6] where each
    #  detection is [y1, x1, y2, x2, score, class_id].
    #  Replace this with your model's output format.]
    detections = decode_detections(result, score_threshold, max_boxes)

    # --- (Optional) Apply Tracking ---
    if tracker is not None and len(detections) > 0:
        # [CUSTOMIZE: BYTETracker expects detections as numpy array with columns:
        #  [x1, y1, x2, y2, score]. It returns tracked objects with IDs.]
        track_input = np.array([[d["x1"], d["y1"], d["x2"], d["y2"], d["score"]]
                                for d in detections])
        h, w = frame.shape[:2]
        tracked = tracker.update(track_input, [h, w], [h, w])
        # tracked objects have .tlbr (top-left-bottom-right) and .track_id
        for t in tracked:
            x1, y1, x2, y2 = map(int, t.tlbr)
            track_id = t.track_id
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(frame, f"ID:{track_id}", (x1, y1 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
    else:
        # --- Draw Detections Without Tracking ---
        for det in detections:
            x1, y1, x2, y2 = det["x1"], det["y1"], det["x2"], det["y2"]
            label = labels[det["class_id"]] if det["class_id"] < len(labels) else "unknown"
            score = det["score"]
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(frame, f"{label}: {score:.2f}", (x1, y1 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

    return frame


def decode_detections(result, score_threshold=0.5, max_boxes=50):
    """
    [CUSTOMIZE: Decode raw model output into a list of detection dicts.

    This is entirely model-specific. Common patterns:
    - YOLO models: output is a flat array that needs NMS decoding
    - SSD models: output has separate boxes, scores, classes, num_detections
    - The HailoRT postprocess built into the HEF often handles NMS already

    Returns:
        list of dicts with keys: x1, y1, x2, y2, score, class_id
    ]
    """
    detections = []
    # Example placeholder -- replace with your model's actual decoding logic
    # ...
    return detections[:max_boxes]
```

## Template: `config.json` (Optional)

```json
{
    "visualization_params": {
        "score_thres": 0.5,
        "max_boxes_to_draw": 50,
        "line_thickness": 2,
        "tracker": {
            "track_thresh": 0.5,
            "track_buffer": 30,
            "match_thresh": 0.8
        }
    }
}
```

## Customization Guide

### How to Swap Models

1. `--hef-path <model_name>` for a model registered in `resources_config.yaml`
2. `--hef-path /path/to/model.hef` for a custom local HEF
3. `--list-models` to see available models for your app
4. When changing models, update `your_app_post_process.py` to decode the new model's output format

### How to Change Input/Output

- **USB Camera:** `--input usb` or `--input /dev/video0`
- **Video file:** `--input video.mp4`
- **Image folder:** `--input /path/to/images/`
- **Camera resolution:** `--camera-resolution hd` (sd/hd/fhd)
- **Save output:** `--save-output --output-dir results/`
- **Headless mode:** `--no-display` (process without showing window)

### How to Add Features

- **BYTETracker integration:** Already shown in template. Pass `--track` at runtime. Configure tracker params in `config.json`.
- **Custom visualization:** Modify `inference_result_handler` to draw whatever you need (masks, keypoints, text, trails).
- **Batch processing:** Increase `--batch-size` for throughput on image folders. The 3-thread architecture handles batching automatically.
- **Multi-output models:** The `inference_callback` already handles both single-output (flat buffer) and multi-output (named dict) models.

### Common Pitfalls

- **Wrong input shape:** The `preprocess` function resizes frames to the model's expected input size automatically. If your model needs special preprocessing (normalization, padding), you need a custom preprocess function.
- **Missing `config.json`:** The `load_json_file` function looks for it relative to your script's directory. Create one or pass an empty dict.
- **Model output format mismatch:** The most common bug. Carefully check what your HEF outputs (shapes, formats) using `hailo_inference.get_output_shape()` and adjust `decode_detections()` accordingly.
- **Memory pressure:** If processing large videos, watch queue sizes. The defaults (100 items) are usually fine, but very high-resolution frames may need smaller queues.

## Checklist

- [ ] Created `your_app.py` with CLI parsing, 3-thread architecture, and inference loop
- [ ] Created `your_app_post_process.py` with model-specific output decoding
- [ ] Created `config.json` with visualization thresholds and (optional) tracker config
- [ ] Created `__init__.py` in your app directory
- [ ] HEF model is registered in `resources_config.yaml` or you use `--hef-path` directly
- [ ] Post-processing correctly decodes your model's output format
- [ ] Labels file matches your model's class indices
- [ ] Tested with `--input usb` (camera) and a video file
- [ ] Tested with `--save-output` to verify output saving works
- [ ] (Optional) Added `--track` support with BYTETracker
- [ ] (Optional) CLI entry point added to `pyproject.toml`
- [ ] (Optional) Test definition added to `test_definition_config.yaml`
