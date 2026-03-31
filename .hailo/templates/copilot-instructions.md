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

> **Do NOT read all files.** Use the routing table below to load **only** the files relevant to the current task. This saves tokens and keeps context focused.

### Context Routing Table

Based on what the task involves, read **only** the matching rows:

| If the task mentions... | Read these files |
|---|---|
| **VLM, vision, image understanding** | `skills/hl-build-vlm-app/SKILL.md`, `toolsets/vlm-backend-api.md`, `memory/gen_ai_patterns.md` |
| **LLM, chat, text generation** | `skills/hl-build-llm-app/SKILL.md`, `instructions/gen-ai-development.md`, `toolsets/gen-ai-utilities.md`, `memory/gen_ai_patterns.md` |
| **Agent, tools, function calling** | `skills/hl-build-agent-app/SKILL.md`, `toolsets/gen-ai-utilities.md`, `memory/gen_ai_patterns.md` |
| **Voice, STT, TTS, Whisper, speech** | `skills/hl-build-voice-app/SKILL.md`, `toolsets/gen-ai-utilities.md` |
| **Pipeline, GStreamer, video, stream** | `skills/hl-build-pipeline-app/SKILL.md`, `instructions/gstreamer-pipelines.md`, `toolsets/gstreamer-elements.md`, `memory/pipeline_optimization.md` — **Fast path for simple variants** (detection filter, counter, custom overlay): SKILL.md + `memory/common_pitfalls.md` is sufficient |
| **Game, interactive, pose game** | `skills/hl-build-pipeline-app/SKILL.md`, `toolsets/pose-keypoints.md`, `toolsets/core-framework-api.md`, `memory/common_pitfalls.md` |
| **Standalone, OpenCV, HailoInfer** | `skills/hl-build-standalone-app/SKILL.md`, `toolsets/core-framework-api.md` |
| **Camera, USB, RPi, capture** | `skills/hl-camera.md`, `memory/camera_and_display.md` |
| **HEF, model, download, config** | `skills/hl-model-management.md`, `toolsets/hailort-api.md`, `memory/hailo_platform_api.md` |
| **Monitoring, events, alerts** | `skills/hl-monitoring.md`, `skills/hl-event-detection.md` |
| **Testing, validation, pytest** | `skills/hl-validate.md`, `instructions/testing-patterns.md` |
| **Complex multi-file app** | `instructions/orchestration.md`, `skills/hl-plan-and-execute.md`, `instructions/agent-protocols.md` |
| **Building any new app** | The specialist agent (loaded via VS Code `@agent`) handles interactive flow. If not using agents, read `instructions/orchestration.md` and the relevant `skills/hl-build-*/SKILL.md` |
| **ALWAYS read (every task)** | `memory/common_pitfalls.md`, `instructions/coding-standards.md` |

All paths above are relative to `.github/`. The knowledge base at `.github/knowledge/knowledge_base.yaml` can be checked when you need recipes or patterns.

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

## Interactive Design (MANDATORY — Phase 0)

> **HARD GATE**: You MUST ask the user 2-3 real design questions and get answers BEFORE writing any code or reading SKILL.md files. A rubber-stamp "Ready to build?" confirmation does NOT count. The questions must surface actual design choices the user cares about.

**When to ask** — ALWAYS, unless the user explicitly says "just build it", "use defaults", or "skip questions".

**What to ask** — Pick 2-3 from this list depending on app type. Use `ask_questions` with concrete options:

| App type | Question 1 | Question 2 | Question 3 |
|---|---|---|---|
| **VLM / monitoring** | App style? (continuous monitor, interactive chat, scene logger) | What to track? (activities, objects, safety hazards, custom) | Output? (display overlay, terminal log, file, alerts) |
| **Pipeline / video** | What processing? (detection, pose, segmentation, tracking) | Display? (bounding boxes, custom overlay, game, headless) | Input? (USB camera, RPi camera, RTSP, video file) |
| **Standalone / OpenCV** | Inference task? (classification, detection, segmentation) | Input? (single image, batch, camera, video) | Output? (display, JSON, annotated image, CSV) |
| **Gen AI / LLM / agent** | Interaction mode? (chat, tool-calling agent, pipeline) | What tools/capabilities? | Input? (text, voice, vision) |

**Anti-pattern (DO NOT DO THIS)**:
```
❌ Present a fully-formed plan → ask "Build it?" → build on approval
   This is a rubber stamp. The user had no input into the design choices.
```

**Correct pattern**:
```
✅ Ask 2-3 questions with concrete options → incorporate answers → present plan → build
   The user shaped the design. Misunderstandings are caught before code is written.
```

## Execution Speed Rules

> Agents MUST follow these rules to minimize tool calls and eliminate redundant work.

1. **SKILL.md is sufficient** — Do NOT read reference source code (vlm_chat.py, backend.py, pose_estimation.py, etc.). SKILL.md + common_pitfalls.md contain 100% of the context needed for standard builds. Do NOT launch sub-agents to find source code that SKILL.md already documents.
2. **Read SKILL.md fully in one call** — SKILL.md files are <400 lines. Read the entire file in a single `read_file` call. Never split into partial reads (e.g., lines 1-300 then 300-600) — that wastes a round trip.
3. **Minimum context = SKILL.md + common_pitfalls.md** — For any standard app build, read exactly these two files in parallel, then build. Do not read coding-standards.md, toolset refs, or source code unless SKILL.md is genuinely missing a pattern.
4. **validate_app.py is the single gate** — Run `python3 .github/scripts/validate_app.py <app_dir> --smoke-test` instead of manual grep/import/lint checks. One command, one gate.
5. **Community apps don't need registration** — Don't register in `defines.py` or `resources_config.yaml`. Community apps are run via `run.sh`.
6. **Parallelize independent operations** — Batch reads together, batch file creates together.
7. **Pre-launch device check** — Always run `hailortcli fw-control identify` before launching any Hailo app. Do NOT use `lsmod | grep hailo_pci` (unreliable).
8. **USB camera: always `--input usb`** — Never hardcode `/dev/video0`. Use `--input usb` for auto-detection. `/dev/video0` is typically the integrated webcam, not the USB camera.
9. **Always `python3`** — Never use bare `python` in terminal commands. Ubuntu/Debian only has `python3`.
10. **Background terminals need venv** — `isBackground=true` spawns a new shell without the venv. Always chain: `source setup_env.sh && python3 ...`

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
PHASE 3: VALIDATE  → Run validate_app.py --smoke-test (single gate check)
         GATE      → All checks pass (fix and re-run if not)
PHASE 4: DOCUMENT  → Write README.md (required), update memory if needed
         GATE      → README.md exists and is non-empty, final validation, all todos complete
```

### Key Protocols

1. **Route context** — Use the routing table to load only relevant files
2. **Context first** — NEVER write code before reading routed context files
3. **Phase gates** — NEVER advance to next phase until current gate passes
4. **Sub-agents** — Delegate independent reads and module builds; keep sequential edits in main agent
5. **Todo tracking** — Use `manage_todo_list` with explicit GATE items
6. **Memory loop** — Update `.github/memory/` when new patterns or pitfalls are discovered
7. **Recovery** — On gate failure: read error → check memory → fix → re-run gate
8. **Speed** — Fast-path clear requests, skip source code reads, use validate_app.py as single gate
9. **Device check** — Always `hailortcli fw-control identify` before launching apps

### Agent Workflow Steps

1. **Match task to routing table** — identify which files to load
2. **Read only routed files** from `.github/` (via sub-agent for speed)
3. **Create todo list** with phases and explicit GATE items
4. **Execute phase-by-phase** using sub-agents where appropriate
5. **Validate at every gate** — never skip
6. **Follow conventions** exactly (see Critical Conventions above)
7. **Document** — Write README.md (REQUIRED deliverable — never skip). Update memory if new patterns discovered

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
| YOLO class IDs / labels | `toolsets/yolo-coco-classes.md` or `local_resources/coco.txt` |

## Agentic Development Files

```
.github/
├── copilot-instructions.md          ← You are here (global instructions)
├── agents/
│   ├── hl-app-builder.agent.md        ← Router agent: delegates to specialist builders
│   ├── hl-vlm-builder.agent.md        ← Specialist: VLM applications
│   ├── hl-pipeline-builder.agent.md   ← Specialist: GStreamer pipeline apps
│   ├── hl-standalone-builder.agent.md ← Specialist: Standalone inference apps
│   ├── hl-agent-builder.agent.md      ← Specialist: Agent with tool calling
│   ├── hl-llm-builder.agent.md        ← Specialist: LLM text generation apps
│   └── hl-voice-builder.agent.md      ← Specialist: Voice-enabled apps
├── instructions/
│   ├── architecture.md              ← System architecture deep dive
│   ├── coding-standards.md          ← Code style & conventions
│   ├── gen-ai-development.md        ← Gen AI app development guide
│   ├── gstreamer-pipelines.md       ← GStreamer pipeline patterns
│   ├── testing-patterns.md          ← Test writing guide
│   ├── orchestration.md             ← Multi-agent orchestration framework
│   ├── agent-protocols.md           ← Agent behavioral contracts
│   ├── gen-ai-apps.instructions.md  ← Auto-loaded for gen_ai_apps/** files
│   ├── pipeline-apps.instructions.md ← Auto-loaded for pipeline_apps/** files
│   ├── standalone-apps.instructions.md ← Auto-loaded for standalone_apps/** files
│   ├── core-framework.instructions.md ← Auto-loaded for core/** files
│   └── tests.instructions.md        ← Auto-loaded for tests/** files
├── skills/
│   ├── hl-build-vlm-app/SKILL.md    ← Skill: Build VLM applications
│   ├── hl-build-pipeline-app/SKILL.md ← Skill: Build GStreamer pipeline apps
│   ├── hl-build-standalone-app/SKILL.md ← Skill: Build standalone inference apps
│   ├── hl-build-agent-app/SKILL.md  ← Skill: Build agent with tool calling
│   ├── hl-build-llm-app/SKILL.md    ← Skill: Build LLM text generation apps
│   ├── hl-build-voice-app/SKILL.md  ← Skill: Build voice-enabled apps
│   ├── hl-monitoring.md             ← Skill: Continuous monitoring patterns
│   ├── hl-event-detection.md        ← Skill: Detect & report events from video
│   ├── hl-camera.md                 ← Skill: Camera setup & management
│   ├── hl-model-management.md       ← Skill: HEF resolution & model config
│   ├── hl-plan-and-execute.md       ← Skill: Plan-and-execute loop pattern
│   └── hl-validate.md               ← Skill: Validation at every phase gate
├── prompts/
│   ├── orchestrated-build.prompt.md ← Meta-template: Orchestrated build (any app)
│   ├── new-vlm-variant.prompt.md    ← Template: Create VLM app variant
│   ├── new-pipeline-app.prompt.md   ← Template: Create pipeline app
│   ├── new-standalone-app.prompt.md ← Template: Create standalone app
│   ├── new-llm-app.prompt.md        ← Template: Create LLM app
│   ├── new-voice-app.prompt.md      ← Template: Create voice app
│   ├── new-pose-game.prompt.md      ← Template: Create pose estimation game
│   └── new-agent-tool.prompt.md     ← Template: Create new agent tool
├── toolsets/
│   ├── hailort-api.md                 ← HailoRT API reference
│   ├── gstreamer-elements.md        ← Available GStreamer elements
│   ├── vlm-backend-api.md           ← VLM Backend class API
│   ├── core-framework-api.md        ← Core framework API reference
│   ├── gen-ai-utilities.md          ← Gen AI utilities reference
│   ├── yolo-coco-classes.md         ← YOLO COCO 80-class label reference
│   └── pose-keypoints.md            ← COCO 17 pose keypoints, skeleton, coordinate transform
├── memory/
│   ├── MEMORY.md                    ← Index + quick reference
│   ├── gen_ai_patterns.md           ← VLM/LLM patterns & gotchas
│   ├── pipeline_optimization.md     ← Pipeline bottleneck fixes
│   ├── camera_and_display.md        ← Camera & OpenCV patterns
│   ├── hailo_platform_api.md        ← SDK usage patterns
│   └── common_pitfalls.md           ← Bugs & anti-patterns
├── knowledge/
│   └── knowledge_base.yaml          ← Machine-readable recipes & patterns
├── scripts/
│   ├── generate_platforms.py        ← Generator: .hailo/ → platform-specific files
│   ├── validate_framework.py        ← Cross-reference integrity validator (routing table, file tree, leaks)
│   └── validate_app.py              ← Validate scaffolded app conventions (--smoke-test for runtime checks)
CLAUDE.md                             ← Claude Code entry point (root)
```
