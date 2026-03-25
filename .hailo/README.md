# .hailo/ — Shared Agentic Knowledge

Platform-neutral knowledge base for building Hailo AI applications. This directory is the **canonical source of truth** for all AI coding agents (GitHub Copilot, Claude Code, Cursor, or any LLM-based agent).

Platform-specific configurations (`.github/`, `.claude/`, `.cursor/`) are **generated** from this directory using the generator script. Never edit generated files directly — edit here, then regenerate.

## Directory Structure

```
.hailo/
├── README.md                          ← This file (master index)
├── instructions/                      ← Architecture & development standards
├── skills/                            ← Step-by-step workflow guides (hl- prefix)
├── toolsets/                          ← API references
├── knowledge/                         ← Structured knowledge bases (YAML)
├── memory/                            ← Persistent cross-session knowledge
├── agents/                            ← Platform-neutral agent definitions
├── contextual-rules/                  ← File-pattern-triggered context rules
├── prompts/                           ← Build prompt templates
├── templates/                         ← Scaffold templates for new apps (TODO)
├── examples/                          ← Minimal runnable examples (TODO)
└── scripts/                           ← Generator & validation scripts
```

## Instructions (`instructions/`)

Architecture and development standards for building Hailo apps.

| File | Description |
|---|---|
| `architecture.md` | Three-tier app architecture (pipeline, standalone, gen-ai), module dependency graph |
| `coding-standards.md` | Mandatory coding conventions: imports, logging, HEF resolution, CLI parsers, error handling |
| `gen-ai-development.md` | Hailo-10H gen AI guide: VLM/LLM/Whisper patterns, multiprocessing backend |
| `gstreamer-pipelines.md` | GStreamer pipeline composition: source/inference/display fragments, callback patterns |
| `testing-patterns.md` | Test framework, markers, fixtures, test patterns |
| `orchestration.md` | Multi-agent orchestration: plan-and-execute loops, phase gates, sub-agent delegation |
| `agent-protocols.md` | Behavioral contracts for agents: context-first execution, phase gates, todo management |

## Skills (`skills/`)

Step-by-step workflow guides for agents. All use the `hl-` prefix.

### Build Skills
| File | Description |
|---|---|
| `hl-build-vlm-app.md` | Build Vision-Language Model apps for Hailo-10H |
| `hl-build-pipeline-app.md` | Build GStreamer pipeline apps for real-time video |
| `hl-build-standalone-app.md` | Build standalone HailoRT inference apps |
| `hl-build-agent-app.md` | Build AI agent apps with LLM tool calling |
| `hl-build-llm-app.md` | Build LLM chat and text generation apps |
| `hl-build-voice-app.md` | Build voice assistant apps (Whisper STT + Piper TTS) |

### Detailed Instructions (per skill)
| File | Description |
|---|---|
| `hl-build-vlm-app-instructions.md` | Detailed VLM app creation guide |
| `hl-build-pipeline-app-instructions.md` | Detailed pipeline app creation guide |
| `hl-build-standalone-app-instructions.md` | Detailed standalone app creation guide |
| `hl-build-agent-app-instructions.md` | Detailed agent app creation guide |
| `hl-build-llm-app-instructions.md` | Detailed LLM app creation guide |
| `hl-add-voice-instructions.md` | Add speech-to-text / text-to-speech to any app |

### Pattern Skills (Reference)
| File | Description |
|---|---|
| `hl-monitoring.md` | Continuous video monitoring with periodic VLM analysis |
| `hl-event-detection.md` | Detect specific events from VLM responses |
| `hl-camera.md` | Camera setup, discovery, and management (USB, RPi, RTSP) |
| `hl-model-management.md` | HEF model resolution, download, and configuration |

### Meta Skills
| File | Description |
|---|---|
| `hl-plan-and-execute.md` | Orchestrated multi-phase workflow: plan, delegate, execute, gate |
| `hl-validate.md` | 5-level validation: structural, imports, functional, conventions, lint |

## Toolsets (`toolsets/`)

API references for frameworks and libraries used in Hailo apps.

| File | Description |
|---|---|
| `hailo-sdk.md` | Hailo Platform SDK: VDevice, VLM, LLM, Speech2Text, GStreamer buffer API |
| `gstreamer-elements.md` | GStreamer elements catalog: Hailo-specific and standard elements |
| `vlm-backend-api.md` | VLM Backend class: constructor, vlm_inference(), thread safety |
| `core-framework-api.md` | Core framework: resolve_hef_path, parsers, logger, HailoInfer, GStreamerApp |
| `gen-ai-utilities.md` | Gen AI utilities: LLM streaming, voice processing, agent tools |

## Knowledge (`knowledge/`)

Structured knowledge bases in YAML format for agent decision-making.

| File | Description |
|---|---|
| `knowledge_base.yaml` | Operational knowledge: tuning recipes, bottleneck patterns, gen AI recipes |

> **TODO**: Merge additional knowledge bases from community repo (app_catalog.yaml, decision_tree.yaml, code_snippets.yaml, pipeline_patterns.yaml, model_compatibility.yaml, best_practices.yaml, troubleshooting.yaml)

## Memory (`memory/`)

Persistent cross-session knowledge base. Read at task start, update when discovering new patterns.

| File | When to Read |
|---|---|
| `MEMORY.md` | Always — unified index of all memory files |
| `gen_ai_patterns.md` | Building Gen AI apps — VLM/LLM architecture, multiprocessing, gotchas |
| `pipeline_optimization.md` | Profiling or optimizing pipelines — bottleneck fixes, FPS strategy |
| `camera_and_display.md` | Camera or display work — USB/RPi/RTSP setup, BGR/RGB, OpenCV patterns |
| `hailo_platform_api.md` | Using HailoRT directly — VDevice, HEF resolution, SDK API patterns |
| `common_pitfalls.md` | Always useful — import errors, signal handling, multiprocessing gotchas |

> **TODO**: Add gesture_detection.md, tappas_coordinate_spaces.md, audio_issues.md from community repo

## Agents (`agents/`)

Platform-neutral agent definitions. The generator converts these to platform-specific formats.

| File | Description |
|---|---|
| `hailo-app-builder.md` | Master router — classifies user request and routes to specialist |
| `hailo-vlm-builder.md` | VLM app builder specialist |
| `hailo-pipeline-builder.md` | GStreamer pipeline app builder specialist |
| `hailo-standalone-builder.md` | Standalone inference app builder specialist |
| `hailo-llm-builder.md` | LLM chat app builder specialist |
| `hailo-agent-builder.md` | Agent with tool calling builder specialist |
| `hailo-voice-builder.md` | Voice assistant builder specialist |

### Neutral Format

Agent files use platform-neutral YAML frontmatter:
- `name`, `description`, `argument-hint` — identity
- `capabilities` — abstract capability list (read, edit, execute, search, etc.)
- `routes-to` — sub-agent routing targets

Body content uses `<!-- INTERACTION: question \n OPTIONS: opt1 | opt2 -->` markers for platform-specific question UI. The generator converts these to:
- **Copilot**: `askQuestions:` blocks
- **Claude**: Natural language prompts
- **Cursor**: Inline guidance text

## Contextual Rules (`contextual-rules/`)

File-pattern-triggered context rules. Each file has a `glob` in YAML frontmatter and body content that's injected when the user edits matching files.

| File | Glob Pattern | Triggers When Editing |
|---|---|---|
| `core-framework.md` | `**/core/**` | Core framework files |
| `gen-ai-apps.md` | `**/gen_ai_apps/**` | Gen AI app files |
| `pipeline-apps.md` | `**/pipeline_apps/**` | Pipeline app files |
| `standalone-apps.md` | `**/standalone_apps/**` | Standalone app files |
| `tests.md` | `tests/**` | Test files |

## Prompts (`prompts/`)

Build prompt templates. Platform-neutral markdown — the generator wraps them for each platform.

| File | Description |
|---|---|
| `dog-monitor-app.md` | Orchestrated dog monitoring VLM build |
| `dog-monitor-flat.md` | Flat (single-prompt) dog monitoring build |
| `new-vlm-variant.md` | Create a VLM app variant |
| `new-pipeline-app.md` | Create a pipeline app |
| `new-standalone-app.md` | Create a standalone app |
| `new-llm-app.md` | Create an LLM app |
| `new-agent-tool.md` | Create an agent tool |
| `new-voice-app.md` | Create a voice app |
| `orchestrated-build.md` | Meta-template for orchestrated builds |

## Platform Integration

This directory is the source of truth. Platform-specific files are **generated** from it:

| Platform | Entry Point | Generated To | Generator Command |
|---|---|---|---|
| GitHub Copilot | `.github/copilot-instructions.md` | `.github/` | `hailo-generate-platforms --platform copilot` |
| Claude Code | `CLAUDE.md` | `.claude/` | `hailo-generate-platforms --platform claude` |
| Cursor | `.cursor/rules/` | `.cursor/` | `hailo-generate-platforms --platform cursor` |
| Any AI agent | Direct | Read `.hailo/` files | N/A |

### Developer Workflow

```bash
# Edit the source of truth
vim .hailo/skills/hl-build-vlm-app.md

# Regenerate all platform configs
python .hailo/scripts/generate_platforms.py --generate

# Verify nothing is stale
python .hailo/scripts/generate_platforms.py --check

# Commit both source and generated output
git add .hailo/ .github/ .claude/ .cursor/ CLAUDE.md
git commit -m "Update VLM skill"
```
