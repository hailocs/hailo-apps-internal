# Visual Quality Inspector

A visual quality inspection application that uses Hailo's Vision Language Model (VLM) to analyze manufactured parts captured from a camera and describe any defects found in natural language.

## Features

- **On-demand image capture** from USB or RPi camera
- **AI-powered defect detection** using Qwen2-VL-2B-Instruct VLM on Hailo-10H
- **Natural language defect descriptions** including type, severity, and location
- **PASS/FAIL assessment** for each inspected part
- **Optional JSONL log file** for recording inspection results over time
- **Non-blocking interface** with live video preview and state-machine interaction

## Requirements

- Hailo-10H AI accelerator
- Python >= 3.10
- OpenCV, NumPy
- Hailo Platform SDK with GenAI support (`pip install -e ".[gen-ai]"`)
- USB camera or Raspberry Pi camera

## Architecture

```
USB Camera --> OpenCV capture --> [User presses Enter] --> Freeze frame
    --> VLM Backend (separate process) --> Qwen2-VL-2B-Instruct
    --> Natural language defect report --> Display + optional log file
```

The app uses a state machine with four states:
1. **STREAMING** - Live camera feed, waiting for capture
2. **CAPTURED** - Frame frozen, user types inspection prompt (or uses default)
3. **PROCESSING** - VLM analyzes the image for defects
4. **RESULT** - Defect report displayed, press Enter to continue

## Usage

```bash
# Basic usage with USB camera
python -m hailo_apps.python.gen_ai_apps.visual_quality_inspector.visual_quality_inspector --input usb

# With Raspberry Pi camera
python -m hailo_apps.python.gen_ai_apps.visual_quality_inspector.visual_quality_inspector --input rpi

# With inspection logging to file
python -m hailo_apps.python.gen_ai_apps.visual_quality_inspector.visual_quality_inspector --input usb --log-file inspections.jsonl
```

## Interactive Mode

1. The app shows a live camera feed in a window
2. Position the manufactured part in view
3. Press **Enter** (in terminal) to capture the image
4. Type a specific question or press **Enter** for the default inspection prompt
5. Wait for the VLM to analyze and describe any defects
6. Press **Enter** to return to live video for the next part
7. Press **q** to quit

## Configuration

Modify constants in `visual_quality_inspector.py`:

- `MAX_TOKENS` (300) - Maximum response length for defect descriptions
- `TEMPERATURE` (0.1) - Low temperature for consistent, precise descriptions
- `SYSTEM_PROMPT` - Quality inspection context for the VLM
- `DEFAULT_INSPECTION_PROMPT` - Default prompt when user presses Enter without typing
- `SAVE_FRAMES` (False) - Set to True to save captured frames to disk
- `INFERENCE_TIMEOUT` (60) - Timeout in seconds for VLM inference

## Log File Format

When `--log-file` is specified, each inspection is appended as a JSON line:

```json
{"inspection_id": 1, "timestamp": "2026-03-17T10:30:00", "prompt": "Inspect this manufactured part...", "result": "FAIL. The part shows...", "inference_time": "3.45 seconds"}
```

## Files

| File | Purpose |
|------|---------|
| `visual_quality_inspector.py` | Main application with state machine, camera handling, CLI args, logging |
| `backend.py` | VLM backend with multiprocessing worker, image preprocessing |

## Customization

- **Different inspection prompts**: Modify `SYSTEM_PROMPT` and `DEFAULT_INSPECTION_PROMPT` for your specific part types
- **Image preprocessing**: Modify `Backend.convert_resize_image()` for different crop/resize strategies
- **Save frames**: Set `SAVE_FRAMES = True` to keep captured images for record-keeping
- **Automated inspection**: Extend the state machine to auto-capture at intervals instead of manual trigger
