# Lane Departure Warning

A standalone Hailo application that processes dashcam video to detect lane markings and alert when the vehicle drifts out of its lane. Built on the UFLD v2 lane detection model running on Hailo-8/Hailo-10H accelerators.

## Prerequisites

- **Hardware:** Hailo-8 or Hailo-10H accelerator
- **Model:** `ufld_v2_tu` (downloaded via `hailo-download-resources`)
- **Input:** Dashcam video file (mp4)

## How to Run

```bash
# Basic usage with dashcam video
python community/apps/standalone_apps/lane_departure_warning/lane_departure_warning.py \
    --input path/to/dashcam_video.mp4

# Custom departure threshold (more sensitive)
python community/apps/standalone_apps/lane_departure_warning/lane_departure_warning.py \
    --input path/to/dashcam_video.mp4 \
    --departure-threshold 0.10

# Specify output directory
python community/apps/standalone_apps/lane_departure_warning/lane_departure_warning.py \
    --input path/to/dashcam_video.mp4 \
    --output-dir ./results/
```

## Architecture

```
Dashcam Video (mp4)
    |
    v
[Preprocess Thread]  -- resize + crop for UFLD v2 -->  [Input Queue]
                                                            |
                                                            v
                                                   [Inference Thread]  -- HailoAsyncInference (ufld_v2_tu) -->  [Output Queue]
                                                                                                                    |
                                                                                                                    v
                                                                                                          [Postprocess Thread]
                                                                                                            |           |
                                                                                                            v           v
                                                                                                    Lane Detection   Departure Analysis
                                                                                                            |           |
                                                                                                            v           v
                                                                                                   Annotated Video   Summary JSON
```

## Output

1. **Annotated video** (`output_departure_warning.mp4`): Original video with lane markings drawn in green (centered) or red (departing), status text overlay, and a lateral offset indicator bar.
2. **Departure summary** (`departure_summary.json`): JSON file listing all departure events with frame numbers, timestamps, direction, and offset values.

## CLI Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--input`, `-i` | (required) | Path to dashcam video file |
| `--hef-path`, `-n` | auto | Path to HEF model file |
| `--output-dir`, `-o` | auto | Output directory for results |
| `--departure-threshold` | 0.15 | Offset threshold to trigger warning (0.0-0.5) |
| `--smoothing-window` | 5 | Frames to average for offset smoothing |

## Customization

- **Sensitivity:** Lower `--departure-threshold` for earlier warnings (e.g., 0.10), raise it for fewer false positives (e.g., 0.25).
- **Smoothing:** Increase `--smoothing-window` to reduce jitter from noisy detections; decrease for faster response.
- **Visualization:** Modify `draw_departure_overlay()` in `lane_departure_warning_utils.py` to change colors, text, or add audio alerts.
