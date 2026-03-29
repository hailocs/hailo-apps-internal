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
└── scripts/                           ← Generator, validation & curation scripts
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
| `hl-app-builder.md` | Master router — classifies user request and routes to specialist |
| `hl-vlm-builder.md` | VLM app builder specialist |
| `hl-pipeline-builder.md` | GStreamer pipeline app builder specialist |
| `hl-standalone-builder.md` | Standalone inference app builder specialist |
| `hl-llm-builder.md` | LLM chat app builder specialist |
| `hl-agent-builder.md` | Agent with tool calling builder specialist |
| `hl-voice-builder.md` | Voice assistant builder specialist |

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
| GitHub Copilot | `.github/copilot-instructions.md` | `.github/` | `python .hailo/scripts/generate_platforms.py --generate --platform copilot` |
| Claude Code | `CLAUDE.md` | `.claude/` | `python .hailo/scripts/generate_platforms.py --generate --platform claude` |
| Cursor | `.cursor/rules/` | `.cursor/` | `python .hailo/scripts/generate_platforms.py --generate --platform cursor` |
| Any AI agent | Direct | Read `.hailo/` files | N/A |

> **Note**: `CLAUDE.md` at the repo root is a generated entry point that points Claude Code to `.hailo/` and `.claude/`. It is NOT hand-maintained — it is regenerated by `generate_platforms.py`. The actual Claude Code agent configs live in `.claude/` (also generated from `.hailo/`).

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

---

## Scripts (`scripts/`)

Automation scripts for validation, curation, platform sync, and publishing.

| Script | Who runs it | Description |
|--------|-----------|-------------|
| `validate_app.py` | Maintainer / agent | Static convention checks (~15 checks: files, syntax, imports, logger, SIGINT, README quality) |
| `validate_app.py --smoke-test` | Maintainer / agent | Adds runtime checks: CLI `--help` and module import (gracefully skips on non-Hailo systems) |
| `curate_contributions.py --scan` | Anyone | Lists all contributions and community apps with VALID/INVALID status |
| `curate_contributions.py --curate` | Maintainer | Processes contributions into `.hailo/` using the tiered curation system (see below) |
| `curate_contributions.py --promote` | Maintainer | Moves a community app to official `hailo_apps/`, registers in `defines.py` + `resources_config.yaml` |
| `curate_and_propose.py` | Maintainer | Runs curation + platform sync + opens internal PR (all-in-one) |
| `push_community_apps.py` | Maintainer | Pushes community apps to public `hailo-ai/hailo-rpi5-examples` repo as PRs |
| `generate_platforms.py --generate` | Maintainer | Syncs `.hailo/` → `.github/` + `.claude/` + `.cursor/` |
| `generate_platforms.py --check` | CI / Maintainer | Verifies generated files are in sync with `.hailo/` |

---

## Community Workflow

### The Three Repos

| Repo | Visibility | Purpose |
|------|-----------|---------|
| `hailo-apps-internal` (this repo) | Private | Development, staging, agentic knowledge base |
| `hailo-ai/hailo-rpi5-examples` | Public | Where community users find and use example apps |
| Community user's fork | Public | Where users prepare their contributions |

### How Community Users Contribute

**Contributing an app:**
```
Fork this repo → create community/apps/<type>/<app_name>/
  ├── app.yaml, <app_name>.py, __init__.py, run.sh, README.md
  → Open PR to this repo
```

**Contributing a knowledge finding:**
```
Fork this repo → create community/contributions/<category>/YYYY-MM-DD_<app>_<slug>.md
  (YAML frontmatter + 6 required sections)
  → Open PR to this repo
```

**Agent-assisted:** An AI agent builds the app and/or generates a contribution recipe during a session. The user reviews and opens a PR.

### Contribution Categories

| Category | Tier 1 target (full append) | Tier 2 targets (summary in `## Community Findings`) |
|----------|---------------------------|-----------------------------------------------------|
| `pipeline-optimization` | `memory/pipeline_optimization.md` | `hl-build-pipeline-app.md`, `gstreamer-pipelines.md`, `gstreamer-elements.md` |
| `bottleneck-patterns` | `memory/pipeline_optimization.md` | `hl-build-pipeline-app.md` |
| `gen-ai-recipes` | `memory/gen_ai_patterns.md` | `hl-build-vlm-app.md`, `hl-build-llm-app.md`, `gen-ai-utilities.md` |
| `hardware-config` | `memory/hailo_platform_api.md` | `hailo-sdk.md` |
| `model-tuning` | `knowledge/best_practices.yaml` | `hl-model-management.md` |
| `camera-display` | `memory/camera_and_display.md` | `hl-camera.md` |
| `voice-audio` | `memory/gen_ai_patterns.md` | `hl-build-voice-app.md`, `gen-ai-utilities.md` |
| `general` | `memory/common_pitfalls.md` | *(none)* |

### Maintainer Procedures

#### 1. Review Incoming PR

```bash
# Validate an app (static + runtime)
python .hailo/scripts/validate_app.py community/apps/<type>/<app_name> --smoke-test

# Scan contributions for validity
python .hailo/scripts/curate_contributions.py --scan
```

If OK → merge the PR.

#### 2. Curate Knowledge (Tiered System)

```bash
# Interactive: review each contribution
python .hailo/scripts/curate_contributions.py --curate

# Auto-accept all valid contributions
python .hailo/scripts/curate_contributions.py --curate --auto
```

**Tiered curation:**

| Tier | Behavior | Target files |
|------|----------|-------------|
| **Tier 1** (full append) | Complete contribution appended | `memory/*.md`, `knowledge/*.yaml` |
| **Tier 2** (summary append) | 3-line summary with cross-reference to Tier 1 entry | `## Community Findings` sections in skills, toolsets, instructions |
| **Tier 3** (never auto-modified) | Core structural files | `coding-standards.md`, `agent-protocols.md`, `orchestration.md` |

After curation, original contribution files are **deleted** (knowledge now lives in `.hailo/`).

#### 3. Sync Platforms

```bash
# Regenerate .github/, .claude/, .cursor/ from .hailo/
python .hailo/scripts/generate_platforms.py --generate
```

Or use the all-in-one wrapper:
```bash
# Curate + sync + open PR
python .hailo/scripts/curate_and_propose.py
```

#### 4. Promote Community App to Official

```bash
python .hailo/scripts/curate_contributions.py --promote <app_name>
```

This: validates → copies to `hailo_apps/python/<type>/` → registers in `defines.py` + `resources_config.yaml` → deletes community copy.

#### 5. Push to Public RPi Examples Repo

```bash
# Preview what would be pushed
python .hailo/scripts/push_community_apps.py --dry-run

# Push one app (requires gh CLI authentication)
python .hailo/scripts/push_community_apps.py --app <app_name>
```

This clones `hailo-ai/hailo-rpi5-examples`, copies the app to `community_projects/<app_name>/`, generates README + requirements.txt, updates the `community_projects.md` index, and opens a PR.

### Visual Flow

```
COMMUNITY USER                          MAINTAINER
──────────────                          ──────────
Fork repo                              
Create app or contribution              
Open PR ──────────────────────────────→ Review PR
                                        validate_app.py --smoke-test
                                        Merge PR
                                            │
                                        curate_contributions.py --curate
                                        │   Tier 1: full → memory/*.md
                                        │   Tier 2: summary → skills/*.md
                                        │   Delete originals
                                        │
                                        generate_platforms.py --generate
                                        │   .hailo/ → .github/ + .claude/
                                        │
                                        curate_contributions.py --promote
                                        │   community/ → hailo_apps/ + defines.py
                                        │
                                        push_community_apps.py
                                            Opens PR to hailo-rpi5-examples
```
