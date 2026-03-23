---
name: hl-build-vlm-app
description: Build a Vision-Language Model application for Hailo-10H. Creates complete VLM apps with camera loop, inference, event tracking, and validation. Use when building any app that looks at camera images and uses VLM for understanding.
---

# Skill: Build VLM Application

Build a complete Vision-Language Model application that uses the Hailo-10H VLM for image understanding.

## When This Skill Is Loaded

- User wants to build an app that **looks at camera images and answers questions**
- User needs **visual scene understanding** (describe, count, detect, analyze)
- User wants a variant of the VLM Chat app with different behavior
- User mentions: VLM, vision, image understanding, camera monitoring, scene analysis

## Reference Implementation

Study `hailo_apps/python/gen_ai_apps/vlm_chat/` — the canonical VLM app:
- `vlm_chat.py` — State machine app with camera loop
- `backend.py` — Multiprocessing VLM inference backend (REUSE this, don't copy)

## Build Process

### Step 1: Register App Constants

Add to `hailo_apps/python/core/common/defines.py`:
```python
MY_VLM_APP = "my_vlm_app"
```

### Step 2: Create Directory

```
hailo_apps/python/gen_ai_apps/<app_name>/
├── __init__.py           # Empty
├── <app_name>.py         # Main app class + entry point
├── event_tracker.py      # Optional: event classification (for monitoring apps)
└── README.md             # Usage documentation
```

### Step 3: Build the App

The main app file follows this structure:
```python
import os
import sys
import cv2
import signal
import time
from typing import Optional

os.environ["QT_QPA_PLATFORM"] = 'xcb'

from hailo_apps.python.gen_ai_apps.vlm_chat.backend import Backend
from hailo_apps.python.core.common.core import (
    get_standalone_parser, resolve_hef_path, handle_list_models_flag
)
from hailo_apps.python.core.common.defines import (
    MY_VLM_APP, HAILO10H_ARCH, USB_CAMERA
)
from hailo_apps.python.core.common.camera_utils import get_usb_video_devices
from hailo_apps.python.core.common.hailo_logger import get_logger

logger = get_logger(__name__)

SYSTEM_PROMPT = "Your system prompt here..."
MONITOR_PROMPT = "Your per-frame VLM question here..."

class MyVLMApp:
    def __init__(self, camera, camera_type, args):
        self.camera = camera
        self.camera_type = camera_type
        self.running = True
        self.backend = None
        signal.signal(signal.SIGINT, self.signal_handler)
        # Initialize Backend, EventTracker, etc.

    def signal_handler(self, sig, frame):
        self.running = False

    def run(self):
        # Main loop: capture frame, display, analyze periodically
        pass

    def cleanup(self):
        if self.backend:
            self.backend.close()
        cv2.destroyAllWindows()

def main():
    parser = get_standalone_parser()
    handle_list_models_flag(parser, MY_VLM_APP)
    # Add custom CLI args here
    args = parser.parse_args()
    hef_path = resolve_hef_path(args.hef_path, app_name=MY_VLM_APP, arch=HAILO10H_ARCH)
    # Camera setup, app.run()

if __name__ == "__main__":
    main()
```

### Step 4: Validate

Run the automated validation script:
```bash
python .github/skills/hl-build-vlm-app/scripts/validate_app.py hailo_apps/python/gen_ai_apps/<app_name>
```

Then run the smoke test:
```bash
python .github/skills/hl-build-vlm-app/scripts/test_scaffold.py hailo_apps/python/gen_ai_apps/<app_name>
```

### Step 5: Write README

Include: description, requirements, usage CLI, architecture, customization notes.

## Key Customization Points

| What to Change | Where |
|---|---|
| System prompt | `SYSTEM_PROMPT` constant |
| Per-frame VLM question | `MONITOR_PROMPT` constant |
| Image preprocessing | `Backend.convert_resize_image()` |
| Inference parameters | `MAX_TOKENS`, `TEMPERATURE` |
| Event classification | `EventTracker.classify_response()` |
| Display overlay | OpenCV `cv2.putText()` in main loop |

## Event Tracker Pattern (for monitoring apps)

When building a monitoring-style app, create an `event_tracker.py` with:
- `EventType` enum with activity categories
- `Event` dataclass with timestamp, type, description
- `EventTracker` class with `classify_response()`, `add_event()`, `get_summary()`

Keyword matching in `classify_response()`:
```python
def classify_response(self, vlm_response: str) -> EventType:
    response_lower = vlm_response.lower()
    for event_type, keywords in self.keyword_map.items():
        if any(kw in response_lower for kw in keywords):
            return event_type
    return EventType.IDLE
```

## Common VLM Prompts

| Variant | System Prompt | User Prompt |
|---|---|---|
| Pet monitor | "Monitor pets. Report activities." | "What is the dog doing right now?" |
| Safety | "You are a safety inspector." | "List any safety hazards visible" |
| Scene | "Describe what you see concisely." | "Describe the image" |
| Counter | "Count objects precisely. Reply JSON." | "Count all {objects}" |
| Traffic | "Analyze traffic patterns." | "Describe traffic and vehicles" |
