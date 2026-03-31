---
paths:
  - "**/gen_ai_apps/**"
---

# Gen AI Apps — Contextual Instructions

You are working on a **Gen AI application** (VLM, LLM, Whisper, Voice, or Agent).

## Required Context Files

Read these files before making changes (paths relative to `.hailo/`):

- `instructions/gen-ai-development.md` — VLM/LLM/Whisper development patterns
- `instructions/coding-standards.md` — Import rules, logging, HEF resolution
- `toolsets/gen-ai-utilities.md` — LLM streaming, voice processing, agent tools API
- `toolsets/hailort-api.md` — VDevice, VLM, LLM, Speech2Text API
- `memory/gen_ai_patterns.md` — Architecture patterns, multiprocessing gotchas
- `memory/common_pitfalls.md` — Known anti-patterns to avoid

## Additional Context (load if relevant)

- If VLM: `toolsets/vlm-backend-api.md`, `skills/hl-build-vlm-app/SKILL.md`
- If Agent: `skills/hl-build-agent-app/SKILL.md`
- If Voice/Whisper: `skills/hl-build-voice-app/SKILL.md`
- If Camera: `memory/camera_and_display.md`, `skills/hl-camera.md`

## Key Patterns for Gen AI

- Use `get_standalone_parser()` for CLI arguments
- Use `SHARED_VDEVICE_GROUP_ID` for VDevice creation
- VLM/LLM use multiprocessing backends — check `gen_ai_patterns.md` for the worker process pattern
- Always resolve HEF paths with `resolve_hef_path(path, app_name, arch)`
- Register new apps in `hailo_apps/python/core/common/defines.py`

## Reference Implementations

- VLM app: `hailo_apps/python/gen_ai_apps/vlm_chat/`
- Agent app: `hailo_apps/python/gen_ai_apps/agent_tools_example/`
- Voice: `hailo_apps/python/gen_ai_apps/gen_ai_utils/voice_processing/`
- LLM utils: `hailo_apps/python/gen_ai_apps/gen_ai_utils/llm_utils/`
