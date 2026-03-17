# Multi-Entrance Tracker

Cross-camera face re-identification tracker for multiple store entrances. Detects faces at each entrance camera using SCRFD, extracts ArcFace embeddings, and matches identities across cameras using a LanceDB vector database. Logs entry/exit events per person as they move between entrances.

## Prerequisites

- **Hardware:** Hailo-8, Hailo-8L, or Hailo-10H
- **Models:** SCRFD (face detection) + ArcFace MobileFaceNet (face recognition)
- **Postprocess:** libscrfd.so, libface_recognition_post.so, libface_align.so, libface_crop.so
- **Dependencies:** lancedb, numpy

Run `hailo-download-resources` and `hailo-compile-postprocess` before first use.

## Usage

```bash
# With video files
python -m hailo_apps.python.pipeline_apps.multi_entrance_tracker.multi_entrance_tracker \
    --sources entrance_cam1.mp4,entrance_cam2.mp4

# Default (uses face_recognition demo video on 2 streams)
python -m hailo_apps.python.pipeline_apps.multi_entrance_tracker.multi_entrance_tracker

# Adjust matching sensitivity (lower = stricter)
python -m hailo_apps.python.pipeline_apps.multi_entrance_tracker.multi_entrance_tracker \
    --sources entrance_cam1.mp4,entrance_cam2.mp4 --match-threshold 0.3
```

## Architecture

```
Entrance Cam 0 -> SOURCE_PIPELINE -> set_stream_id -> robin.sink_0
Entrance Cam 1 -> SOURCE_PIPELINE -> set_stream_id -> robin.sink_1
...

hailoroundrobin (mode=1, round-robin scheduling)
  -> INFERENCE_PIPELINE_WRAPPER (SCRFD face detection, resolution preserved)
    -> TRACKER_PIPELINE (face tracker, class_id=-1)
      -> CROPPER_PIPELINE
           inner: face_align -> ArcFace INFERENCE_PIPELINE (embedding extraction)
           cropper: VMS face crop function
        -> USER_CALLBACK_PIPELINE (unified cross-camera callback)
          -> hailostreamrouter
            router.src_0 -> per-entrance ReID callback -> DISPLAY_PIPELINE (Entrance 0)
            router.src_1 -> per-entrance ReID callback -> DISPLAY_PIPELINE (Entrance 1)
```

## Output

- **Multi-panel display:** One window per entrance camera, showing face detections with cross-camera identity labels
- **Console logs:** Cross-camera matches, per-entrance unique face counts, entry/exit events
- **Entry/exit log:** Internal list of timestamped events tracking person movements between entrances

## Customization

- **Add more entrances:** Pass additional sources via `--sources cam1,cam2,cam3,cam4`
- **Adjust matching:** Use `--match-threshold` to control identity matching sensitivity
- **Resolution:** Use `--width` and `--height` (default: 640x640)
- **Database:** Persists in `database/` subdirectory; delete to reset identities
