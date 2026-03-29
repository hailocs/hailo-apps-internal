# Hailo Apps — Copilot Global Instructions

> This repository is designed for **agentic-first development**. AI coding agents can build complete, production-ready Hailo AI applications by following the structured instructions, skills, and prompts in this `.github/` directory — without manually writing code.

## Repository Identity

- **Name**: hailo-apps
- **Purpose**: Production-grade AI vision & generative-AI applications running on Hailo accelerators (Hailo-8, Hailo-8L, Hailo-10H)
- **Stack**: Python 3.10+, GStreamer, HailoRT, TAPPAS, OpenCV, hailo_platform SDK

## Architecture at a Glance

| Layer | Description |
|---|---|
| **Core Framework** (`hailo_apps/python/core/`) | GStreamerApp base class, pipeline helpers, parsers, logging, HEF utilities |
| **Pipeline Apps** (`hailo_apps/python/pipeline_apps/`) | GStreamer-based video pipelines (detection, pose, segmentation, etc.) |
| **Standalone Apps** (`hailo_apps/python/standalone_apps/`) | Direct inference apps using HailoInfer + OpenCV (no GStreamer) |
| **Gen AI Apps** (`hailo_apps/python/gen_ai_apps/`) | Hailo-10H generative AI: VLM, LLM, Whisper, Voice Assistant, Agent |
| **Community Apps** (`community/apps/`) | Agent-built apps staged for review before promotion to official |
| **Community Contributions** (`community/contributions/`) | Lessons learned, recipes, optimization patterns from real builds |
| **Postprocess** (`hailo_apps/postprocess/`) | C++ shared libraries for model-specific postprocessing |
| **Config** (`hailo_apps/config/`) | YAML-driven model registry, resource paths, test definitions |

## Critical Conventions (MUST FOLLOW)

1. **Imports are always absolute**: `from hailo_apps.python.core.common.xyz import ...`
2. **HEF resolution**: Always use `resolve_hef_path(path, app_name, arch)` — never hardcode paths
3. **Device sharing**: Always use `SHARED_VDEVICE_GROUP_ID` when creating `VDevice`
4. **Logging**: Use `get_logger(__name__)` from `hailo_apps.python.core.common.hailo_logger`
5. **CLI parsers**: Use `get_pipeline_parser()` for GStreamer apps, `get_standalone_parser()` for standalone/gen-ai apps
6. **Architecture detection**: Use `detect_hailo_arch()` or `--arch` flag; never assume hardware
7. **Entry points**: App must have a `main()` or `if __name__ == "__main__"` block

## Dynamic Context Loading

> **Do NOT read all 44 files.** Use the routing table below to load **only** the files relevant to the current task. This saves tokens and keeps context focused.

### Context Routing Table

Based on what the task involves, read **only** the matching rows:

| If the task mentions... | Read these files |
|---|---|
| **VLM, vision, image understanding** | `skills/hl-build-vlm-app.md`, `toolsets/vlm-backend-api.md`, `memory/gen_ai_patterns.md` |
| **LLM, chat, text generation** | `skills/hl-build-llm-app.md`, `instructions/gen-ai-development.md`, `toolsets/gen-ai-utilities.md`, `memory/gen_ai_patterns.md` |
| **Agent, tools, function calling** | `skills/hl-build-agent-app.md`, `toolsets/gen-ai-utilities.md`, `memory/gen_ai_patterns.md` |
| **Voice, STT, TTS, Whisper, speech** | `skills/hl-build-voice-app.md`, `toolsets/gen-ai-utilities.md` |
| **Pipeline, GStreamer, video, stream** | `skills/hl-build-pipeline-app.md`, `instructions/gstreamer-pipelines.md`, `toolsets/gstreamer-elements.md`, `memory/pipeline_optimization.md` |
| **Standalone, OpenCV, HailoInfer** | `skills/hl-build-standalone-app.md`, `toolsets/core-framework-api.md` |
| **Camera, USB, RPi, capture** | `skills/hl-camera.md`, `memory/camera_and_display.md` |
| **HEF, model, download, config** | `skills/hl-model-management.md`, `toolsets/hailo-sdk.md`, `memory/hailo_platform_api.md` |
| **Monitoring, events, alerts** | `skills/hl-monitoring.md`, `skills/hl-event-detection.md` |
| **Testing, validation, pytest** | `skills/hl-validate.md`, `instructions/testing-patterns.md` |
| **Complex multi-file app** | `instructions/orchestration.md`, `skills/hl-plan-and-execute.md`, `instructions/agent-protocols.md` |
| **ALWAYS read (every task)** | `memory/common_pitfalls.md`, `instructions/coding-standards.md` |

All paths above are relative to `.github/`. The knowledge base at `.github/knowledge/knowledge_base.yaml` and community contributions at `community/contributions/` can be checked when you need recipes or patterns.

### Community App Workflow

When building new apps, agents MUST:
1. Place app code in `community/apps/<app_name>/` with `app.yaml` manifest and `run.sh` wrapper
2. Create a contribution recipe in `community/contributions/<category>/` documenting lessons learned
3. Do NOT register in `defines.py` or `resources_config.yaml` — that happens during promotion
4. Run via `./community/apps/<app_name>/run.sh --input <source>`

Promotion to official: `python .hailo/scripts/curate_contributions.py --promote <app_name>`
Curation of knowledge: `python .hailo/scripts/curate_contributions.py --curate`

### Persistent Memory

```
.github/memory/
├── MEMORY.md                  ← Index — read this first
├── gen_ai_patterns.md         ← VLM/LLM architecture, multiprocessing, gotchas
├── pipeline_optimization.md   ← GStreamer bottlenecks, queue tuning, scheduler fixes
├── camera_and_display.md      ← Camera init, BGR/RGB, OpenCV patterns
├── hailo_platform_api.md      ← VDevice, VLM.generate(), HEF resolution
└── common_pitfalls.md         ← Bugs found, anti-patterns to avoid
```

**Rules**: Read relevant memory files at task start (use routing table above). Update them when discovering new patterns.

## Orchestrated Agent Workflow

For complex multi-file apps, use the **plan-and-execute loop** with **sub-agent delegation** and **phase gates**.
Full details: `.github/instructions/orchestration.md` and `.github/instructions/agent-protocols.md`

### Quick Reference: The Loop

```
PHASE 0: CONTEXT   → Use routing table above to load relevant files only
PHASE 1: PLAN      → Register app, create directory, define interfaces
         GATE      → Verify directory exists, constant registered
PHASE 2: BUILD     → Sub-agents for independent modules, main agent for dependent ones
         GATE      → Validate all imports resolve
PHASE 3: VALIDATE  → CLI --help, convention checks, lint/errors
         GATE      → All checks pass (fix and re-run if not)
PHASE 4: DOCUMENT  → Sub-agent writes README, update memory if needed
         GATE      → Final validation, all todos complete
```

### Key Protocols

1. **Route context** — Use the routing table to load only relevant files, not all 44
2. **Context first** — NEVER write code before reading routed context files
3. **Phase gates** — NEVER advance to next phase until current gate passes
4. **Sub-agents** — Delegate independent reads and module builds; keep sequential edits in main agent
5. **Todo tracking** — Use `manage_todo_list` with explicit GATE items
6. **Memory loop** — Update `.github/memory/` when new patterns or pitfalls are discovered
7. **Recovery** — On gate failure: read error → check memory → fix → re-run gate

### Agent Workflow Steps

1. **Match task to routing table** — identify which files to load
2. **Read only routed files** from `.github/` (via sub-agent for speed)
3. **Create todo list** with phases and explicit GATE items
4. **Execute phase-by-phase** using sub-agents where appropriate
5. **Validate at every gate** — never skip
6. **Follow conventions** exactly (see Critical Conventions above)
7. **Register the app** in defines.py
8. **Document** with README.md and update memory

## File Reference Map

| Need | Look At |
|---|---|
| Build a GStreamer pipeline app | `hailo_apps/python/core/gstreamer/gstreamer_app.py` |
| Compose pipeline strings | `hailo_apps/python/core/gstreamer/gstreamer_helper_pipelines.py` |
| Build a gen-ai app (VLM/LLM) | `hailo_apps/python/gen_ai_apps/vlm_chat/` |
| Build an agent with tools | `hailo_apps/python/gen_ai_apps/agent_tools_example/` |
| Add voice capabilities | `hailo_apps/python/gen_ai_apps/gen_ai_utils/voice_processing/` |
| Use LLM streaming/tools | `hailo_apps/python/gen_ai_apps/gen_ai_utils/llm_utils/` |
| Define constants/app names | `hailo_apps/python/core/common/defines.py` |
| Resolve model paths | `hailo_apps/python/core/common/core.py` → `resolve_hef_path()` |
| Parse CLI arguments | `hailo_apps/python/core/common/parser.py` |
| Understand available models | `hailo_apps/config/resources_config.yaml` |

## Agentic Development Files

```
.github/
├── copilot-instructions.md          ← You are here (global instructions)
├── agents/
│   ├── hl-app-builder.md            ← Router agent: delegates to specialist builders
│   ├── hl-vlm-builder.md            ← Specialist: VLM applications
│   ├── hl-pipeline-builder.md       ← Specialist: GStreamer pipeline apps
│   ├── hl-standalone-builder.md     ← Specialist: Standalone inference apps
│   ├── hl-agent-builder.md          ← Specialist: Agent with tool calling
│   ├── hl-llm-builder.md            ← Specialist: LLM text generation apps
│   └── hl-voice-builder.md          ← Specialist: Voice-enabled apps
├── instructions/
│   ├── architecture.md              ← System architecture deep dive
│   ├── coding-standards.md          ← Code style & conventions
│   ├── gen-ai-development.md        ← Gen AI app development guide
│   ├── gstreamer-pipelines.md       ← GStreamer pipeline patterns
│   ├── testing-patterns.md          ← Test writing guide
│   ├── orchestration.md             ← Multi-agent orchestration framework
│   └── agent-protocols.md           ← Agent behavioral contracts
├── skills/
│   ├── hl-build-vlm-app.md          ← Skill: Build VLM applications
│   ├── hl-build-pipeline-app.md     ← Skill: Build GStreamer pipeline apps
│   ├── hl-build-standalone-app.md   ← Skill: Build standalone inference apps
│   ├── hl-build-agent-app.md        ← Skill: Build agent with tool calling
│   ├── hl-build-llm-app.md          ← Skill: Build LLM text generation apps
│   ├── hl-build-voice-app.md        ← Skill: Build voice-enabled apps
│   ├── hl-monitoring.md             ← Skill: Continuous monitoring patterns
│   ├── hl-event-detection.md        ← Skill: Detect & report events from video
│   ├── hl-camera.md                 ← Skill: Camera setup & management
│   ├── hl-model-management.md       ← Skill: HEF resolution & model config
│   ├── hl-plan-and-execute.md       ← Skill: Plan-and-execute loop pattern
│   └── hl-validate.md               ← Skill: Validation at every phase gate
├── prompts/
│   ├── dog-monitor-app.md           ← Demo: Orchestrated dog monitoring build
│   ├── dog-monitor-flat.md          ← Demo: Flat (non-orchestrated) dog monitor
│   ├── orchestrated-build.md        ← Meta-template: Orchestrated build (any app)
│   ├── new-vlm-variant.md           ← Template: Create VLM app variant
│   ├── new-pipeline-app.md          ← Template: Create pipeline app
│   ├── new-standalone-app.md        ← Template: Create standalone app
│   ├── new-llm-app.md               ← Template: Create LLM app
│   ├── new-voice-app.md             ← Template: Create voice app
│   └── new-agent-tool.md            ← Template: Create new agent tool
├── toolsets/
│   ├── hailo-sdk.md                 ← Hailo SDK API reference
│   ├── gstreamer-elements.md        ← Available GStreamer elements
│   ├── vlm-backend-api.md           ← VLM Backend class API
│   ├── core-framework-api.md        ← Core framework API reference
│   └── gen-ai-utilities.md          ← Gen AI utilities reference
├── memory/
│   ├── MEMORY.md                    ← Index + quick reference
│   ├── gen_ai_patterns.md           ← VLM/LLM patterns & gotchas
│   ├── pipeline_optimization.md     ← Pipeline bottleneck fixes
│   ├── camera_and_display.md        ← Camera & OpenCV patterns
│   ├── hailo_platform_api.md        ← SDK usage patterns
│   └── common_pitfalls.md           ← Bugs & anti-patterns
├── knowledge/
│   └── knowledge_base.yaml          ← Machine-readable recipes & patterns
├── contextual-rules/
│   ├── gen-ai-apps.md               ← Auto-loaded for gen_ai_apps/** files
│   ├── pipeline-apps.md             ← Auto-loaded for pipeline_apps/** files
│   ├── standalone-apps.md           ← Auto-loaded for standalone_apps/** files
│   ├── core-framework.md            ← Auto-loaded for core/** files
│   └── tests.md                     ← Auto-loaded for tests/** files
├── scripts/
│   ├── generate_platforms.py        ← Generator: .hailo/ → platform-specific files
│   ├── validate_app.py              ← Validate scaffolded app conventions (--smoke-test for runtime checks)
│   ├── curate_contributions.py      ← Tiered curation: knowledge → memory + skill/toolset summaries
│   ├── curate_and_propose.py        ← Curate, sync platforms, and propose PRs
│   └── push_community_apps.py       ← Push community apps to external repo
CLAUDE.md                             ← Claude Code entry point (root)
community/
├── apps/                             ← Community-built apps (10 apps)
│   ├── pipeline_apps/               ← 8 pipeline apps
│   ├── standalone_apps/             ← 2 standalone apps
│   └── gen_ai_apps/                 ← Gen AI apps (coming soon)
└── contributions/                    ← Community-contributed insights
    ├── README.md
    ├── pipeline-optimization/
    ├── bottleneck-patterns/
    ├── gen-ai-recipes/
    ├── hardware-config/
    ├── camera-display/
    ├── voice-audio/
    └── general/
```
