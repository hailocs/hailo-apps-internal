# Multi-Camera Store Monitor

Real-time retail store monitoring using 3 cameras (entrance, checkout, stockroom) processed through a single shared Hailo-8 detection pipeline with round-robin scheduling.

## Features

- **3-camera round-robin:** Entrance, checkout, and stockroom feeds multiplexed through a single YOLOv8 detection model
- **Person detection & counting:** Per-camera person counts with configurable confidence threshold
- **Zone alerts:** Configurable per-camera person count thresholds that trigger warnings
- **Per-camera tracking:** HailoTracker assigns unique IDs to persons within each stream
- **Periodic summary:** Console summary every 10 seconds showing current, max, and average person counts per camera

## Prerequisites

- Hailo-8 accelerator
- TAPPAS environment (`source setup_env.sh`)
- Detection model HEF (auto-downloaded via `hailo-download-resources`)
- Detection postprocess .so (compiled via `hailo-compile-postprocess`)

## Usage

```bash
# With 3 video files
python -m hailo_apps.python.pipeline_apps.multi_camera_store_monitor.multi_camera_store_monitor \
    --sources entrance.mp4,checkout.mp4,stockroom.mp4

# Default (uses the sample detection video for all 3 streams)
python -m hailo_apps.python.pipeline_apps.multi_camera_store_monitor.multi_camera_store_monitor

# With custom person detection threshold
python -m hailo_apps.python.pipeline_apps.multi_camera_store_monitor.multi_camera_store_monitor \
    --sources entrance.mp4,checkout.mp4,stockroom.mp4 --person-threshold 0.6

# Show FPS overlay
python -m hailo_apps.python.pipeline_apps.multi_camera_store_monitor.multi_camera_store_monitor --show-fps
```

## Pipeline Architecture

```
SOURCE_0 (Entrance)  -> set_stream_id("src_0") -> robin.sink_0
SOURCE_1 (Checkout)  -> set_stream_id("src_1") -> robin.sink_1
SOURCE_2 (Stockroom) -> set_stream_id("src_2") -> robin.sink_2

hailoroundrobin (mode=1, shared across all cameras)
    -> INFERENCE_PIPELINE (YOLOv8 detection)
        -> TRACKER_PIPELINE (per-stream tracking)
            -> USER_CALLBACK (unified: person counting + zone alerts)
                -> hailostreamrouter
                    router.src_0 -> per-source callback -> DISPLAY_0 (Entrance)
                    router.src_1 -> per-source callback -> DISPLAY_1 (Checkout)
                    router.src_2 -> per-source callback -> DISPLAY_2 (Stockroom)
```

## Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--sources` | Default video x3 | Comma-separated list of 3 video sources |
| `--person-threshold` | 0.5 | Confidence threshold for person detections |
| `--show-fps` | false | Show FPS overlay on display |
| `--hef-path` | Auto-detected | Path to detection HEF file |

### Zone Alert Thresholds

Edit `ZONE_ALERT_THRESHOLDS` in `multi_camera_store_monitor.py`:

| Camera | Default Threshold |
|--------|------------------|
| Entrance (src_0) | 10 persons |
| Checkout (src_1) | 5 persons |
| Stockroom (src_2) | 3 persons |

## Customization

- **Add more cameras:** Increase `NUM_STORE_CAMERAS` in the pipeline file and add entries to `CAMERA_NAMES`
- **Change model:** Use `--hef-path <path>` for a different detection model
- **Custom zones:** Define polygon zones in the callback and check if detections fall within them
- **Data export:** Add JSON/CSV logging in the callback for analytics
