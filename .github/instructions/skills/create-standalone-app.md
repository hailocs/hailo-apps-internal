# Skill: Create Standalone Inference Application

> Build a direct-inference application using HailoInfer without GStreamer.

## When to Use This Skill

- User needs **custom preprocessing/postprocessing** in pure Python
- User wants to process **single images or video files** (not real-time)
- User needs **full control** over the inference pipeline
- GStreamer is not available or not needed

## Reference Implementation

Study `hailo_apps/python/standalone_apps/object_detection/` for the pattern.

## Step-by-Step Build Process

### Step 1: Create App Structure

```
standalone_apps/my_app/
├── __init__.py
├── my_app.py
├── my_app_post_process.py  # Custom postprocessing
├── config.json             # Model configuration
├── README.md
└── requirements.txt
```

### Step 2: Implement Main App

```python
import cv2
import numpy as np
from hailo_apps.python.core.common.hailo_inference import HailoInfer
from hailo_apps.python.core.common.core import (
    get_standalone_parser, resolve_hef_path, handle_list_models_flag
)
from hailo_apps.python.core.common.defines import MY_APP, HAILO8_ARCH
from hailo_apps.python.core.common.hailo_logger import get_logger

logger = get_logger(__name__)

class MyStandaloneApp:
    def __init__(self, hef_path: str, input_source: str):
        self.infer = HailoInfer(hef_path)
        self.input_source = input_source
        self.input_shape = self.infer.get_input_shape()

    def preprocess(self, frame: np.ndarray) -> np.ndarray:
        """Resize and normalize frame for inference."""
        h, w = self.input_shape[:2]
        return cv2.resize(frame, (w, h))

    def postprocess(self, raw_output: dict, original_frame: np.ndarray) -> list:
        """Parse inference output into detections."""
        # Custom postprocessing logic
        pass

    def run(self):
        cap = cv2.VideoCapture(self.input_source)
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            input_data = self.preprocess(frame)
            output = self.infer.run(input_data)
            results = self.postprocess(output, frame)
            # ... display or save results
        cap.release()

if __name__ == "__main__":
    parser = get_standalone_parser()
    handle_list_models_flag(parser, MY_APP)
    args = parser.parse_args()
    hef_path = resolve_hef_path(args.hef_path, app_name=MY_APP, arch=args.arch)
    app = MyStandaloneApp(str(hef_path), args.input)
    app.run()
```

## HailoInfer API

```python
from hailo_apps.python.core.common.hailo_inference import HailoInfer

infer = HailoInfer(hef_path)

# Get model metadata
input_shape = infer.get_input_shape()   # (H, W, C)

# Synchronous inference
output = infer.run(preprocessed_numpy_array)

# Async inference
future = infer.run_async(preprocessed_numpy_array)
output = future.get()
```

## Standalone-Specific CLI Arguments

Inherited from `get_standalone_parser()`:
- `--input`: Input source (camera index, file, URL)
- `--hef-path`: Model path
- `--camera-resolution`: Camera resolution
- `--no-display`: Headless mode
- `--output-resolution`: Output display size
- `--output-dir`: Save outputs to directory
- `--save-output`: Enable output saving
