# Phone Detection

## What This App Does
Placeholder/empty app directory. As of this writing it contains no files (not even an `__init__.py`) — there is no implementation, README, or main script yet. (see README — none present)

## Architecture
- **Type:** Pipeline app (placeholder; not yet implemented)
- **Pattern:** (see README — not yet defined)
- **Models:** (see README — not yet defined; detecting a "cell phone" would typically reuse a COCO-trained YOLO detector and filter to that class)
- **Hardware:** hailo8, hailo8l, hailo10h (expected, once implemented)
- **Postprocess:** (see README — not yet defined)

## Key Files
| File | Purpose |
|------|---------|
| _(none)_ | Directory is currently empty — no application code present |

## How to Run
Not runnable yet — no main script exists. To implement, follow the `detection` pipeline app as a reference (`hailo_apps/python/pipeline_apps/detection/`), then run:
```bash
source setup_env.sh
python hailo_apps/python/pipeline_apps/phone_detection/phone_detection.py --input usb
```

## How to Extend
- **To build it out:** Subclass `GStreamerApp` (or reuse the detection pipeline), filter detections to the COCO `cell phone` label, and register the app in `hailo_apps/python/core/common/defines.py`.
- Use the `detection` pipeline app as the closest reference implementation.
