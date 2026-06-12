# People Detection

## What This App Does
Placeholder/stub app directory. As of this writing it contains only an empty `__init__.py` — there is no implementation, README, or main script yet. (see README — none present)

## Architecture
- **Type:** Pipeline app (placeholder; not yet implemented)
- **Pattern:** (see README — not yet defined)
- **Models:** (see README — not yet defined; a person/people detector would typically reuse the `detection` pipeline's YOLO models)
- **Hardware:** hailo8, hailo8l, hailo10h (expected, once implemented)
- **Postprocess:** (see README — not yet defined)

## Key Files
| File | Purpose |
|------|---------|
| `__init__.py` | Empty package marker — no application code present |

## How to Run
Not runnable yet — no main script exists. To implement, follow the `detection` pipeline app as a reference (`hailo_apps/python/pipeline_apps/detection/`), then run:
```bash
source setup_env.sh
python hailo_apps/python/pipeline_apps/people_detection/people_detection.py --input usb
```

## How to Extend
- **To build it out:** Subclass `GStreamerApp` (or reuse the detection pipeline), filter detections to the `person` label, and register the app in `hailo_apps/python/core/common/defines.py`.
- Use the `detection` and `pose_estimation` pipeline apps as the closest reference implementations.
