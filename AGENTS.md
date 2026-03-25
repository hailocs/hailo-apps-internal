# Hailo Apps — Project Instructions

> Auto-generated from `.hailo/`. Do not edit directly.

## Shared Knowledge

All skills, instructions, toolsets, knowledge bases, and memory live in `.hailo/`.
Read `.hailo/README.md` for the complete master index.

## Critical Conventions

1. **Imports are always absolute**: `from hailo_apps.python.core.common.xyz import ...`
2. **HEF resolution**: Always use `resolve_hef_path(path, app_name, arch)`
3. **Device sharing**: Always use `SHARED_VDEVICE_GROUP_ID` when creating VDevice
4. **Logging**: Use `get_logger(__name__)`
5. **CLI parsers**: Use `get_pipeline_parser()` or `get_standalone_parser()`

## Available Skills

| Skill | Doc |
|-------|-----|
| Build VLM App | `.hailo/skills/hl-build-vlm-app.md` |
| Build Pipeline App | `.hailo/skills/hl-build-pipeline-app.md` |
| Build Standalone App | `.hailo/skills/hl-build-standalone-app.md` |
| Build Agent App | `.hailo/skills/hl-build-agent-app.md` |
| Build LLM App | `.hailo/skills/hl-build-llm-app.md` |
| Build Voice App | `.hailo/skills/hl-build-voice-app.md` |

## Hardware

| Architecture | Value | Use case |
|---|---|---|
| Hailo-8 | `hailo8` | Full performance pipeline + standalone apps |
| Hailo-8L | `hailo8l` | Lower power, compatible model subset |
| Hailo-10H | `hailo10h` | GenAI (LLM, VLM, Whisper) + vision pipelines |
