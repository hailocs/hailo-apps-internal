# Baby Sleep Monitor

Real-time baby sleep position monitoring using pose estimation. Analyzes body keypoints to detect unsafe sleeping positions (face-down, twisted, side-lying) and alerts with an on-screen status banner and a logged warning. (See "Audio alerts" below — audible alerts require extra setup.)

## How It Works

The app uses YOLOv8-pose to detect body keypoints (17 COCO keypoints) on a sleeping baby. The callback analyzes the spatial relationships between key body parts (nose, eyes, shoulders, hips) to classify the sleeping position as:

- **SAFE** (green): Baby is on their back (supine), face clearly visible
- **WARNING** (yellow): Ambiguous position, partial side-lying, or one eye hidden
- **DANGER** (red): Face-down (prone), nose/eyes not visible, or body significantly twisted

When a DANGER state persists for more than 3 seconds, an alert is raised: an `ALERT!` indicator on the status banner and a `WARNING`-level log message.

## Audio alerts

Out of the box the app does **not** play any sound — the previous terminal-bell approach (`"\a"`) is silent under most desktop/GUI environments, so it has been removed in favor of a clear log warning. To get an audible alert you need extra setup: wire real audio playback into `BabySleepCallbackData._trigger_audio_alert()` in `baby_sleep_monitor.py` (e.g. `playsound`, `simpleaudio`, or a `subprocess` call to `aplay`/`paplay` with your own sound file), and install the corresponding dependency.

## Prerequisites

- Hailo-8 accelerator (also works on Hailo-8L and Hailo-10H)
- USB camera (baby monitor camera)
- Pose estimation model and postprocess plugin:
  ```bash
  hailo-download-resources
  hailo-compile-postprocess
  ```

## Usage

```bash
# With USB camera (default)
python community/apps/pipeline_apps/baby_sleep_monitor/baby_sleep_monitor.py --input usb

# With a video file for testing
python community/apps/pipeline_apps/baby_sleep_monitor/baby_sleep_monitor.py --input test_video.mp4

# Show FPS counter
python community/apps/pipeline_apps/baby_sleep_monitor/baby_sleep_monitor.py --input usb --show-fps

# With frame access for overlay drawing
python community/apps/pipeline_apps/baby_sleep_monitor/baby_sleep_monitor.py --input usb --use-frame
```

## Pipeline Architecture

```
USB Camera -> SOURCE_PIPELINE
               |
               v
           INFERENCE_PIPELINE_WRAPPER(INFERENCE_PIPELINE)  [YOLOv8-pose, resolution preserved]
               |
               v
           TRACKER_PIPELINE(class_id=0)  [Track person detections]
               |
               v
           USER_CALLBACK_PIPELINE  [Analyze pose, classify sleep position, trigger alerts]
               |
               v
           DISPLAY_PIPELINE  [Show video with status overlay]
```

## Customization

- **Alert threshold**: Modify `danger_threshold_seconds` in `BabySleepCallbackData.__init__()` to change how long a danger state must persist before alerting (default: 3 seconds).
- **Position analysis**: Tune the twist ratio thresholds and nose position checks in `analyze_sleep_position()` for your camera angle and baby size.
- **Audio alert**: See the "Audio alerts" section above — add real audio playback in `_trigger_audio_alert()` for an audible production alert.
- **Model selection**: Use `--hef-path` to specify a different pose model, or `--list-models` to see available options.

## Based On

This app is built from the **pose_estimation** template app, using the same pipeline pattern (source -> inference wrapper -> tracker -> callback -> display) with custom sleep position analysis logic in the callback.
