# Prompt: Create New VLM App Variant

> Template prompt for creating a new VLM-based application variant.

## Instructions for Agent

You are building a new VLM application variant in the hailo-apps repository. Follow these steps exactly:

### Required Context (Read These First)
1. `.hailo/instructions/gen-ai-development.md` — Gen AI patterns
2. `.hailo/skills/hl-build-vlm-app.md` — VLM app skill
3. `.hailo/toolsets/vlm-backend-api.md` — Backend API
4. `.hailo/toolsets/hailort-api.md` — HailoRT API reference
5. `hailo_apps/python/gen_ai_apps/vlm_chat/` — Reference implementation

### Build Steps
1. Create directory: `hailo_apps/python/gen_ai_apps/{app_name}/`
2. Add `__init__.py` (empty)
3. Reuse or adapt `Backend` from `vlm_chat/backend.py`
4. Create main app file with:
   - Proper imports (absolute)
   - CLI parser using `get_standalone_parser()`
   - HEF resolution using `resolve_hef_path()`
   - Camera initialization
   - Main loop with VLM inference
   - Signal handling and graceful shutdown
5. Add `README.md` with usage instructions
6. Register constants in `defines.py`

### Customization Variables

Fill in these values for your specific variant:

| Variable | Description | Example |
|---|---|---|
| `{app_name}` | Directory and module name | `my_vlm_app` |
| `{APP_CONSTANT}` | defines.py constant | `MY_VLM_APP` |
| `{system_prompt}` | VLM system behavior | `"You are monitoring a scene..."` |
| `{user_prompt}` | Per-frame question | `"What is happening in the scene?"` |
| `{capture_interval}` | Seconds between analyses | `10` |
| `{max_tokens}` | Max response length | `300` |
| `{behavior}` | Interactive or continuous | `continuous` |
