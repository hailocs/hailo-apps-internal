# Workout Rep Counter

## What This App Does
Real-time exercise repetition counter using YOLOv8 pose estimation. Computes the relevant joint angle for the selected exercise (squat, pushup, bicep curl), detects up/down phase transitions, and counts reps per tracked person.

## Architecture
- **Type:** Pipeline app
- **Pattern:** Pose estimation + ByteTrack → callback (joint-angle computation + phase state machine) → display
- **Models:** YOLOv8 pose (HEF resolved per architecture via the pose pipeline helper)
- **Hardware:** hailo8, hailo8l, hailo10h
- **Postprocess:** C++ `libyolov8_pose_postprocess.so` + Python callback

## Key Files
| File | Purpose |
|------|---------|
| `workout_rep_counter.py` | Entry point + callback: keypoint extraction, angle via law of cosines, per-track rep state machine, overlay |
| `workout_rep_counter_pipeline.py` | `GStreamerApp` subclass with the `--exercise` selection arg |

## How to Run
```bash
source setup_env.sh
python community/apps/pipeline_apps/workout_rep_counter/workout_rep_counter.py --input usb --use-frame
```
Optional: `--exercise squat|pushup|bicep_curl`, `--input path/to/video.mp4`.

## How to Extend
- Add exercises by extending the `EXERCISES` dict (joint triplet + angle thresholds).
- Add a keyboard listener thread to switch exercises at runtime instead of fixing it at startup.
