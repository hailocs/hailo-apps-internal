# Prompt: Create New Pipeline Application

> Template prompt for creating a new GStreamer pipeline application.

## Instructions for Agent

You are building a new GStreamer pipeline application in the hailo-apps repository.

### Required Context (Read These First)
1. `.hailo/instructions/gstreamer-pipelines.md` — Pipeline patterns
2. `.hailo/skills/hl-build-pipeline-app.md` — Pipeline app skill
3. `.hailo/toolsets/gstreamer-elements.md` — Available elements
4. `.hailo/toolsets/core-framework-api.md` — Framework API
5. `hailo_apps/python/core/gstreamer/gstreamer_app.py` — Base class
6. `hailo_apps/python/core/gstreamer/gstreamer_helper_pipelines.py` — Helpers

### Build Steps
1. Register app in `defines.py` (name, model, postprocess .so)
2. Create directory under `pipeline_apps/{app_name}/`
3. Create `app_callback_class` subclass with custom state
4. Implement `app_callback()` function for frame processing
5. Subclass `GStreamerApp`, override `get_pipeline_string()`
6. Compose pipeline using helper functions
7. Add entry point with `get_pipeline_parser()`
8. Add `README.md`

### Pipeline Composition Pattern

```python
def get_pipeline_string(self):
    source = SOURCE_PIPELINE(self.video_source, self.video_width, self.video_height)
    inference = INFERENCE_PIPELINE(hef_path=self.hef_path, post_process_so=self.so_path)
    callback = USER_CALLBACK_PIPELINE()
    display = DISPLAY_PIPELINE(video_sink=self.video_sink, sync=self.sync)
    return f"{source} ! {QUEUE('q1')} ! {inference} ! {QUEUE('q2')} ! {callback} ! {display}"
```

### Customization Variables

| Variable | Description |
|---|---|
| `{app_name}` | App directory name |
| `{model}` | Default HEF model name |
| `{postprocess_so}` | Postprocess shared library |
| `{pipeline_pattern}` | single / wrapped / cascaded / tiled |
| `{callback_logic}` | What to do in frame callback |
