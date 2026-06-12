# Traffic Light Detector

## What This App Does
Detects traffic lights in dashcam video using YOLOv8 object detection and classifies their state (red, yellow, green) via HSV color analysis on the cropped regions. Outputs annotated frames and an optional JSON summary of traffic-light states per frame.

## Architecture
- **Type:** Standalone app
- **Pattern:** HailoInfer + YOLOv8 detection + HSV color classification; 3-thread pipeline (preprocess → async inference → visualize)
- **Models:** YOLOv8 (COCO; filters class 9 = traffic light)
- **Hardware:** hailo8 (README)
- **Postprocess:** Python — class filtering → HSV color-range matching → state classification → annotation

## Key Files
| File | Purpose |
|------|---------|
| `traffic_light_detector.py` | Main: preprocess → async inference → visualize threads; state tracking |
| `traffic_light_post_process.py` | YOLOv8 postprocess, HSV color ranges, state classification, annotation |
| `config.json` | Visualization params (score threshold, color map, tracker settings) |

## How to Run
```bash
source setup_env.sh
python -m hailo_apps.python.standalone_apps.traffic_light_detector.traffic_light_detector \
  --input dashcam.mp4
```
Optional: `--save-output`, `--json-summary`, `--output-dir results/`, `--confidence-threshold 0.4`, `--no-display`.

## How to Extend
- Add temporal filtering for state consistency across frames.
- Add adaptive HSV thresholds for night/low-light footage.
