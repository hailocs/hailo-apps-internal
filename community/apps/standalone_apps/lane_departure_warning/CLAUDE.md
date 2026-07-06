# Lane Departure Warning System

## What This App Does
Processes dashcam video to detect lane markings with a UFLD v2 model and analyze the vehicle's lateral position. Produces an annotated output video with departure warnings (green lanes when centered, red when departing) plus a JSON summary of departure events with timestamps and offsets.

## Architecture
- **Type:** Standalone app
- **Pattern:** HailoInfer + UFLD v2 lane detection; 3-thread pipeline (preprocess → inference → postprocess) with departure analysis
- **Models:** ufld_v2_tu (Ultra-Fast Lane Detection v2)
- **Hardware:** hailo8, hailo10h (see README)
- **Postprocess:** Python — lane anchor decoding → lateral offset → smoothing → departure threshold comparison

## Key Files
| File | Purpose |
|------|---------|
| `lane_departure_warning.py` | Main: preprocess → inference → postprocess threads; departure analysis, JSON logging, annotated video |
| `lane_departure_warning_utils.py` | `UFLDProcessing` (anchor decoding) + `DepartureDetector` (offset smoothing, event logging) + visualization |

## How to Run
```bash
source setup_env.sh
python community/apps/standalone_apps/lane_departure_warning/lane_departure_warning.py --input dashcam.mp4
```
Optional: `--departure-threshold 0.10`, `--smoothing-window 5`, `--output-dir results/`.

## How to Extend
- Add audio alerts on departure or multi-lane tracking.
- Add road-curvature compensation to the departure threshold for curved roads.
