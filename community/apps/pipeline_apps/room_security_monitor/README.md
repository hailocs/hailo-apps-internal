# Room Security Monitor

A door-camera security application built on the face recognition pipeline. It monitors a USB camera feed in real-time, recognizes authorized personnel via SCRFD face detection + ArcFace embeddings, and triggers an alarm when an unknown person is detected. All access events (authorized and unknown) are logged to a CSV file.

**Real-time face enrollment** — enroll unknown faces directly from the live camera feed without stopping the pipeline. Use the graphical panel (`--ui`) or terminal commands to add faces instantly.

## Prerequisites

- **Hardware:** Hailo-8 (also supports Hailo-8L and Hailo-10H)
- **Models:** SCRFD face detection + ArcFace MobileFaceNet recognition (downloaded via `hailo-download-resources`)
- **Postprocess plugins:** Compiled via `hailo-compile-postprocess`
- **Python dependencies:** Standard hailo-apps environment (`source setup_env.sh`)

## How to Run

### 1. Start monitoring with graphical enrollment (recommended)

```bash
# With USB camera + enrollment UI panel
python community/apps/pipeline_apps/room_security_monitor/room_security_monitor.py --input usb --ui
```

The `--ui` flag opens a **graphical enrollment panel** alongside the video window:
- **Unknown Faces** section shows thumbnails of unrecognized people
- Click "Select" on a face, type a name, click "Add Person"
- **Known People** section lists enrolled persons with "Add Photo" buttons
- After enrollment, the face is immediately re-classified with the new name
- **"Clear All Data"** button wipes the database, training images, and samples (with confirmation)

### 1b. Terminal mode (alternative)

```bash
# Without UI — terminal-based enrollment
python community/apps/pipeline_apps/room_security_monitor/room_security_monitor.py --input usb
```

```
>> e Alice          # Enroll the latest unknown face as "Alice"
>> e 5 Bob          # Enroll specific track ID 5 as "Bob"
>> s Alice          # Add another sample for "Alice"
>> l                # List currently visible faces
>> db               # List all persons in the database
>> h / q            # Help / Quit
```

**Enrollment flow (both modes):**
1. An unknown face appears on camera (red "Unknown" label in video)
2. Enroll via UI panel or terminal command
3. The face crop is saved to `train/<name>/` and added to the database
4. The overlay immediately updates to show the person's name

**Adding more samples:**
- More samples improve recognition accuracy (the system averages embeddings)
- UI: click "+ Add Photo" next to a known person
- Terminal: type `s <name>` when the person is visible

### 2. Batch train authorized faces (offline)

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

### 3. Clear all data

**From the UI:** Click "Clear All Data" at the bottom of the enrollment panel. A confirmation dialog appears. This deletes the database, all training images, and all samples.

**From the command line:**
```bash
python community/apps/pipeline_apps/room_security_monitor/room_security_monitor.py --mode delete
```
Note: `--mode delete` clears the database and samples but does not remove training images from `train/`. The UI button clears everything.

## Architecture

```
USB Camera
  -> SOURCE_PIPELINE
    -> INFERENCE_PIPELINE_WRAPPER(SCRFD face detection)
      -> TRACKER_PIPELINE(face tracker with metadata persistence)
        -> CROPPER_PIPELINE(face alignment + ArcFace recognition)
          -> USER_CALLBACK_PIPELINE(vector DB search & classification + enrollment capture)
            -> USER_CALLBACK_PIPELINE(alarm logic & access logging)
              -> DISPLAY_PIPELINE (live view with face labels)

Enrollment (parallel, choose one):
  Option A: --ui flag → Tkinter panel (face thumbnails, name entry, buttons)
  Option B: Terminal thread (type commands: e/s/l/db/h/q)
  Both write face crops to train/<name>/ and update LanceDB
```

## Output

- **Live display:** Bounding boxes around faces with recognized names or "Unknown" labels
- **Console:** Real-time log of authorized entries and alarm events
- **Access log:** `access_log.csv` with timestamp, track ID, name, confidence, and event type
- **Alarm:** Console alert for unknown faces (configurable cooldown to avoid spam)
- **Training data:** Face crops auto-saved to `train/<name>/` when enrolled from the live feed

## Directory Structure

```
room_security_monitor/
├── room_security_monitor.py           # Callback + enrollment logic + main
├── room_security_monitor_pipeline.py  # GStreamer pipeline + vector DB callbacks
├── enrollment_ui.py                   # Tkinter enrollment panel (--ui flag)
├── security_algo_params.json          # Algorithm parameters
├── README.md
├── train/                             # Training images (auto-populated during enrollment)
│   ├── alice/
│   │   ├── <uuid>.jpeg               # Enrolled from live feed
│   │   └── photo1.jpg                # Manually placed
│   └── bob/
│       └── <uuid>.jpeg
├── samples/                           # Cropped face samples (auto-generated)
└── database/                          # LanceDB vector database
    └── persons.db
```

## Customization

- **Alarm integration:** Override `SecurityCallbackClass.trigger_alarm()` to connect to GPIO, webhooks, or MQTT
- **Confidence threshold:** Edit `security_algo_params.json` (`lance_db_vector_search_classificaiton_confidence_threshold`)
- **Alarm cooldown:** Edit `security_algo_params.json` (`unknown_alarm_cooldown_seconds`) or pass at runtime
- **Skip frames:** Edit `security_algo_params.json` (`skip_frames`) to control how many frames to skip before first recognition attempt

## Based On

This app is built from the `face_recognition` template. See `hailo_apps/python/pipeline_apps/face_recognition/` for the original implementation.
