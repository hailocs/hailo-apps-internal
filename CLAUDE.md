# Hailo Apps Infrastructure

AI applications for Hailo-8, Hailo-8L, and Hailo-10H edge accelerators.
20+ ready-to-run apps: real-time computer vision pipelines, standalone inference, and GenAI voice/vision agents.

## Agentic Development

This repository is designed for **agentic-first development**. AI coding agents (Copilot, Claude Code, or any LLM-based agent) can build complete, production-ready Hailo AI applications by following the structured instructions in this repository — without manually writing code.

### Agent Entry Points

| Agent | Entry Point | Description |
|---|---|---|
| **GitHub Copilot** | `.github/copilot-instructions.md` | Auto-loaded by Copilot Chat as system context |
| **Claude Code** | `CLAUDE.md` (this file) | Auto-loaded by Claude Code as project conventions |
| **Any agent** | `.github/instructions/` | Skills, toolsets, and prompts readable by any agent |

### Dynamic Context Loading

> **Do NOT read all 44 files.** Use the routing table below to load **only** the files relevant to the current task.

#### Context Routing Table

| If the task mentions... | Read these files (relative to `.github/`) |
|---|---|
| **VLM, vision, image understanding** | `instructions/skills/create-vlm-app.md`, `toolsets/vlm-backend-api.md`, `memory/gen_ai_patterns.md` |
| **LLM, chat, text generation** | `instructions/gen-ai-development.md`, `toolsets/gen-ai-utilities.md`, `memory/gen_ai_patterns.md` |
| **Agent, tools, function calling** | `instructions/skills/create-agent-app.md`, `toolsets/gen-ai-utilities.md`, `memory/gen_ai_patterns.md` |
| **Voice, STT, TTS, Whisper, speech** | `instructions/skills/add-voice-mode.md`, `toolsets/gen-ai-utilities.md` |
| **Pipeline, GStreamer, video, stream** | `instructions/skills/create-pipeline-app.md`, `instructions/gstreamer-pipelines.md`, `toolsets/gstreamer-elements.md`, `memory/pipeline_optimization.md` |
| **Standalone, OpenCV, HailoInfer** | `instructions/skills/create-standalone-app.md`, `toolsets/core-framework-api.md` |
| **Camera, USB, RPi, capture** | `instructions/skills/camera-integration.md`, `memory/camera_and_display.md` |
| **HEF, model, download, config** | `instructions/skills/model-management.md`, `toolsets/hailo-sdk.md`, `memory/hailo_platform_api.md` |
| **Monitoring, events, alerts** | `instructions/skills/continuous-monitoring.md`, `instructions/skills/event-detection.md` |
| **Testing, validation, pytest** | `instructions/skills/validate-and-test.md`, `instructions/testing-patterns.md` |
| **Complex multi-file app** | `instructions/orchestration.md`, `instructions/skills/plan-and-execute.md`, `instructions/agent-protocols.md` |
| **ALWAYS read (every task)** | `memory/common_pitfalls.md`, `instructions/coding-standards.md` |

### Memory (persistent knowledge base)

Knowledge base lives in `.github/memory/` (checked into the repo). Read only the memory files matched by the routing table above:

- `.github/memory/MEMORY.md` — Top-level index, key patterns, quick reference
- `.github/memory/gen_ai_patterns.md` — Gen AI app architecture, VLM/LLM patterns, gotchas
- `.github/memory/pipeline_optimization.md` — Pipeline performance patterns, bottleneck fixes
- `.github/memory/camera_and_display.md` — Camera integration, display, OpenCV patterns
- `.github/memory/hailo_platform_api.md` — Hailo SDK API patterns, device management, HEF resolution

**Rules:**
- Read relevant memory files at the start of a task to build on previous work
- Update memory files when discovering stable patterns, fixing bugs, or learning new project conventions
- Organize by topic (create new files for new topics, link from MEMORY.md)
- Keep entries concise and factual — no session-specific or speculative content

### Orchestrated Workflow

For non-trivial tasks, follow the **plan-and-execute loop** with phase gates:

```
PHASE 0: CONTEXT   → Read memory + skills + reference code (before ANY coding)
PHASE 1: PLAN      → Register app, create directory, define interfaces → GATE
PHASE 2: BUILD     → Implement modules → GATE (validate imports)
PHASE 3: VALIDATE  → CLI --help, convention checks, lint → GATE
PHASE 4: DOCUMENT  → README, update memory → GATE (final)
```

Full orchestration guide: `.github/instructions/orchestration.md`
Agent protocols: `.github/instructions/agent-protocols.md`
Plan-and-execute skill: `.github/instructions/skills/plan-and-execute.md`
Validation skill: `.github/instructions/skills/validate-and-test.md`

**Key rules:**
- NEVER write code before loading context (memory + skill files)
- NEVER advance to next phase until current gate passes
- Use todo lists to track phases with explicit GATE checkpoints
- Update `.github/memory/` when new patterns or pitfalls are discovered

## Quick Reference

```bash
source setup_env.sh                # Activate environment (always do first)
hailo-compile-postprocess          # Compile C++ postprocess plugins
hailo-post-install                 # Full post-install (downloads resources + compiles)
hailo-download-resources           # Download model HEFs and media
```

## Repository Layout

```
hailo_apps/
├── python/
│   ├── pipeline_apps/         # GStreamer real-time video apps
│   ├── standalone_apps/       # Lightweight HailoRT-only apps
│   ├── gen_ai_apps/           # Hailo-10H GenAI apps (VLM, LLM, Whisper, Agent)
│   └── core/                  # Shared framework
│       ├── common/            # Utilities, defines, buffer_utils, logger, inference
│       └── gstreamer/         # GStreamerApp base class, helper pipelines
├── postprocess/cpp/           # C++ GStreamer elements (meson build)
├── config/                    # YAML configs (resources, tests, app definitions)
└── installation/              # Install scripts
.github/
├── copilot-instructions.md    # Copilot agent instructions
├── instructions/              # Architecture, coding standards, skills
├── prompts/                   # Reusable prompt templates
├── toolsets/                  # API references
└── memory/                    # Persistent cross-session knowledge
doc/                           # User guide + developer guide
tests/                         # Pytest suite
community/                     # Community-contributed insights
```

## Three App Types

### Pipeline Apps (`pipeline_apps/`)
Real-time GStreamer video pipelines. Pattern: `GStreamerApp` subclass + `get_pipeline_string()`.
Run via CLI: `hailo-detect`, `hailo-pose`, `hailo-seg`, etc.

### Standalone Apps (`standalone_apps/`)
Direct inference using `HailoInfer` + OpenCV. No GStreamer needed.

### Gen AI Apps (`gen_ai_apps/`) — Hailo-10H Only
VLM image understanding, LLM chat, Whisper STT, voice assistants, and tool-calling agents.
Uses `hailo_platform.genai` API: `VLM`, `LLM`, `Speech2Text`.

## Critical Conventions

1. **Imports**: Always absolute — `from hailo_apps.python.core.common.xyz import ...`
2. **HEF resolution**: Always `resolve_hef_path(path, app_name, arch)` — never hardcode
3. **Device sharing**: Always `SHARED_VDEVICE_GROUP_ID` for `VDevice` group_id
4. **Logging**: `get_logger(__name__)` from `hailo_apps.python.core.common.hailo_logger`
5. **Parsers**: `get_pipeline_parser()` for GStreamer, `get_standalone_parser()` for standalone/gen-ai
6. **Architecture**: `detect_hailo_arch()` or `--arch` flag — never assume hardware
7. **Entry points**: Must have `main()` or `if __name__ == "__main__"` block

## Config System

YAML-driven via `hailo_apps/config/`:
- `config.yaml` — Global settings, version validation
- `resources_config.yaml` — Models per app per architecture
- `config_manager.py` — Unified API with `@lru_cache` caching

## Hardware

| Architecture | Value | Use case |
|---|---|---|
| Hailo-8 | `hailo8` | Full performance, all pipeline + standalone apps |
| Hailo-8L | `hailo8l` | Lower power, compatible model subset |
| Hailo-10H | `hailo10h` | GenAI (LLM, VLM, Whisper) + vision pipelines |

## Testing

```bash
pytest tests/test_runner.py -v           # Pipeline app tests
pytest tests/test_standalone_runner.py   # Standalone smoke tests
pytest tests/test_gen_ai.py              # GenAI tests (skipped on non-10H)
pytest tests/test_sanity_check.py        # Sanity checks
```

## Documentation Index

| Resource | Path |
|---|---|
| User Guide | `doc/user_guide/README.md` |
| Developer Guide | `doc/developer_guide/README.md` |
| App Development | `doc/developer_guide/app_development.md` |
| GStreamer Helpers | `doc/developer_guide/gstreamer_helper_pipelines.md` |
| Config System | `hailo_apps/config/README.md` |
| Agent Instructions | `.github/copilot-instructions.md` |
| Skills & Prompts | `.github/instructions/skills/` and `.github/prompts/` |
