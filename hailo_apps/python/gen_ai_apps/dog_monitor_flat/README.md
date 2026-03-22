# Dog Monitor (Flat Build)

Continuous pet-monitoring application powered by the Hailo-10H VLM. The app captures camera frames at a configurable interval, classifies dog activities (drinking, eating, sleeping, playing, barking, waiting at the door, etc.), and maintains a timestamped event log. On exit it prints a full session summary.

## Requirements

- **Hailo-10H** accelerator with HailoRT and `hailo_platform` SDK installed
- USB or Raspberry Pi camera
- Python 3.10+

## Usage

### Basic — USB camera, 10-second interval

```bash
python -m hailo_apps.python.gen_ai_apps.dog_monitor_flat.dog_monitor --input usb
```

### Save event frames to disk

```bash
python -m hailo_apps.python.gen_ai_apps.dog_monitor_flat.dog_monitor --input usb --save-events --events-dir ./dog_events
```

### Custom capture interval (5 seconds)

```bash
python -m hailo_apps.python.gen_ai_apps.dog_monitor_flat.dog_monitor --input usb --interval 5
```

### Raspberry Pi camera

```bash
python -m hailo_apps.python.gen_ai_apps.dog_monitor_flat.dog_monitor --input rpi
```

## CLI Arguments

| Flag | Default | Description |
|---|---|---|
| `--input` / `-i` | — | Input source (`usb`, `rpi`, or device path) |
| `--interval` | `10` | Seconds between automatic frame analyses |
| `--save-events` | off | Save frames when interesting events are detected |
| `--events-dir` | `./dog_events` | Directory for saved event frames |
| `--hef-path` / `-n` | auto | Path or name of VLM HEF model |
| `--list-models` | — | List available models and exit |

## Sample Output

```
══════════════════════════════════════════════════════════════
  DOG MONITOR — Continuous monitoring started
  Interval: 10s | Save events: False
  Press Ctrl+C to stop and see session summary
══════════════════════════════════════════════════════════════

[2026-03-19 14:00:10] SLEEPING: The dog is curled up on the couch, sleeping peacefully.
[2026-03-19 14:00:20] SLEEPING: The dog is still resting on the couch with eyes closed.
[2026-03-19 14:00:30] DRINKING: The dog is drinking water from its bowl in the kitchen.
[2026-03-19 14:00:40] IDLE: The dog is sitting on the floor looking around the room.
^C

════════════════════════════════════════════════════════════
  DOG MONITOR — Session Summary
════════════════════════════════════════════════════════════
  Duration:       00:00:40
  Total events:   4
────────────────────────────────────────────────────────────
  Activity Counts:
    SLEEPING      2
    DRINKING      1
    IDLE          1
────────────────────────────────────────────────────────────
  Event Log (last 20):
    [2026-03-19 14:00:10] SLEEPING     The dog is curled up on the couch, sleeping peacefully.
    [2026-03-19 14:00:20] SLEEPING     The dog is still resting on the couch with eyes closed.
    [2026-03-19 14:00:30] DRINKING     The dog is drinking water from its bowl in the kitchen.
    [2026-03-19 14:00:40] IDLE         The dog is sitting on the floor looking around the room.
════════════════════════════════════════════════════════════
```

## Architecture

The app reuses the `Backend` class from `hailo_apps.python.gen_ai_apps.vlm_chat.backend`, which runs VLM inference in a dedicated worker process using `SHARED_VDEVICE_GROUP_ID` for device sharing. The `EventTracker` module handles keyword-based classification and session statistics.
