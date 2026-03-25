# Hailo Apps — Claude Code Entry Point

> Auto-generated from `.hailo/`. Do not edit directly.

## Shared Knowledge

All skills, instructions, toolsets, knowledge bases, and memory live in `.hailo/`.
Read `.hailo/README.md` for the complete master index.

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

## Hardware

| Architecture | Value | Use case |
|---|---|---|
| Hailo-8 | `hailo8` | Full performance, all pipeline + standalone apps |
| Hailo-8L | `hailo8l` | Lower power, compatible model subset |
| Hailo-10H | `hailo10h` | GenAI (LLM, VLM, Whisper) + vision pipelines |

## Memory

Persistent knowledge in `.hailo/memory/`. Read at task start, update when learning.
