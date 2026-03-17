# Cat Food Monitor

Monitor a cat food bowl with a USB camera. Detect cats approaching, recognize which of your trained cats it is, and log feeding times and durations per cat to a CSV file.

Built on the **face_recognition** pipeline template, using SCRFD face detection + ArcFace embeddings for identity matching via a LanceDB vector database.

## Prerequisites

- Hailo-8 (also supports Hailo-8L and Hailo-10H)
- USB camera pointed at the food bowl
- Models downloaded: `hailo-download-resources`
- Postprocess compiled: `hailo-compile-postprocess`

## Usage

### 1. Train cat identities

Place images of each cat in subdirectories under `train/`:

```
train/
  whiskers/
    photo1.jpg
    photo2.jpg
  mittens/
    photo1.jpg
    photo2.jpg
```

Then run training:

```bash
python community/apps/pipeline_apps/cat_food_monitor/cat_food_monitor.py --mode train
```

### 2. Run the monitor

```bash
# USB camera (default)
python community/apps/pipeline_apps/cat_food_monitor/cat_food_monitor.py --input usb

# Video file
python community/apps/pipeline_apps/cat_food_monitor/cat_food_monitor.py --input path/to/video.mp4
```

### 3. Clear the database

```bash
python community/apps/pipeline_apps/cat_food_monitor/cat_food_monitor.py --mode delete
```

## Output

- **Live display** with bounding boxes and cat identity labels
- **feeding_log.csv** with columns: timestamp, cat_name, event (arrived/departed), track_id, confidence, duration_seconds

## Architecture

```
SOURCE_PIPELINE (USB camera)
  -> INFERENCE_PIPELINE_WRAPPER (SCRFD face detection)
    -> TRACKER_PIPELINE
      -> CROPPER_PIPELINE (face align + ArcFace recognition)
        -> USER_CALLBACK_PIPELINE (vector DB search: cat identity)
          -> USER_CALLBACK_PIPELINE (app callback: logging)
            -> DISPLAY_PIPELINE
```

## Algorithm Parameters

Edit `cat_food_algo_params.json` to tune:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `skip_frames` | 15 | Frames to skip before first recognition attempt |
| `lance_db_vector_search_classificaiton_confidence_threshold` | 0.45 | Minimum confidence for identity match |
| `batch_size` | 1 | Inference batch size |

## Customization

- **Add more cats**: Add subdirectories to `train/` and re-run `--mode train`
- **Adjust sensitivity**: Lower the confidence threshold in `cat_food_algo_params.json` for stricter matching
- **Feeding log cooldown**: Edit `FEEDING_LOG_COOLDOWN_SECONDS` in `cat_food_monitor.py` (default: 60s between log entries per cat)

## Notes

This app reuses the face detection + recognition models (SCRFD + ArcFace) which are optimized for human faces. For best results with cat faces, you would ideally retrain or fine-tune these models on cat face data. However, the existing models can provide a reasonable starting point for prototyping, especially if cats are photographed consistently from similar angles during training.
