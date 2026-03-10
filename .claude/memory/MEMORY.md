# Hailo Apps Infra - Memory

## Project Structure
- Repo root: `/home/giladn/tappas_apps/repos/hailo-apps-infra`
- C++ postprocess: `hailo_apps/postprocess/cpp/` (meson build, compiled via `hailo-compile-postprocess`)
- Python pipeline apps: `hailo_apps/python/pipeline_apps/<app_name>/`
- Defines/constants: `hailo_apps/python/core/common/defines.py`
- GStreamer helpers: `hailo_apps/python/core/gstreamer/gstreamer_helper_pipelines.py`
- Resources installed to: `/usr/local/hailo/resources/` (models, so files)

## Build Commands
- Activate env: `source setup_env.sh`
- Compile C++ postprocess: `hailo-compile-postprocess` (NOT `hailo_post_install`)
- Full post-install: `hailo-post-install`
- Inspect HEF model: `hailortcli parse-hef <path.hef>`

## Gesture Detection App
- See detailed notes: [gesture_detection.md](gesture_detection.md)
- Branch: `gesture-app`
- Status: Core pipeline working, bbox/landmark accuracy fixed

## Pipeline Profiler Skill
- Slash command: `/profile-pipeline` — profile, analyze, suggest, experiment, learn
- Scripts: `.claude/skills/profile-pipeline/scripts/`
- Knowledge base: `.claude/skills/profile-pipeline/knowledge/knowledge_base.yaml`
- Detailed notes: [pipeline_profiling.md](pipeline_profiling.md)

## Key Patterns
- Pipeline apps follow pattern: `app.py` (callback + main) + `app_pipeline.py` (GStreamerApp subclass)
- Run apps via: `python hailo_apps/python/pipeline_apps/<app>/app.py`
- GStreamerApp subclass must override `get_pipeline_string()`, call `self.create_pipeline()` in __init__
- `hailocropper` sends **parent detection** as ROI to inner pipeline, not the crop sub-detection
- `hailo_common::add_landmarks_to_detection()` normalizes coords relative to detection bbox
- For plain HailoROI (no detection), create HailoLandmarks manually and `roi->add_object()`

## Critical: TAPPAS Coordinate Spaces & scaling_bbox
- See detailed notes: [tappas_coordinate_spaces.md](tappas_coordinate_spaces.md)
- `INFERENCE_PIPELINE_WRAPPER` sets a non-identity `scaling_bbox` on the ROI (letterbox transform)
- `set_scaling_bbox()` ACCUMULATES (composes), `clear_scaling_bbox()` resets to identity
- `hailooverlay` applies scaling_bbox to detection bboxes but NOT to landmarks → mismatch!
- If creating new detections in frame-absolute coords after the wrapper, must `clear_scaling_bbox()`
