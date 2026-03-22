# Skill: Create VLM Application

> Build a Vision-Language Model application that uses the Hailo-10H VLM for image understanding.

## When to Use This Skill

- User wants to build an app that **looks at camera images and answers questions**
- User needs **visual scene understanding** (describe, count, detect, analyze)
- User wants a variant of the VLM Chat app with different behavior

## Prerequisites

- Hailo-10H hardware
- `hailo_platform.genai` package with VLM support
- USB or RPi camera

## Reference Implementation

Study `hailo_apps/python/gen_ai_apps/vlm_chat/` before building:
- `vlm_chat.py` — State machine app with camera loop
- `backend.py` — Multiprocessing VLM inference backend

## Step-by-Step Build Process

### Step 1: Register App Constants

Add to `hailo_apps/python/core/common/defines.py`:
```python
MY_VLM_APP = "my_vlm_app"
MY_VLM_APP_TITLE = "My VLM App"
```

### Step 2: Create App Directory

```
hailo_apps/python/gen_ai_apps/my_vlm_app/
├── __init__.py
├── my_vlm_app.py
├── backend.py
└── README.md
```

### Step 3: Copy and Adapt Backend

The backend from `vlm_chat/backend.py` is reusable. Copy it and modify:
- Worker process function
- System prompt
- Image preprocessing (if different resolution needed)
- Response format

### Step 4: Build Main App

```python
import os
import sys
import cv2
import signal
import time
import threading
import concurrent.futures
from typing import Optional

os.environ["QT_QPA_PLATFORM"] = 'xcb'

from hailo_apps.python.gen_ai_apps.my_vlm_app.backend import Backend
from hailo_apps.python.core.common.core import (
    get_standalone_parser, resolve_hef_path, handle_list_models_flag
)
from hailo_apps.python.core.common.defines import (
    MY_VLM_APP, HAILO10H_ARCH, USB_CAMERA
)
from hailo_apps.python.core.common.camera_utils import get_usb_video_devices
from hailo_apps.python.core.common.hailo_logger import get_logger

logger = get_logger(__name__)

class MyVLMApp:
    def __init__(self, camera, camera_type):
        self.camera = camera
        self.camera_type = camera_type
        self.running = True
        signal.signal(signal.SIGINT, self.signal_handler)
        # ... state, backend, thread setup

    def signal_handler(self, sig, frame):
        self.stop()

    def stop(self):
        self.running = False
        if self.backend:
            self.backend.close()

    def run(self):
        # Camera loop + inference logic
        pass

if __name__ == "__main__":
    parser = get_standalone_parser()
    handle_list_models_flag(parser, MY_VLM_APP)
    args = parser.parse_args()
    hef_path = resolve_hef_path(args.hef_path, app_name=MY_VLM_APP, arch=HAILO10H_ARCH)
    # ... camera setup, app.run()
```

### Step 5: Add README

Include: description, requirements, usage CLI, expected output.

## Key Customization Points

| What to Change | Where |
|---|---|
| System prompt | `SYSTEM_PROMPT` constant in main app |
| VLM question/prompt | Passed to `backend.vlm_inference()` |
| Image preprocessing | `Backend.convert_resize_image()` |
| Inference parameters | `MAX_TOKENS`, `TEMPERATURE`, `SEED` |
| App behavior/state machine | `show_video()` method |
| Display/overlay | OpenCV drawing in main loop |

## Common VLM Prompts for Variants

| Variant | System Prompt | User Prompt Pattern |
|---|---|---|
| Scene describer | "Describe what you see concisely." | "Describe the image" |
| Object counter | "Count objects precisely. Reply JSON." | "Count all {objects} in the image" |
| Safety monitor | "You are a safety inspector." | "List any safety hazards visible" |
| Pet monitor | "Monitor pets. Report activities." | "What is the dog/cat doing?" |
| Traffic analyzer | "Analyze traffic patterns." | "Describe traffic and vehicles" |
