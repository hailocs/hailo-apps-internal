# Face Recognition

## What This App Does
A cascaded face detection and recognition pipeline that identifies known individuals in real-time. It uses a two-stage approach: first detecting faces with SCRFD, then cropping each face and running ArcFace embeddings through a MobileFaceNet recognition model. Face embeddings are compared against a LanceDB vector database to identify people. The app supports three modes: `run` (real-time recognition), `train` (enroll new faces from images), and `delete` (clear the database).

This is the most architecturally complex pipeline app in the repository, demonstrating cascaded networks, cropper pipelines, vector database integration, tracker manipulation, and optional Telegram notifications.

## Architecture
- **Type:** Pipeline app (cascaded multi-model)
- **Pattern:** source -> detection_wrapper -> tracker -> cropper(face_align + recognition) -> vector_db_callback -> user_callback -> display
- **Models:**
  - hailo8: `scrfd_10g` (face detection) + `arcface_mobilefacenet` (recognition)
  - hailo8l: `scrfd_2.5g` (face detection) + `arcface_mobilefacenet` (recognition)
  - hailo10h: `scrfd_10g` (face detection) + `arcface_mobilefacenet` (recognition)
- **Hardware:** hailo8, hailo8l, hailo10h
- **Postprocess:** Multiple .so files -- face detection (scrfd), face alignment, face cropping, face recognition

## Key Files
| File | Purpose |
|------|---------|
| `face_recognition.py` | Main entry point, callback printing recognized names, mode dispatcher |
| `face_recognition_pipeline.py` | `GStreamerFaceRecognitionApp` with cascaded pipeline, DB callbacks, training logic |
| `face_recon_algo_params.json` | Algorithm parameters (skip_frames, confidence threshold, batch_size) |
| `train/` | Directory for training images (subfolders named by person) |
| `samples/` | Stored face crop samples |
| `database/` | LanceDB vector database files |

## Pipeline Structure
```
SOURCE_PIPELINE
  -> INFERENCE_PIPELINE_WRAPPER(SCRFD face detection)
    -> TRACKER_PIPELINE(class_id=-1, keep_past_metadata=True)
      -> CROPPER_PIPELINE(
           inner: face_align hailofilter -> ArcFace INFERENCE_PIPELINE
           cropper: face_recognition function
         )
        -> USER_CALLBACK_PIPELINE("vector_db_callback")  # vector DB search
          -> USER_CALLBACK_PIPELINE("identity_callback")  # user callback
            -> DISPLAY_PIPELINE
```

In training mode, `multifilesrc` replaces the source pipeline, and a different callback handles embedding storage.

Key parameters:
- Tracker: `kalman_dist_thr=0.7`, `iou_thr=0.8`, `init_iou_thr=0.9`, `keep_past_metadata=True`
- Skip frames before recognition (configurable in JSON)
- Vector search confidence threshold from `face_recon_algo_params.json`
- Multi-model: uses `--hef-path` with `action='append'` for two HEF files

## Callback Data Available
```python
roi = hailo.get_roi_from_buffer(buffer)
detections = roi.get_objects_typed(hailo.HAILO_DETECTION)
for detection in detections:
    if detection.get_label() == "face":
        track = detection.get_objects_typed(hailo.HAILO_UNIQUE_ID)
        track_id = track[0].get_id() if track else 0
        classifications = detection.get_objects_typed(hailo.HAILO_CLASSIFICATION)
        # classification.get_label() = person name or "Unknown"
        # classification.get_confidence() = recognition confidence
        embedding = detection.get_objects_typed(hailo.HAILO_MATRIX)
        # embedding[0].get_data() = 512-dim face embedding vector
```

## Common Use Cases
- Access control and visitor identification
- Attendance tracking systems
- VIP recognition for hospitality
- Security alerting with Telegram integration
- Multi-camera person identification (see reid_multisource)

## How to Extend
- **Train new faces:** Place face images in `train/<person_name>/` subdirectories, run with `--mode train`
- **Clear database:** Run with `--mode delete`
- **Telegram alerts:** Set `TELEGRAM_ENABLED=True` with token and chat ID in `face_recognition.py`
- **Adjust sensitivity:** Edit `face_recon_algo_params.json` -- lower `lance_db_vector_search_classificaiton_confidence_threshold` for stricter matching
- **Swap detection model:** Use `--hef-path <det.hef> --hef-path <rec.hef>` (order matters: detection first, recognition second)

## Related Apps
| App | When to use instead |
|-----|-------------------|
| detection | If you only need to detect people without identifying them |
| reid_multisource | If you need cross-camera person re-identification across multiple streams |
| clip | If you need to match faces/objects to text descriptions |
