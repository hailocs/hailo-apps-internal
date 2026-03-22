# Dog Monitor — Continuous Pet Activity Tracker

## Description

A continuous monitoring application using Hailo-10H VLM to watch a home camera and
track dog activities in real time. Built on the VLM Chat Backend for hardware-accelerated
vision-language inference.

The app captures frames at configurable intervals, analyzes them with a VLM prompt
optimized for pet activity recognition, classifies the response into activity categories,
and maintains a running session summary.

## Requirements

- Hailo-10H accelerator
- USB or RPi camera
- Python 3.10+
- hailo_platform SDK with genai support

## Usage

**Basic monitoring (USB camera, 10s interval):**
```bash
python -m hailo_apps.python.gen_ai_apps.dog_monitor_orch.dog_monitor --input usb
```

**With event frame saving:**
```bash
python -m hailo_apps.python.gen_ai_apps.dog_monitor_orch.dog_monitor --input usb --save-events --events-dir ./dog_events
```

**Custom interval (every 5 seconds):**
```bash
python -m hailo_apps.python.gen_ai_apps.dog_monitor_orch.dog_monitor --input usb --interval 5
```

**Headless mode (no display window):**
```bash
python -m hailo_apps.python.gen_ai_apps.dog_monitor_orch.dog_monitor --input usb --no-display --interval 10
```

**RPi camera:**
```bash
python -m hailo_apps.python.gen_ai_apps.dog_monitor_orch.dog_monitor --input rpi --interval 15
```

## CLI Arguments

| Argument | Type | Default | Description |
|---|---|---|---|
| `--input` / `-i` | str | — | Input source: `usb`, `rpi`, file path, or RTSP URL |
| `--interval` | int | 10 | Seconds between VLM analysis frames |
| `--save-events` | flag | off | Save frames when notable events are detected |
| `--events-dir` | str | `./dog_events` | Directory to save event frames |
| `--no-display` | flag | off | Run without OpenCV display window |
| `--hef-path` / `-n` | str | auto | HEF model path (auto-resolved if omitted) |

## Activity Categories

| Category | Keywords Detected |
|---|---|
| DRINKING | drink, water, bowl |
| EATING | eat, food, kibble, chew |
| SLEEPING | sleep, rest, nap, lying, lay |
| PLAYING | play, toy, fetch, run, jump |
| BARKING | bark, alert, growl, whine |
| AT_DOOR | door, wait, entrance, exit |
| NO_DOG | no dog, empty, not visible |
| IDLE | (default — no keyword match) |

## Architecture

```
Camera → [capture every N seconds] → VLM Backend → EventTracker → Display + Log
```

- **Backend**: Reused from `vlm_chat` — spawns a worker process with `VDevice` + `VLM` for inference
- **EventTracker**: Keyword-based classification of VLM responses into activity categories
- **Display**: Real-time camera feed with overlay showing last event and activity counts
- **Summary**: Session summary printed on exit (Ctrl+C) with activity breakdown

## Files

| File | Lines | Purpose |
|---|---|---|
| `dog_monitor.py` | ~240 | Main app: camera loop, VLM inference, display overlay |
| `event_tracker.py` | ~120 | EventType enum, Event dataclass, EventTracker class |
| `README.md` | — | This documentation |
