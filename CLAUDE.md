# Hailo Apps — Claude Code Entry Point

> Auto-generated from `.hailo/`. Do not edit directly.

## Shared Knowledge

All skills, instructions, toolsets, knowledge bases, and memory live in `.hailo/`.
Read `.hailo/README.md` for the complete master index.

## Interactive Workflow (MUST FOLLOW)

**Always walk through key decisions with the user before building.** Ask 2-3 targeted
questions to confirm app type, features, and input source. This creates a collaborative
workflow and catches misunderstandings early. Only skip questions if the user explicitly
says "just build it" or "use defaults".

## Quick Reference

```bash
source setup_env.sh                    # Activate environment (always do this first)
pip install -e .                       # Install in editable mode
```

## Skills (slash commands)

| Command | Description |
|---------|-------------|
| `/hl-build-vlm-app` | Build VLM image understanding apps |
| `/hl-build-pipeline-app` | Build GStreamer pipeline apps |
| `/hl-build-standalone-app` | Build standalone HailoRT apps |
| `/hl-build-agent-app` | Build AI agent apps with tool calling |
| `/hl-build-llm-app` | Build LLM chat apps |
| `/hl-build-voice-app` | Build voice assistant apps |


### Context Routing Table

Based on what the task involves, read **only** the matching rows:

| If the task mentions... | Read these files |
|---|---|
| **VLM, vision, image understanding** | `.hailo/skills/hl-build-vlm-app.md`, `.hailo/toolsets/vlm-backend-api.md`, `.hailo/memory/gen_ai_patterns.md` |
| **LLM, chat, text generation** | `.hailo/skills/hl-build-llm-app.md`, `.hailo/instructions/gen-ai-development.md`, `.hailo/toolsets/gen-ai-utilities.md`, `.hailo/memory/gen_ai_patterns.md` |
| **Agent, tools, function calling** | `.hailo/skills/hl-build-agent-app.md`, `.hailo/toolsets/gen-ai-utilities.md`, `.hailo/memory/gen_ai_patterns.md` |
| **Voice, STT, TTS, Whisper, speech** | `.hailo/skills/hl-build-voice-app.md`, `.hailo/toolsets/gen-ai-utilities.md` |
| **Pipeline, GStreamer, video, stream** | `.hailo/skills/hl-build-pipeline-app.md`, `.hailo/instructions/gstreamer-pipelines.md`, `.hailo/toolsets/gstreamer-elements.md`, `.hailo/memory/pipeline_optimization.md` |
| **Game, interactive, pose game** | `.hailo/skills/hl-build-pipeline-app.md`, `.hailo/toolsets/pose-keypoints.md`, `.hailo/toolsets/core-framework-api.md`, `.hailo/memory/common_pitfalls.md` |
| **Standalone, OpenCV, HailoInfer** | `.hailo/skills/hl-build-standalone-app.md`, `.hailo/toolsets/core-framework-api.md` |
| **Camera, USB, RPi, capture** | `.hailo/skills/hl-camera.md`, `.hailo/memory/camera_and_display.md` |
| **HEF, model, download, config** | `.hailo/skills/hl-model-management.md`, `.hailo/toolsets/hailort-api.md`, `.hailo/memory/hailo_platform_api.md` |
| **Monitoring, events, alerts** | `.hailo/skills/hl-monitoring.md`, `.hailo/skills/hl-event-detection.md` |
| **Testing, validation, pytest** | `.hailo/skills/hl-validate.md`, `.hailo/instructions/testing-patterns.md` |
| **ALWAYS read (every task)** | `.hailo/memory/common_pitfalls.md`, `.hailo/instructions/coding-standards.md` |


## Python Imports

```python
from hailo_apps.python.core.common.defines import *
from hailo_apps.python.core.common.core import resolve_hef_path
from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.gstreamer.gstreamer_app import GStreamerApp
```

## Critical Conventions

1. **Imports are always absolute**: `from hailo_apps.python.core.common.xyz import ...`
2. **HEF resolution**: Always use `resolve_hef_path(path, app_name, arch)`
3. **Device sharing**: Always use `SHARED_VDEVICE_GROUP_ID` when creating VDevice
4. **Logging**: Use `get_logger(__name__)`
5. **CLI parsers**: Use `get_pipeline_parser()` or `get_standalone_parser()`
6. **Architecture detection**: Use `detect_hailo_arch()` or `--arch` flag
7. **USB camera**: Always `--input usb` for auto-detection. Never hardcode `/dev/video0` (typically integrated webcam).
8. **SKILL.md is sufficient**: Read SKILL.md + common_pitfalls.md. Do NOT read source code files.
9. **Custom background**: When user provides a background image, use `background.copy()` — never blend camera feed.

## Hardware

| Architecture | Value | Use case |
|---|---|---|
| Hailo-8 | `hailo8` | Full performance, all pipeline + standalone apps |
| Hailo-8L | `hailo8l` | Lower power, compatible model subset |
| Hailo-10H | `hailo10h` | GenAI (LLM, VLM, Whisper) + vision pipelines |

## Memory

Persistent knowledge in `.hailo/memory/`. Read at task start, update when learning.
