# Room Security Monitor

## What This App Does
Door-camera security app using SCRFD face detection + ArcFace recognition. Recognizes authorized people, triggers an alarm on unknown faces, and logs all access events to CSV. Supports live face enrollment (Tkinter UI or terminal commands) and batch training.

## Architecture
- **Type:** Pipeline app (face recognition)
- **Pattern:** Camera → SCRFD detection → ByteTrack tracker → face crop + ArcFace embedding → LanceDB vector search → callback (event log + enrollment)
- **Models:** SCRFD face detection + ArcFace MobileFaceNet recognition
- **Hardware:** hailo8, hailo8l, hailo10h
- **Postprocess:** Arch-specific C++ `.so`: SCRFD detect (`...scrfd_10g` / `...scrfd_2_5g`), face align, face crop, face recognition

## Key Files
| File | Purpose |
|------|---------|
| `room_security_monitor.py` | Entry point + callback: enrollment logic, alarm trigger, CSV logging |
| `room_security_monitor_pipeline.py` | `GStreamerApp` subclass: SCRFD + cropper + ArcFace, multi-model HEF resolution, DB init |
| `enrollment_ui.py` | Tkinter enrollment panel (when `--ui` is used) |
| `security_algo_params.json` | Tuning: alarm cooldown, confidence threshold, frame-skip rate |

## How to Run
```bash
source setup_env.sh
python community/apps/pipeline_apps/room_security_monitor/room_security_monitor.py --input usb --ui
# terminal enrollment (no UI): --input usb   (then use 'e','s','l','db' commands)
# batch enroll: --mode train
```

## How to Extend
- Override the alarm trigger in the callback class to send GPIO/HTTP/MQTT instead of console output.
- Adjust the vector-search confidence threshold in `security_algo_params.json` (default 0.5) to trade precision vs recall.
