# Workout Rep Counter

Real-time exercise repetition counter using YOLOv8 pose estimation on the Hailo-8 accelerator. The app detects body keypoints, computes joint angles for the selected exercise, and counts reps by tracking the up/down phases of each movement.

## Supported Exercises

| Exercise    | Tracked Joint Angle            | Down Phase | Up Phase |
|-------------|--------------------------------|------------|----------|
| Squat       | Hip-Knee-Ankle                 | <= 90 deg  | >= 160 deg |
| Pushup      | Shoulder-Elbow-Wrist           | <= 90 deg  | >= 160 deg |
| Bicep Curl  | Shoulder-Elbow-Wrist           | <= 40 deg  | >= 160 deg |

## Prerequisites

- Hailo-8 accelerator
- YOLOv8 pose model HEF (downloaded via `hailo-download-resources`)
- Pose estimation postprocess plugin (compiled via `hailo-compile-postprocess`)
- USB camera or video file

## How to Run

```bash
# Activate environment
source setup_env.sh

# Run with USB camera (default exercise: squat)
python community/apps/pipeline_apps/workout_rep_counter/workout_rep_counter.py --input usb

# Run with video file
python community/apps/pipeline_apps/workout_rep_counter/workout_rep_counter.py --input path/to/workout.mp4

# Run with frame overlay (shows angle + rep count on OpenCV window)
python community/apps/pipeline_apps/workout_rep_counter/workout_rep_counter.py --input usb --use-frame
```

## Architecture

```
USB Camera
    |
    v
SOURCE_PIPELINE
    |
    v
INFERENCE_PIPELINE_WRAPPER(INFERENCE_PIPELINE)   # YOLOv8-pose at model res, display at full res
    |
    v
TRACKER_PIPELINE(class_id=0)                     # Track persons across frames
    |
    v
USER_CALLBACK_PIPELINE                           # Extract keypoints, compute angles, count reps
    |
    v
DISPLAY_PIPELINE                                 # Show skeleton overlay + stats
```

## Customization

- **Add exercises:** Define new entries in the `EXERCISES` dictionary in `workout_rep_counter.py` with three keypoints and angle thresholds.
- **Change exercise at runtime:** Modify `user_data.exercise` before or during the callback (e.g., via a keyboard listener on a separate thread).
- **Tune thresholds:** Adjust `down_angle` and `up_angle` values per exercise for your camera angle and body proportions.
- **Multi-person support:** The app already tracks multiple persons via track IDs. Each person gets independent rep counts.
