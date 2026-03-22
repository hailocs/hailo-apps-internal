# Agentic-First Development for Hailo Apps — Session Summary

> **Objective**: Make the hailo-apps repository fully **agentic-first** — enabling AI coding agents to build complete, production-ready Hailo AI applications from a single prompt, with zero manual coding.

---

## Executive Summary

We have built a comprehensive agentic development infrastructure for the hailo-apps repository. An AI coding agent (GitHub Copilot, Claude Code, or any LLM-based agent) can now receive a structured prompt from a ready-made template — and autonomously produce a complete, convention-compliant, production-ready application by reading structured instructions, skills, and API references checked into the repository.

The prompt templates (stored in `.github/prompts/`) contain the full application specification: what to build, which modules to reuse, which conventions to follow, where to place files, and how to validate the result. The user copies one of these prompts into chat and the infrastructure handles the rest.

**Two approaches are supported**:

| Approach | Best For | Agent Behavior |
|---|---|---|
| **Flat (Simple)** | Small-to-medium apps, well-scoped tasks | Agent uses auto-loaded conventions + own judgment |
| **Orchestrated (Multi-Phase)** | Complex multi-file apps, reproducibility, auditability | Agent follows prescribed 4-phase workflow with gates, sub-agents, memory updates |

**Key metrics** (matching the 9 categories in the [File Inventory](#file-inventory-by-category) below):

| # | Category | Files | Lines | Highlights |
|---|---|---|---|---|
| 1 | Agent entry points | 2 | 310 | Auto-loaded by Copilot + Claude Code |
| 2 | Architecture & standards | 5 | 794 | Coding conventions, system design |
| 3 | Orchestration framework | 2 | 674 | Phase gates, sub-agent delegation, 9 agent protocols |
| 4 | Skills | 11 | 1,678 | Step-by-step guides per app archetype |
| 5 | API toolset references | 5 | 816 | Function-level SDK documentation |
| 6 | Prompt templates | 6 | 790 | Ready-to-paste prompts (flat + orchestrated) |
| 7 | Persistent memory | 6 | 524 | Cross-session knowledge retention |
| 8 | Knowledge base | 1 | 103 | Machine-readable YAML recipes & patterns |
| 9 | Community contributions | 6 | 63 | Contribution structure (5 category dirs + README) |
| | **Total** | **44** | **~5,752** | |

---

## What Was Built

### Why These Categories?

The file categories below are not arbitrary — they follow established patterns from the agentic development community (used in projects like Claude Code's `CLAUDE.md`, Cursor Rules, Windsurf, and GitHub Copilot's `.github/copilot-instructions.md`). Each category serves a specific role in how AI agents reason and execute:

| Category | Role in Agentic Workflow | Analogy |
|---|---|---|
| **Entry points** | First thing the agent reads — orients it to the project | The "front door" |
| **Instructions** | Deep reference material the agent consults as needed | The "textbook" |
| **Skills** | Step-by-step recipes for specific tasks | The "cookbook" |
| **Toolsets** | API documentation so the agent uses APIs correctly | The "API reference manual" |
| **Prompts** | Pre-written task specifications ready to execute | The "work orders" |
| **Memory** | Persistent lessons learned from previous sessions | The "institutional knowledge" |
| **Knowledge base** | Machine-readable patterns for automated lookup | The "indexed database" |
| **Community** | Crowdsourced insights that feed back into the system | The "field notes" |

The key insight: **without these structured files, an AI agent would need to explore the entire codebase to understand conventions, discover APIs, and learn from past mistakes — burning tokens and time**. By pre-organizing knowledge into these categories, we give the agent focused, relevant context that dramatically reduces cost and improves output quality.

### File Inventory by Category

#### 1. Agent Entry Points (2 files)

These are auto-loaded by the respective AI agents and serve as the "table of contents" for all other files.

| File | Lines | Purpose |
|---|---|---|
| `.github/copilot-instructions.md` | 162 | **GitHub Copilot entry point** — auto-loaded when Copilot Chat opens. Contains repo identity, critical conventions, orchestration overview, file reference map, and directory index. |
| `CLAUDE.md` | 148 | **Claude Code entry point** — auto-loaded by Claude Code. Mirrors copilot-instructions.md with Claude-specific formatting. Also serves any agent that reads root-level markdown. |

#### 2. Architecture & Standards (5 files — 794 lines)

Deep-dive reference documents for code conventions and system architecture.

| File | Lines | Purpose |
|---|---|---|
| `.github/instructions/architecture.md` | 171 | Three-tier app architecture (pipeline / standalone / gen-ai), module dependency graph, config system, hardware support matrix |
| `.github/instructions/coding-standards.md` | 193 | Import rules, logging conventions, HEF resolution, VDevice sharing, CLI parsers, error handling, signal handling, environment variables |
| `.github/instructions/gen-ai-development.md` | 161 | VLM/LLM/Whisper development patterns, minimal VLM inference code, image preprocessing, multiprocessing backend, voice integration |
| `.github/instructions/gstreamer-pipelines.md` | 165 | GStreamer pipeline composition, all available pipeline fragments, architecture patterns, callback patterns, element reference |
| `.github/instructions/testing-patterns.md` | 104 | pytest framework, markers, fixtures, test patterns, running commands |

#### 3. Orchestration Framework (2 files — 674 lines)

The multi-agent orchestration system — phase gates, sub-agent delegation, and recovery protocols.

| File | Lines | Purpose |
|---|---|---|
| `.github/instructions/orchestration.md` | 401 | **Master orchestration guide**: Phase 0-4 definitions with gate checklists, sub-agent delegation patterns (context loader, module builder, validator), plan-and-execute protocol, concurrency model diagram, anti-patterns table |
| `.github/instructions/agent-protocols.md` | 273 | **9 behavioral contracts**: context-first execution, explicit phase gates, todo management, sub-agent delegation matrix, convention verification scripts, memory feedback loop, graceful recovery ladder, Copilot Coding Agent (Issues) workflow, multi-file atomic changes |

#### 4. Skills (11 files — 1,678 lines)

Step-by-step guides for specific development tasks. Each skill contains patterns, code templates, and validation commands.

| File | Lines | Skill |
|---|---|---|
| `.github/instructions/skills/create-vlm-app.md` | 128 | Build VLM-based applications (register → backend → app → README) |
| `.github/instructions/skills/create-pipeline-app.md` | 115 | Build GStreamer pipeline apps with composition patterns |
| `.github/instructions/skills/create-standalone-app.md` | 108 | Build standalone HailoInfer + OpenCV apps |
| `.github/instructions/skills/create-agent-app.md` | 111 | Build LLM agents with tool calling |
| `.github/instructions/skills/add-voice-mode.md` | 97 | Add STT/TTS voice input/output to any app |
| `.github/instructions/skills/continuous-monitoring.md` | 166 | Timer-based capture loops, event logging, session summaries |
| `.github/instructions/skills/event-detection.md` | 163 | EventType enums, keyword parsing, alert management |
| `.github/instructions/skills/camera-integration.md` | 121 | Camera types (USB/RPi/file), discovery, color spaces |
| `.github/instructions/skills/model-management.md` | 129 | HEF resolution, config manager, adding new models |
| `.github/instructions/skills/plan-and-execute.md` | 255 | **Orchestration skill**: The plan→delegate→execute→gate loop |
| `.github/instructions/skills/validate-and-test.md` | 285 | **Validation skill**: 5 validation levels, convention checklist, test templates |

#### 5. API Toolset References (5 files — 816 lines)

Function-level API documentation for the frameworks used in Hailo apps.

| File | Lines | API Coverage |
|---|---|---|
| `.github/toolsets/hailo-sdk.md` | 178 | VDevice, VLM, LLM, Speech2Text, GStreamer buffer API, constants |
| `.github/toolsets/gstreamer-elements.md` | 121 | All Hailo + standard GStreamer elements, helper function mapping |
| `.github/toolsets/vlm-backend-api.md` | 127 | Backend class: constructor, vlm_inference, convert_resize_image, worker process |
| `.github/toolsets/core-framework-api.md` | 198 | resolve_hef_path, parsers, HailoInfer, camera_utils, GStreamerApp, buffer_utils |
| `.github/toolsets/gen-ai-utilities.md` | 192 | LLM streaming/tools, voice processing (STT/TTS/VAD), agent tools framework |

#### 6. Prompt Templates (6 files — 790 lines)

Ready-to-use prompts that agents can execute directly.

| File | Lines | Purpose |
|---|---|---|
| `.github/prompts/dog-monitor-app.prompt.md` | 324 | **Demo prompt (Orchestrated)** — full Phase 0-4 orchestrated workflow with sub-agent delegation and phase gates |
| `.github/prompts/dog-monitor-flat.prompt.md` | 94 | **Demo prompt (Flat)** — simple single-shot prompt, same app specification |
| `.github/prompts/orchestrated-build.prompt.md` | 220 | **Meta-template** — universal orchestrated prompt with placeholders for any app type |
| `.github/prompts/new-vlm-variant.prompt.md` | 42 | Template for creating VLM app variants |
| `.github/prompts/new-pipeline-app.prompt.md` | 46 | Template for creating GStreamer pipeline apps |
| `.github/prompts/new-agent-tool.prompt.md` | 64 | Template for creating new agent tools |

#### 7. Persistent Memory (6 files — 524 lines)

Cross-session knowledge base. Agents read these at task start and update them when discovering new patterns.

| File | Lines | Domain |
|---|---|---|
| `.github/memory/MEMORY.md` | 37 | Index of all memory files, key project patterns, update rules |
| `.github/memory/gen_ai_patterns.md` | 82 | VLM/LLM architecture, multiprocessing backend, token streaming, known issues |
| `.github/memory/pipeline_optimization.md` | 64 | GStreamer bottleneck patterns, scheduler-timeout fix, queue tuning |
| `.github/memory/camera_and_display.md` | 98 | Camera types, color spaces, USB discovery, OpenCV display patterns |
| `.github/memory/hailo_platform_api.md` | 114 | VDevice creation, HEF resolution chain, model classes, architecture detection |
| `.github/memory/common_pitfalls.md` | 129 | Import errors, signal handling, multiprocessing gotchas, resource cleanup |

#### 8. Knowledge Base (1 file — 103 lines)

Machine-readable YAML with recipes, bottleneck patterns, and indexed insights.

| File | Lines | Contents |
|---|---|---|
| `.github/knowledge/knowledge_base.yaml` | 103 | 3 gen-AI recipes, 1 pipeline recipe, 5 bottleneck patterns, 8 tagged insights |

#### 9. Community Contributions (6 files)

Structure for community-contributed patterns and insights.

| File | Purpose |
|---|---|
| `community/contributions/README.md` | Contribution format, categories, YAML frontmatter template |
| `community/contributions/pipeline-optimization/.gitkeep` | Pipeline tuning contributions |
| `community/contributions/bottleneck-patterns/.gitkeep` | Performance bottleneck fixes |
| `community/contributions/gen-ai-recipes/.gitkeep` | Gen AI application recipes |
| `community/contributions/hardware-config/.gitkeep` | Hardware-specific configurations |
| `community/contributions/general/.gitkeep` | General insights |

---

## The Two Approaches

Both approaches produce the same application. The difference is **how much process control you impose** — and the tradeoff is **cost vs. risk reduction**.

### Shared Foundation: Both Approaches Use Our Infrastructure

Both the flat and orchestrated approaches benefit from the **same 44-file infrastructure**. Most importantly, `copilot-instructions.md` is **auto-loaded by Copilot** (and `CLAUDE.md` by Claude Code) — giving the agent conventions, file references, memory pointers, and the full project map **for free** (no extra tokens spent). This shared foundation is why the flat approach works well: it's not running "blind" — it has the entire convention system available.

The difference between the two approaches is **what the prompt adds on top of that foundation**:

| Shared foundation (both approaches get this) | Added by orchestrated prompt only |
|---|---|
| `copilot-instructions.md` auto-loaded (conventions, file map, critical rules) | Explicit instruction to read 15 specific files via sub-agent |
| Memory files referenced (agent *can* read them) | **Required** memory reads before writing any code |
| Skills and toolsets available if agent looks for them | Specific skill files prescribed per phase |
| Agent has built-in todos, sub-agents, validation tools | **Exactly** 14 todos, 3-4 sub-agents, 4 gate checks prescribed |
| General coding knowledge + Hailo conventions | Step-by-step phase sequence with no skipping allowed |

In other words: the flat approach says "here's what to build — figure out how." The orchestrated approach says "here's what to build and **exactly** how to do it, step by step."

### Approach 1: Flat (Simple) Prompt

**File**: `.github/prompts/dog-monitor-flat.prompt.md`

**How it works**: A self-contained prompt describes what to build. The agent receives `copilot-instructions.md` (auto-loaded) which describes conventions, memory files, and the orchestrated workflow. The agent **uses its built-in tools however it sees fit** — it decides which files to read, whether to launch sub-agents, and whether to validate. It will likely use todos and sub-agents (because the model does that naturally), but the *specifics* of what it does are non-deterministic.

```
┌──────────────────┐     ┌──────────────────────────────┐     ┌──────────────────┐
│   User pastes    │ ──▶ │  Agent uses built-in tools    │ ──▶ │  Agent writes    │
│   flat prompt    │     │  (todos, sub-agents, reads)    │     │  all code files  │
│                  │     │  as it sees fit — ad-hoc        │     │  and README      │
│                  │     │  approach, not prescribed       │     │                  │
└──────────────────┘     └──────────────────────────────┘     └──────────────────┘
```

**Key characteristic**: The flat prompt doesn't prescribe the workflow. The agent **will** use its tools, but:
- Which files it reads first? **Its choice** — may or may not read memory files
- How many sub-agents? **Its choice** — may use 0, 1, or 5
- Todo structure? **Its choice** — may not match the ideal phases
- Validation? **Its choice** — may skip or run different checks
- Memory/community update? **Its choice** — likely skips unless prompted

This means the flat approach **produces different results each run** — the agent may take a different path each time.

**Pros**: Dramatically cheaper (~10x fewer tokens), faster, same output quality for well-scoped tasks.
**Cons**: Non-deterministic, may miss conventions on complex tasks, may skip validation, no guaranteed knowledge updates.

**When to use**: Small-to-medium apps (1-6 files), well-defined archetypes, when the auto-loaded conventions provide sufficient guardrails.

### Approach 2: Orchestrated (Multi-Phase) Prompt

**File**: `.github/prompts/dog-monitor-app.prompt.md`

**How it works**: The prompt **explicitly prescribes** how the agent should use its built-in tools. It lists exactly which 15 files to read, which sub-agents to launch with which prompts, which phases to follow, and which validation commands to run at each gate. The same built-in tools are used — but **deterministically**.

```
┌─────────┐     ┌─────────┐     ┌─────────┐     ┌─────────┐     ┌─────────┐
│ PHASE 0 │ ──▶ │ PHASE 1 │ ──▶ │ PHASE 2 │ ──▶ │ PHASE 3 │ ──▶ │ PHASE 4 │
│ Context │     │ Plan &  │     │ Build   │     │Validate │     │  Docs & │
│ Loading │     │Register │     │ Code    │     │& Test   │     │ Memory  │
│         │     │         │     │         │     │         │     │         │
│Sub-agent│     │  GATE   │     │Sub-agent│     │  GATE   │     │  GATE   │
│reads 15 │     │dir+const│     │builds   │     │--help   │     │README   │
│ files   │     │ exist?  │     │indep.   │     │lint OK? │     │ exists? │
│         │     │         │     │modules  │     │convents?│     │memory   │
│         │     │         │     │         │     │         │     │updated? │
└─────────┘     └─────────┘     └─────────┘     └─────────┘     └─────────┘
```

**What the orchestrated prompt prescribes (that the flat prompt leaves to chance)**:
- **Exactly** 15 files to read in Phase 0 (sub-agent with specific file list)
- **Exactly** 14 todo items across 4 phases with GATE checkpoints
- **Exactly** which validation commands to run at each gate
- **Required** memory file reads to avoid known pitfalls
- **Required** memory and knowledge base updates when done
- **Required** community recipe contribution

The agent uses the same built-in tools — but our infrastructure turns ad-hoc tool usage into a **repeatable, auditable process**.

**Pros**: Deterministic process, explicit validation at every phase, guaranteed knowledge updates, reproducible across runs.
**Cons**: Significantly more expensive (~10x more tokens), longer execution, more total tool calls. The overhead may not justify the cost for simple tasks.

**When to use**: Complex apps (10+ files, multiple archetypes), apps with many interdependencies, when reproducibility and auditability matter, when you want guaranteed memory/community updates.

---

## Execution Modes

All modes use the **same prompt content and infrastructure** — the difference is *where* and *when* the agent runs:

| Mode | How It Works | User Involvement | Best For |
|---|---|---|---|
| **Copilot Chat (Interactive)** | Developer pastes prompt into VS Code chat, watches agent work in real-time, can intervene | High — you're in the loop | Development, debugging, demos |
| **Copilot Coding Agent (Async)** | File a GitHub Issue with the prompt, Copilot picks it up automatically, creates a PR | None — fire and forget | Batch work, overnight builds, CI-like |
| **Claude Code (Interactive)** | Developer uses Claude Code in VS Code (extension) or terminal (CLI), same workflow | High — you're in the loop | Claude users, alternative to Copilot |

### Copilot Chat vs. Copilot Coding Agent

The key difference is **interactive vs. autonomous**:

- **Copilot Chat**: You sit in VS Code, paste the prompt, watch it work, can intervene mid-execution. Interactive.
- **Copilot Coding Agent**: You file a GitHub Issue, walk away. The agent works autonomously on a branch and opens a PR when done. No human in the loop. Best for well-specified tasks.

### Claude Code — two ways to run it

- **VS Code extension**: Install the Claude extension for VS Code. Works similarly to Copilot Chat — interactive, in the editor.
- **Terminal CLI**: Run `claude` in your terminal from the repo root. `CLAUDE.md` is auto-loaded. Same prompt content works in both modes.

### How to Use Copilot Coding Agent (GitHub Issues)

This mode is fully autonomous — no human in the loop during execution.

| Step | Action |
|---|---|
| 1 | Go to the repository on **GitHub.com** → **Issues** → **New Issue** |
| 2 | Add the label **`copilot`** (this triggers the Copilot Coding Agent) |
| 3 | Set the **title** to a clear task description, e.g., "Build Dog Monitor Application" |
| 4 | In the **issue body**, paste the prompt content from the template file (e.g., from `dog-monitor-app.prompt.md`) |
| 5 | Optionally add labels like `new-app`, `bug-fix`, or `enhancement` to classify the task |
| 6 | **Submit the issue** — Copilot Coding Agent picks it up automatically |
| 7 | The agent creates a new branch, follows the orchestrated workflow, and **opens a Pull Request** when done |
| 8 | You receive a notification when the PR is ready — **review the PR**, check the code, and merge |

> **Tip**: The orchestrated prompt works especially well with the Coding Agent because it's fully self-contained — the prompt specifies every file to read, every gate to check, and every validation to run. The agent doesn't need your guidance.

> **Issue format template** is available at the bottom of `.github/prompts/orchestrated-build.prompt.md` — ready to copy into an Issue body.

---

## How-To Guide (Copilot Chat in VS Code)

> The step-by-step guides below assume **GitHub Copilot Chat in VS Code** (the most common mode). For other modes, use the same prompt text — only the delivery mechanism changes.

### Prerequisites

1. **VS Code** with GitHub Copilot extension installed
2. **Copilot Chat** enabled (agent mode recommended — click the dropdown next to "Ask" and select "Agent")
3. The hailo-apps repository cloned locally and open in VS Code
4. `.github/copilot-instructions.md` is auto-loaded by Copilot — no manual action needed

### How to Execute: Flat Approach

| Step | Action |
|---|---|
| 1 | Open **Copilot Chat** in VS Code (Ctrl+Shift+I or click the Copilot icon) |
| 2 | Switch to **Agent mode** (dropdown next to the input box) |
| 3 | Open `.github/prompts/dog-monitor-flat.prompt.md` in the editor |
| 4 | Copy **everything under "## The Prompt"** heading |
| 5 | Paste into Copilot Chat and press Enter |
| 6 | Wait for the agent to create all files (~2-5 minutes) |
| 7 | Review the created files in `hailo_apps/python/gen_ai_apps/dog_monitor/` |
| 8 | Test: `python -m hailo_apps.python.gen_ai_apps.dog_monitor.dog_monitor --help` |

### How to Execute: Orchestrated Approach

| Step | Action |
|---|---|
| 1 | Open **Copilot Chat** in VS Code (Ctrl+Shift+I or click the Copilot icon) |
| 2 | Switch to **Agent mode** (dropdown next to the input box) |
| 3 | Open `.github/prompts/dog-monitor-app.prompt.md` in the editor |
| 4 | Copy **everything below the `---` line** in the "## The Prompt" section |
| 5 | Paste into Copilot Chat and press Enter |
| 6 | **Observe the agent behavior** — it should: |
|   | a. Launch a sub-agent to read 15 context files |
|   | b. Create a todo list with ~14 items across 4 phases |
|   | c. Register the app constant and create the directory (Phase 1) |
|   | d. Run Phase 1 gate check → verify constant and directory exist |
|   | e. Launch a sub-agent to build `event_tracker.py` (Phase 2, parallel) |
|   | f. Build `dog_monitor.py` in the main agent (Phase 2, sequential) |
|   | g. Run Phase 2 gate check → verify both modules import correctly |
|   | h. Run 3 validation checks: CLI, conventions, lint (Phase 3) |
|   | i. Run Phase 3 gate check → all must pass |
|   | j. Launch a sub-agent to write README.md (Phase 4) |
|   | k. Run final gate check → all imports, CLI, and README validated |
| 7 | Review the todo list panel — all items should show ✓ |
| 8 | Test: `python -m hailo_apps.python.gen_ai_apps.dog_monitor.dog_monitor --help` |

### How to Build ANY New App (Not Just Dog Monitor)

1. Open `.github/prompts/orchestrated-build.prompt.md`
2. Follow the placeholder table for your app type (VLM / pipeline / standalone / agent)
3. Replace all `<PLACEHOLDERS>` with your specific values
4. Use any of the three execution modes described above (Copilot Chat, Copilot Coding Agent, or Claude Code)

---

## Architecture Diagram

```
                    ┌────────────────────────────────────┐
                    │          AI Coding Agent            │
                    │  (Copilot / Claude / Any LLM)       │
                    └─────────────────┬──────────────────┘
                                      │ reads
                    ┌─────────────────▼──────────────────┐
                    │     copilot-instructions.md         │
                    │          or CLAUDE.md               │
                    │       (auto-loaded entry point)     │
                    └─────────────────┬──────────────────┘
                                      │ references
              ┌───────────────────────┼───────────────────────┐
              │                       │                       │
   ┌──────────▼──────────┐ ┌─────────▼─────────┐ ┌──────────▼──────────┐
   │   instructions/     │ │    memory/         │ │    toolsets/         │
   │                     │ │                    │ │                     │
   │ • architecture.md   │ │ • MEMORY.md        │ │ • hailo-sdk.md      │
   │ • coding-standards  │ │ • gen_ai_patterns  │ │ • gstreamer-elems   │
   │ • gen-ai-dev.md     │ │ • common_pitfalls  │ │ • vlm-backend-api   │
   │ • gstreamer.md      │ │ • camera_display   │ │ • core-framework    │
   │ • orchestration.md  │ │ • hailo_platform   │ │ • gen-ai-utilities  │
   │ • agent-protocols   │ │ • pipeline_optim   │ │                     │
   │ • skills/ (11)      │ │                    │ │                     │
   └──────────┬──────────┘ └────────────────────┘ └─────────────────────┘
              │ selects skill
   ┌──────────▼──────────┐
   │     prompts/        │
   │                     │      ┌─────────────────────┐
   │ • dog-monitor.md    │──────▶  Generated App Code  │
   │ • orchestrated.md   │      │  (production-ready)  │
   │ • new-vlm.md        │      └─────────────────────┘
   │ • new-pipeline.md   │
   │ • new-agent-tool.md │
   └─────────────────────┘
```

---

## Summary Statistics

| Category | Files | Lines |
|---|---|---|
| Agent entry points | 2 | 310 |
| Architecture & standards | 5 | 794 |
| Orchestration framework | 2 | 674 |
| Skills | 11 | 1,678 |
| API toolset references | 5 | 816 |
| Prompt templates | 6 | 790 |
| Persistent memory | 6 | 524 |
| Knowledge base | 1 | 103 |
| Community contributions | 6 | 63 |
| **Total** | **44** | **~5,752** |

---

## What This Enables

1. **Zero-code application development**: A structured prompt template produces a complete, runnable Hailo AI app
2. **Consistent quality**: Conventions, validation gates, and memory ensure every generated app follows the same patterns
3. **Knowledge accumulation**: The memory system captures pitfalls and patterns so future agent runs benefit from past experience. Community contributions feed real-world insights back into the system — anyone can add a recipe, bottleneck fix, or hardware tip that future builds automatically benefit from.
4. **Multiple agent support**: Works with GitHub Copilot (Chat + Coding Agent), Claude Code, and any LLM-based agent
5. **Scalable to any app type**: Skills and templates cover VLM, pipeline, standalone, agent, and voice applications
6. **Self-improving**: Every build updates the memory files and can contribute a community recipe. The next build reads those updates — so the system gets smarter with each use, across all developers and agents.
