# Room Security Monitor

A door-camera security application built on the face recognition pipeline. It monitors a USB camera feed in real-time, recognizes authorized personnel via SCRFD face detection + ArcFace embeddings, and triggers an alarm when an unknown person is detected. All access events (authorized and unknown) are logged to a CSV file.

## Prerequisites

- **Hardware:** Hailo-8 (also supports Hailo-8L and Hailo-10H)
- **Models:** SCRFD face detection + ArcFace MobileFaceNet recognition (downloaded via `hailo-download-resources`)
- **Postprocess plugins:** Compiled via `hailo-compile-postprocess`
- **Python dependencies:** Standard hailo-apps-infra environment (`source setup_env.sh`)

## How to Run

### 1. Train authorized faces

Place face images in subdirectories named after each person:

```
community/apps/pipeline_apps/room_security_monitor/train/
    alice/
        photo1.jpg
        photo2.jpg
    bob/
        photo1.jpg
```

Then run:

```bash
python community/apps/pipeline_apps/room_security_monitor/room_security_monitor.py --mode train
```

### 2. Start monitoring

```bash
# With USB camera (default)
python community/apps/pipeline_apps/room_security_monitor/room_security_monitor.py --input usb

# With video file
python community/apps/pipeline_apps/room_security_monitor/room_security_monitor.py --input path/to/video.mp4
```

### 3. Clear the database

```bash
python community/apps/pipeline_apps/room_security_monitor/room_security_monitor.py --mode delete
```

## Architecture

```
USB Camera
  -> SOURCE_PIPELINE
    -> INFERENCE_PIPELINE_WRAPPER(SCRFD face detection)
      -> TRACKER_PIPELINE(face tracker with metadata persistence)
        -> CROPPER_PIPELINE(face alignment + ArcFace recognition)
          -> USER_CALLBACK_PIPELINE(vector DB search & classification)
            -> USER_CALLBACK_PIPELINE(alarm logic & access logging)
              -> DISPLAY_PIPELINE (live view with face labels)
```

## Output

- **Live display:** Bounding boxes around faces with recognized names or "Unknown" labels
- **Console:** Real-time log of authorized entries and alarm events
- **Access log:** `access_log.csv` with timestamp, track ID, name, confidence, and event type
- **Alarm:** Console alert for unknown faces (configurable cooldown to avoid spam)

## Customization

- **Alarm integration:** Override `SecurityCallbackClass.trigger_alarm()` to connect to GPIO, webhooks, or MQTT
- **Confidence threshold:** Edit `security_algo_params.json` (`lance_db_vector_search_classificaiton_confidence_threshold`)
- **Alarm cooldown:** Edit `security_algo_params.json` (`unknown_alarm_cooldown_seconds`) or pass at runtime
- **Skip frames:** Edit `security_algo_params.json` (`skip_frames`) to control how many frames to skip before first recognition attempt

## Based On

This app is built from the `face_recognition` template. See `community/apps/pipeline_apps/face_recognition/` for the original implementation.
