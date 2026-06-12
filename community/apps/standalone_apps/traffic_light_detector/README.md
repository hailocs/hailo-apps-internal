# Traffic Light Detector

Detect traffic lights in dashcam footage and classify their state (red, yellow, green) using a Hailo-8 accelerator. This standalone app uses YOLOv8 for object detection and HSV color analysis for state classification -- no GStreamer required.

## Prerequisites

- Hailo-8 accelerator
- YOLOv8 model HEF (auto-downloaded via `hailo-download-resources`)
- Python environment with hailo-apps-infra installed (`source setup_env.sh`)

## How to Run

```bash
# Process a dashcam video file
python -m hailo_apps.python.standalone_apps.traffic_light_detector.traffic_light_detector \
    --input dashcam_video.mp4

# Process and save annotated output with JSON summary
python -m hailo_apps.python.standalone_apps.traffic_light_detector.traffic_light_detector \
    --input dashcam_video.mp4 --save-output --json-summary --output-dir results/

# Process an image folder (batch mode, headless)
python -m hailo_apps.python.standalone_apps.traffic_light_detector.traffic_light_detector \
    --input /path/to/images/ --no-display --save-output

# Show FPS and use a custom confidence threshold
python -m hailo_apps.python.standalone_apps.traffic_light_detector.traffic_light_detector \
    --input dashcam_video.mp4 --show-fps --confidence-threshold 0.4
```

## Architecture

```
Input (video/images)
        |
  [Preprocess Thread]  -- resize frames to model input size
        |
    input_queue
        |
  [Inference Thread]   -- YOLOv8 detection on Hailo-8 (async)
        |
    output_queue
        |
  [Visualize Thread]   -- filter for traffic lights (COCO class 9)
        |                  classify state via HSV color analysis
        |                  draw annotated results
        v
  Display / Save Output + Optional JSON Summary
```

## Output

- **Annotated frames:** Each detected traffic light is drawn with a color-coded bounding box (red/yellow/green) and a label showing the state and confidence.
- **JSON summary** (with `--json-summary`): A `traffic_light_summary.json` file in the output directory containing per-frame traffic light detections with state, confidence, and bounding box coordinates.

## Customization

- **Confidence threshold:** Use `--confidence-threshold 0.4` or edit `config.json` (`score_thres`).
- **Color classification tuning:** Modify HSV ranges in `traffic_light_post_process.py` (`COLOR_RANGES`).
- **Different model:** Use `--hef-path <model_name>` to try other detection models. Use `--list-models` to see available options.
