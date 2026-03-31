# Prompt: Build LLM Chat App

> **Template** for creating a new LLM text generation application for Hailo-10H.
> Replace all `<PLACEHOLDERS>` with your specific values.

## The Prompt

---

Build an LLM chat application for Hailo-10H with these specifications:

**App name**: `<app_name>` (snake_case)
**Style**: `<interactive_chat / single_shot_qa / batch_processor / structured_output>`
**System prompt**: `<your system prompt, e.g., "You are a technical support assistant for networking equipment.">`
**Max tokens**: `<200>`
**Temperature**: `<0.1>`

**Custom requirements**:
- <requirement 1, e.g., "support multi-turn conversation with history">
- <requirement 2, e.g., "output responses in JSON format">
- <requirement 3, e.g., "add --voice flag for speech input">

Follow all conventions from `copilot-instructions.md`:
- Register constant in `defines.py`
- Use `get_standalone_parser()` for CLI
- Use `resolve_hef_path(path, APP_NAME, arch=HAILO10H_ARCH)` — LLM is Hailo-10H only
- Use `SHARED_VDEVICE_GROUP_ID` for VDevice
- Always `llm.clear_context()` after each generation
- Cleanup order: `clear_context()` → `release()` → `vdevice.release()` in finally
- Filter `<|im_end|>` from streaming output
- Absolute imports only
- `get_logger(__name__)` for logging
- Signal handler for graceful SIGINT shutdown

Create files in `hailo_apps/python/gen_ai_apps/<app_name>/`:
- `__init__.py`
- `<app_name>.py` — main app
- `README.md` — usage instructions

Validate:
```bash
python3 -m hailo_apps.python.gen_ai_apps.<app_name>.<app_name> --help
grep -rn "^from \.\|^import \." hailo_apps/python/gen_ai_apps/<app_name>/*.py