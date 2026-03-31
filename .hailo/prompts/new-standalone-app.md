# Prompt: Build Standalone Inference App

> **Template** for creating a new standalone (HailoInfer + OpenCV) application.
> Replace all `<PLACEHOLDERS>` with your specific values.

## The Prompt

---

Build a standalone inference application for Hailo with these specifications:

**App name**: `<app_name>` (snake_case)
**Task**: `<detection / pose_estimation / segmentation / lane_detection / ocr / super_resolution>`
**Input**: `<usb_camera / video_file / image_directory>`
**Output**: `<display_window / save_video / save_images / json_results>`

**Custom requirements**:
- <requirement 1, e.g., "count detected persons per frame">
- <requirement 2, e.g., "draw bounding boxes with confidence scores">
- <requirement 3, e.g., "save results to JSON file">

**Architecture**: Use the standard 3-thread pattern (preprocess → infer → postprocess) with queue-based communication.

Follow all conventions from `copilot-instructions.md`:
- Register constant in `defines.py`
- Use `get_standalone_parser()` for CLI
- Use `handle_and_resolve_args()` for HEF resolution
- Use `HailoInfer` for inference
- Absolute imports only
- `get_logger(__name__)` for logging
- Signal handler for graceful SIGINT shutdown
- `hailo_infer.close()` in finally block

Create files in `hailo_apps/python/standalone_apps/<app_name>/`:
- `__init__.py`
- `<app_name>.py` — main app with 3-thread architecture
- `<app_name>_post_process.py` — custom postprocessing
- `README.md` — usage instructions

Validate:
```bash
python3 -m hailo_apps.python.standalone_apps.<app_name>.<app_name> --help
grep -rn "^from \.\|^import \." hailo_apps/python/standalone_apps/<app_name>/*.py