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

### Step 1: Create App Directory

Create the app directory:

```
hailo_apps/python/<type>/<app_name>/
├── app.yaml              # App manifest (required)
├── run.sh                # Launch wrapper (sets PYTHONPATH)
├── __init__.py           # Empty
├── <app_name>.py         # Main app class + entry point
├── event_tracker.py      # Optional: event classification (for monitoring apps)
└── README.md             # Usage documentation (REQUIRED — never skip)
```

**app.yaml** — required manifest:
```yaml
name: <app_name>
title: My VLM App
description: One-line description
author: AI Agent (auto-generated)
date: "YYYY-MM-DD"
type: gen_ai
hailo_arch: hailo10h
model: Qwen2-VL-2B-Instruct
tags: [vlm, monitoring]
status: draft
```

**run.sh** — launch wrapper:
```bash
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
PYTHONPATH="$REPO_ROOT" python3 "$SCRIPT_DIR/<app_name>.py" "$@"
```

**NOTE**: Do NOT register in `defines.py` or `resources_config.yaml`.
Community apps are run via `run.sh`. Registration happens during promotion

### Step 2: Build the App

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
    HAILO10H_ARCH, USB_CAMERA
)
from hailo_apps.python.core.common.camera_utils import get_usb_video_devices
from hailo_apps.python.core.common.hailo_logger import get_logger

logger = get_logger(__name__)

APP_NAME = "my_vlm_app"

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
    # IMPORTANT: Add ALL custom args BEFORE handle_list_models_flag
    # so they appear in --help output
    parser.add_argument("--interval", type=int, default=15, help="Seconds between analyses")
    handle_list_models_flag(parser, APP_NAME)
    args = parser.parse_args()
    hef_path = resolve_hef_path(args.hef_path, app_name=APP_NAME, arch=HAILO10H_ARCH)
    # Camera setup, app.run()

if __name__ == "__main__":
    main()
```

### Step 4: Validate

Run the automated validation script (includes static checks + runtime smoke tests):
```bash
python3 .hailo/scripts/validate_app.py hailo_apps/python/gen_ai_apps/<app_name> --smoke-test
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

## Display & Output Best Practices

### Window Size
The VLM crops images to 336×336 but this is too small for a display window.
Always resize to at least 640×640 for readability:
```python
DISPLAY_SIZE = (640, 640)
display = cv2.resize(frame, DISPLAY_SIZE, interpolation=cv2.INTER_LINEAR)
```

### Text Wrapping
VLM responses can be long (100+ chars). Always wrap overlay text to fit the window:
```python
@staticmethod
def _wrap_text(text: str, max_chars: int = 70) -> list[str]:
    words = text.split()
    lines, current = [], ""
    for word in words:
        if current and len(current) + 1 + len(word) > max_chars:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip() if current else word
    if current:
        lines.append(current)
    return lines or [""]
```
Make the banner height dynamic: `banner_h = 35 + 22 * len(desc_lines)`.

### Print Activity to Terminal
`logger.info()` may not be visible at default log level. Always `print()` event
classifications so the user sees them:
```python
print(f"\n[{event.time_str}] Activity: {event.event_type.value}")
print(f"  {answer}")
```

## Video Playback During Inference (CRITICAL)

**NEVER freeze video playback during VLM inference.** VLM inference takes 10-30 seconds.
Freezing the display makes the app feel broken and wastes most of the video.

The correct pattern for continuous monitoring apps:
- Video keeps playing normally at all times
- Inference runs in a background thread via `ThreadPoolExecutor`
- Track `_inference_pending` flag to avoid submitting overlapping requests
- When inference completes, update the overlay with the result
- The overlay shows the *latest* result while live video continues

Freezing is ONLY appropriate for interactive capture-and-ask apps (like `vlm_chat`)
where the user explicitly presses a key to capture a frame and ask a question.

```python
# ── Main loop: NEVER freeze ───────────────────────────────────
 while self.running:
    raw_frame = get_frame()
    if raw_frame is None:
        # End of video — wait for pending inference, show result 5s
        if vlm_future and not vlm_future.done():
            vlm_future.result(timeout=INFERENCE_TIMEOUT)
        # hold last overlay 5 seconds
        ...
        break

    frame = preprocess(raw_frame)

    # Submit inference on timer (non-blocking)
    if not self._inference_pending and time_elapsed >= self.interval:
        self._inference_pending = True
        vlm_future = self.executor.submit(self._analyze_frame, frame.copy())

    # Check completion (non-blocking)
    if vlm_future and vlm_future.done():
        vlm_future.result()
        vlm_future = None

    # ALWAYS display live frame + overlay
    display = self._draw_overlay(frame)
    cv2.imshow(WINDOW_NAME, display)
    cv2.waitKey(25)
```

## End-of-Video Handling

Short videos (or any file input) will end before inference completes.
The app MUST:
1. Wait for any pending `vlm_future` to finish when `get_frame()` returns `None`
2. Redraw the overlay with the final result AFTER inference completes
3. Hold the final frame on screen for a few seconds so the user can read it

```python
if raw_frame is None:
    if vlm_future and not vlm_future.done():
        logger.info("Video ended. Waiting for pending inference...")
        vlm_future.result(timeout=INFERENCE_TIMEOUT)
    # Show final result for 5 seconds
    if last_good_frame is not None:
        end_time = time.time() + 5
        while time.time() < end_time:
            display = self._draw_overlay(last_good_frame)
            cv2.imshow(WINDOW_NAME, display)
            if cv2.waitKey(100) & 0xFF == ord("q"):
                break
    break
```

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

## Registration Checklist

Community apps do NOT need registration. These steps are only needed after promotion:
1. `hailo_apps/python/core/common/defines.py` — app name constant (e.g. `MY_VLM_APP = "my_vlm_app"`)
2. `hailo_apps/config/resources_config.yaml` — model mapping (e.g. `my_vlm_app: *vlm_chat_app`)


## Lessons Learned (from real builds)

### 1. YAML Alias Placement Breaks Config
When adding `new_app: *vlm_chat_app` to `resources_config.yaml`, inserting it between
an existing key and its `models:` block breaks YAML parsing with a confusing error
referencing a distant line. **Always insert after the full preceding block** and
validate with `yaml.safe_load()`.

### 2. Custom CLI Args Must Come Before handle_list_models_flag()
If you add `parser.add_argument("--interval", ...)` after `handle_list_models_flag()`,
the argument won't appear in `--help` output. The flag handler does `parse_known_args()`
which triggers argparse's help rendering before your arg is registered. Solution:
add all custom arguments **before** calling `handle_list_models_flag()`.

### 3. MAX_TOKENS Too High → Repetitive VLM Output
Qwen2-VL with `MAX_TOKENS=300` on short prompts produces verbose, looping text
(the same sentences repeated). For monitoring apps, use `MAX_TOKENS=100`–`150` and
reinforce brevity in the prompt: `"Be concise — one or two sentences maximum."`

### 4. Event Keyword Classification — First Match Wins
The keyword classifier matches the first `EventType` whose keywords appear in the
response. Generic words ("food", "floor") can trigger the wrong category. Fix by:
- Ordering categories from most-specific to least-specific
- Using specific action verbs ("sniffing", "chewing") instead of nouns
- Or: instruct the VLM to output a single label from a fixed list

### 5. Check Video Duration Before Launch
A 60s video at `--interval 15` with 5-45s inference time yields only 1-2 observations.
Always check the video duration first and set interval accordingly:
```bash
ffprobe -v quiet -show_entries format=duration -of default=noprint_wrappers=1 video.mp4
```

### 6. python3 Not python — Ubuntu Has No `python` Binary
On Ubuntu/Debian, `python` doesn't exist by default. Always use `python3` in
terminal commands and documentation. The `setup_env.sh` activates the venv but
does NOT create a `python` → `python3` alias.

### 7. YAML Edits Fail on Whitespace Mismatches
When editing `resources_config.yaml` with `replace_string_in_file`, the match
must be byte-exact including trailing spaces. If the first attempt fails, re-read
the target lines with `read_file` and copy the exact whitespace. Include 3-5
context lines from the actual file output, not from memory.

### 8. Validation Script Is the Single Gate Check
The `validate_app.py` script runs 11 static checks (file existence, syntax, imports,
conventions, unused imports, unreachable code, README quality). With `--smoke-test`, it also runs 2 runtime checks: CLI `--help` and module
import tests (gracefully skipping on non-Hailo systems). If all checks pass, the app is
convention-compliant. Run it once at the end instead of manual grep checks — it catches everything.

### 9. Auto-Approve Eliminates 46+ Clicks Per Build
Add `"chat.tools.autoApprove": true` to `.vscode/settings.json` for fully
autonomous agentic workflows. Without it, every tool call requires manual approval.

## Common VLM Prompts

| Variant | System Prompt | User Prompt |
|---|---|---|
| Scene monitor | "Monitor the scene. Report activities." | "What is happening in the scene right now?" |
| Safety | "You are a safety inspector." | "List any safety hazards visible" |
| Scene | "Describe what you see concisely." | "Describe the image" |
| Counter | "Count objects precisely. Reply JSON." | "Count all {objects}" |
| Traffic | "Analyze traffic patterns." | "Describe traffic and vehicles" |

