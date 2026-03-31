---
paths:
  - "**/pipeline_apps/**"
---

# Pipeline Apps — Contextual Instructions

You are working on a **GStreamer pipeline application**.

## Required Context Files

Read these files before making changes (paths relative to `.hailo/`):

- `instructions/gstreamer-pipelines.md` — Pipeline composition, fragments, architecture
- `instructions/coding-standards.md` — Import rules, logging, HEF resolution
- `toolsets/gstreamer-elements.md` — All Hailo + standard GStreamer elements
- `toolsets/core-framework-api.md` — GStreamerApp, buffer_utils, parsers
- `memory/pipeline_optimization.md` — Bottleneck patterns, queue tuning, scheduler fixes
- `memory/common_pitfalls.md` — Known anti-patterns to avoid

## Additional Context (load if relevant)

- If camera input: `memory/camera_and_display.md`, `skills/hl-camera.md`
- If adding models: `skills/hl-model-management.md`, `toolsets/hailort-api.md`

## Key Patterns for Pipelines

- Subclass `GStreamerApp` and implement `get_pipeline_string()`
- Use `get_pipeline_parser()` for CLI arguments
- Compose pipelines using helper functions from `gstreamer_helper_pipelines.py`
- Use `SHARED_VDEVICE_GROUP_ID` for hailonet elements
- Always resolve HEF paths with `resolve_hef_path(path, app_name, arch)`
- Register new apps in `hailo_apps/python/core/common/defines.py`

## Reference Implementations

- Detection: `hailo_apps/python/pipeline_apps/detection/`
- Pose: `hailo_apps/python/pipeline_apps/pose_estimation/`
- Instance segmentation: `hailo_apps/python/pipeline_apps/instance_segmentation/`
- Pipeline helpers: `hailo_apps/python/core/gstreamer/gstreamer_helper_pipelines.py`
