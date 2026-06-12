# Re-ID Multisource

## What This App Does
Cross-camera person re-identification (ReID) that tracks and identifies the same person across multiple video streams. It combines face detection (SCRFD), face alignment, face recognition (ArcFace MobileFaceNet), and a vector database to assign consistent global identities to people seen across different cameras. When a face is detected and recognized in one stream, the same person appearing in another stream receives the same identity label.

This is the most complex multi-stream pipeline, combining the round-robin/stream-router pattern from `multisource` with the cascaded face detection and recognition from `face_recognition`, plus cross-stream identity matching via LanceDB.

## Architecture
- **Type:** Pipeline app (multi-stream, cascaded multi-model)
- **Pattern:** N sources -> roundrobin -> detection_wrapper -> tracker -> cropper(face_align + recognition) -> callback -> streamrouter -> N per-source callbacks -> N displays
- **Models:**
  - hailo8: `scrfd_10g` (face detection) + `arcface_mobilefacenet` (recognition)
  - hailo8l: `scrfd_2.5g` (face detection) + `arcface_mobilefacenet` (recognition)
  - hailo10h: `scrfd_10g` (face detection) + `arcface_mobilefacenet` (recognition)
- **Hardware:** hailo8, hailo8l, hailo10h
- **Postprocess:** Multiple .so files -- SCRFD detection, face alignment, face cropping (VMS), face recognition, all-detections cropper

## Key Files
| File | Purpose |
|------|---------|
| `reid_multisource.py` | Main entry point, unified callback printing stream_id + label + track_id |
| `reid_multisource_pipeline.py` | `GStreamerREIDMultisourceApp` with full cascaded multi-stream pipeline |

## Pipeline Structure
```
SOURCE_PIPELINE("source_0") -> hailofilter(set_stream_id) -> robin.sink_0
SOURCE_PIPELINE("source_1") -> hailofilter(set_stream_id) -> robin.sink_1
...

hailoroundrobin(mode=1) name=robin
  -> INFERENCE_PIPELINE_WRAPPER(SCRFD face detection)
    -> TRACKER_PIPELINE(class_id=-1, name="hailo_face_tracker")
      -> CROPPER_PIPELINE(
           inner: face_align hailofilter -> ArcFace INFERENCE_PIPELINE
           cropper: VMS cropper function
         )
        -> USER_CALLBACK_PIPELINE (unified)
          -> hailostreamrouter name=router
            router.src_0 -> per-source ReID callback -> DISPLAY_PIPELINE("hailo_display_0")
            router.src_1 -> per-source ReID callback -> DISPLAY_PIPELINE("hailo_display_1")
```

Key parameters:
- Default resolution: 640x640
- Frame rate: 12 FPS on RPi, 15 FPS on other hosts
- Vector search threshold: 0.1 (very permissive for cross-camera matching)
- Per-source callbacks dynamically generated and connected via `handoff` signal
- Database: LanceDB `cross_tracked.db` stored locally
- Default: 2 sources (uses face_recognition.mp4 duplicated)

## Callback Data Available

**Unified callback:**
```python
roi = hailo.get_roi_from_buffer(buffer)
stream_id = roi.get_stream_id()
detections = roi.get_objects_typed(hailo.HAILO_DETECTION)
for detection in detections:
    ids = detection.get_objects_typed(hailo.HAILO_UNIQUE_ID)
    track_id = ids[0].get_id() if ids else 0
```

**Per-source ReID callbacks (internal, connected automatically):**
```python
# Each detection gets face embedding matched against LanceDB
embedding = detection.get_objects_typed(hailo.HAILO_MATRIX)
embedding_vector = np.array(embedding[0].get_data())
# Creates HAILO_CLASSIFICATION with type=REID_CLASSIFICATION_TYPE
# label format: "src_N, <original_creation_label>"
```

## Common Use Cases
- Cross-camera person tracking in buildings or campuses
- Visitor flow analysis across multiple entrances
- Retail analytics tracking customers across store zones
- Security monitoring identifying the same person across cameras
- Smart city pedestrian tracking

## How to Extend
- **Add more cameras:** Use `--sources /dev/video0,/dev/video1,rtsp://...` (comma-separated)
- **Adjust matching sensitivity:** Modify `lance_db_vector_search_classificaiton_confidence_threshold` (currently 0.1)
- **Swap models:** Use `--hef-path <det.hef> --hef-path <rec.hef>` (order: detection first, recognition second)
- **Change resolution:** Use `--width 640 --height 640` (defaults already set)
- **Persistent database:** The LanceDB database persists in the `database/` subdirectory

## Related Apps
| App | When to use instead |
|-----|-------------------|
| multisource | If you only need detection (not face recognition) across multiple streams |
| face_recognition | If you have a single camera and need face identification |
| detection | If you only need single-stream object detection |
