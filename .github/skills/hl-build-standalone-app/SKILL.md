---
name: hl-build-standalone-app
description: Build a complete standalone app using HailoInfer + OpenCV on Hailo-8/8L/10H.
---

# Skill: Build Standalone Inference Application

Build a complete standalone app using HailoInfer + OpenCV on Hailo-8/8L/10H.

## When This Skill Is Loaded

- User wants **direct inference** without GStreamer
- User mentions: OpenCV, HailoInfer, standalone, batch processing, custom pipeline
- User needs **full control** over preprocessing and postprocessing

## Reference Implementations

Study `hailo_apps/python/standalone_apps/object_detection/` — the canonical standalone app:
- `object_detection.py` — 3-thread architecture, HailoInfer, queue-based
- Also see: `pose_estimation/`, `instance_segmentation/`, `lane_detection/`

## Build Process

### Step 1: Create App Directory

Create the app directory:

```
hailo_apps/python/<type>/<app_name>/
├── app.yaml              # App manifest (type: standalone)
├── run.sh                # Launch wrapper
├── __init__.py
├── <app_name>.py         # Main app (3-thread architecture)
├── <app_name>_post_process.py  # Custom postprocessing
├── config.json           # Labels, thresholds (optional)
└── README.md             # Usage documentation (REQUIRED — never skip)
```

Create `app.yaml` with `type: standalone` and `run.sh` wrapper.
Do NOT register in `defines.py` or `resources_config.yaml`.

### Step 2: Build Main App (3-Thread Architecture)

```python
import threading
import queue
import signal
import cv2
import numpy as np

from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.common.core import resolve_hef_path, handle_and_resolve_args
from hailo_apps.python.core.common.parser import get_standalone_parser
from hailo_apps.python.core.common.hailo_inference import HailoInfer

logger = get_logger(__name__)

APP_NAME = "my_standalone_app"
MAX_INPUT_QUEUE_SIZE = 5
MAX_OUTPUT_QUEUE_SIZE = 5
MAX_ASYNC_INFER_JOBS = 3


def preprocess_thread(cap, input_queue, hailo_infer, stop_event):
    height, width, _ = hailo_infer.get_input_shape()
    while not stop_event.is_set():
        ret, frame = cap.read()
        if not ret:
            break
        resized = cv2.resize(frame, (width, height))
        input_queue.put((frame, resized))
    input_queue.put(None)


def infer_thread(hailo_infer, input_queue, output_queue, stop_event):
    while not stop_event.is_set():
        item = input_queue.get()
        if item is None:
            break
        frame, preprocessed = item
        results = hailo_infer.run(preprocessed)
        output_queue.put((frame, results))
    output_queue.put(None)


def postprocess_thread(output_queue, stop_event, no_display):
    while not stop_event.is_set():
        item = output_queue.get()
        if item is None:
            break
        frame, results = item
        # Custom postprocessing here
        if not no_display:
            cv2.imshow("Output", frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                stop_event.set()


def main():
    parser = get_standalone_parser()
    args = parser.parse_args()
    args = handle_and_resolve_args(args, APP_NAME)

    stop_event = threading.Event()
    signal.signal(signal.SIGINT, lambda s, f: stop_event.set())

    hailo_infer = HailoInfer(str(args.hef_path), args.batch_size)
    cap = cv2.VideoCapture(args.input)

    input_q = queue.Queue(maxsize=MAX_INPUT_QUEUE_SIZE)
    output_q = queue.Queue(maxsize=MAX_OUTPUT_QUEUE_SIZE)

    threads = [
        threading.Thread(target=preprocess_thread, args=(cap, input_q, hailo_infer, stop_event)),
        threading.Thread(target=infer_thread, args=(hailo_infer, input_q, output_q, stop_event)),
        threading.Thread(target=postprocess_thread, args=(output_q, stop_event, args.no_display)),
    ]

    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        hailo_infer.close()
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
```

### Step 4: Validate

```bash
python3 .github/scripts/validate_app.py hailo_apps/python/standalone_apps/my_standalone_app --smoke-test
```

## Critical Conventions

1. **CLI parser**: `get_standalone_parser()` — includes `--input`, `--hef-path`, `--batch-size`, `--no-display`, `--save-output`
2. **HEF resolution**: `handle_and_resolve_args(args, APP_NAME)`
3. **3-thread pattern**: preprocess → infer → postprocess, connected by `queue.Queue`
4. **Queue sentinel**: `queue.put(None)` to signal thread termination
5. **Async inference**: Limit concurrent jobs with `MAX_ASYNC_INFER_JOBS`
6. **Cleanup**: Always `hailo_infer.close()` in finally block
7. **Stop event**: `threading.Event()` for graceful shutdown
8. **Signal handler**: Register SIGINT to set stop_event

