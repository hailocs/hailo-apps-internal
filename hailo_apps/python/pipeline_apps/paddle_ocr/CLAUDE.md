# Paddle OCR

## What This App Does
Real-time Optical Character Recognition (OCR) using a two-stage pipeline: first detecting text regions in the video frame, then cropping each text region and running character recognition on it. Built on PaddleOCR models compiled for Hailo, with a text detection model (`ocr_det`) finding text bounding boxes and a recognition model (`ocr`) reading the characters within each detected region. The pipeline includes tracking to maintain text region identities across frames.

The callback demonstrates parsing OCR results, filtering by confidence, and optionally rendering detected text with bounding boxes on the video frame.

## Architecture
- **Type:** Pipeline app (cascaded multi-model)
- **Pattern:** source -> detection_wrapper -> tracker -> cropper(recognition) -> callback -> display
- **Models:**
  - hailo8: `ocr_det` (text detection) + `ocr` (text recognition)
  - hailo8l: `ocr_det` (text detection) + `ocr` (text recognition)
  - hailo10h: `ocr_det` (text detection) + `ocr` (text recognition)
- **Hardware:** hailo8, hailo8l, hailo10h
- **Postprocess:** OCR postprocess .so (resolved via `OCR_POSTPROCESS_SO_FILENAME`) -- contains both detection and recognition functions

## Key Files
| File | Purpose |
|------|---------|
| `paddle_ocr.py` | Main entry point, callback parsing OCR text results with bbox drawing |
| `paddle_ocr_pipeline.py` | `GStreamerPaddleOCRApp` subclass, cascaded detection + recognition pipeline |

## Pipeline Structure
```
SOURCE_PIPELINE(mirror_image=False)
  -> INFERENCE_PIPELINE_WRAPPER(OCR detection "ocr_detection")
    -> TRACKER_PIPELINE(class_id=-1, name="ocr_tracker",
                        keep_lost_frames=1, keep_tracked_frames=2)
      -> CROPPER_PIPELINE(
           inner: INFERENCE_PIPELINE("ocr_recognition", batch_size=8)
           cropper: OCR_CROPPER_FUNCTION
           bypass_max_size_buffers=16
         )
        -> USER_CALLBACK_PIPELINE
          -> DISPLAY_PIPELINE
```

Key parameters:
- Frame rate capped at 10 FPS for OCR processing load
- Recognition batch_size=8 to batch multiple cropped text regions
- Tracker with `keep_lost_frames=1`, `keep_tracked_frames=2` for fast stale track removal
- `mirror_image=False` in SOURCE_PIPELINE (text must not be mirrored)
- OCR config JSON from `local_resources/ocr_config.json`
- Multi-model: uses `--hef-path` with `action='append'` for two HEF files
- Default video: `ocr.mp4`

## Callback Data Available
```python
roi = hailo.get_roi_from_buffer(buffer)
text_detections = roi.get_objects_typed(hailo.HAILO_DETECTION)
for detection in text_detections:
    label = detection.get_label()           # "text_region"
    bbox = detection.get_bbox()             # HailoBBox
    confidence = detection.get_confidence()  # float

    # OCR recognized text (from recognition stage)
    ocr_objects = detection.get_objects_typed(hailo.HAILO_CLASSIFICATION)
    for cls in ocr_objects:
        if cls.get_classification_type() == "text_region":
            text_result = cls.get_label()   # the recognized text string
```

The callback filters detections with `confidence > 0.12` and skips empty text results.

## Common Use Cases
- License plate reading
- Document digitization from camera feeds
- Sign and label reading for accessibility
- Industrial part number recognition
- Retail price tag reading
- Warehouse barcode/text scanning

## How to Extend
- **Swap models:** Use `--hef-path <det.hef> --hef-path <rec.hef>` (order: detection first, recognition second)
- **Adjust frame rate:** Modify the `self.frame_rate = 10` cap for faster/slower processing
- **Increase batch size:** Adjust `self.recognition_batch_size` for more/fewer concurrent crops
- **Post-process results:** Access `user_data.get_ocr_results()` for structured OCR output (text, confidence, bbox)
- **Change input:** `--input /dev/video0` for live camera, `--input ocr.mp4` for demo

## Related Apps
| App | When to use instead |
|-----|-------------------|
| detection | If you only need to detect objects, not read text |
| clip | If you need to classify objects by text description rather than read text in images |
| face_recognition | If you need to identify people rather than read text |
