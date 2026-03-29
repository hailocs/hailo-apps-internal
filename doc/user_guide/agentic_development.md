# AI-Powered Development (Beta)

> **Status:** Beta — Available for early adopters. Feedback welcome on the [Hailo Community Forum](https://community.hailo.ai/).

Build complete Hailo AI applications using natural language and AI coding agents. The agents understand the Hailo SDK, GStreamer pipelines, model architectures, and code conventions — so you describe **what** you want and they build **how**.

## Prerequisites

- **Hailo development environment** set up ([Installation Guide](./installation.md))
- **One of these IDEs** with AI agent support:
  - [GitHub Copilot](https://github.com/features/copilot) in VS Code (agents via `@agent-name`)
  - [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (agents via `CLAUDE.md` + `.claude/`)
  - [Cursor](https://cursor.sh/) (rules via `.cursor/rules/`)

## Quick Start

### Example 1: Build a Detection Pipeline (via App Builder)

The **app builder** is the master router — describe any app and it picks the right specialist.

```
@hl-app-builder "person detection with tracking on USB camera"
```

The agent will:
1. Ask clarifying questions (model type, features, input source)
2. Present a build plan for your approval
3. Route to the **pipeline builder**
4. Generate all code in `community/apps/<app_name>/`
5. Validate and report

### Example 2: Build a VLM Monitor (directly)

If you know you want a VLM app, go straight to the specialist:

```
@hl-vlm-builder "dog monitoring camera that alerts when the dog is eating shoes"
```

The agent will:
1. Ask key decisions (continuous monitor vs interactive, camera type)
2. Load VLM patterns and reference implementations
3. Scan official and community apps for similar patterns
4. Build the complete app with backend reuse, event tracking, graceful shutdown
5. Validate conventions and deliver with run instructions

## Available Agents

| Agent | Use Case | Hardware |
|-------|----------|----------|
| **hl-app-builder** | Master router — describe any app, get routed to the right specialist | All |
| **hl-vlm-builder** | Vision-Language Model apps (monitoring, scene analysis, visual Q&A) | Hailo-10H |
| **hl-pipeline-builder** | GStreamer video pipelines (detection, pose, segmentation, tracking) | Hailo-8, 8L, 10H |
| **hl-standalone-builder** | OpenCV + HailoInfer apps (batch processing, custom inference) | Hailo-8, 8L, 10H |
| **hl-llm-builder** | LLM chat and text generation apps | Hailo-10H |
| **hl-agent-builder** | Agents with LLM tool calling (smart assistants, API integrators) | Hailo-10H |
| **hl-voice-builder** | Voice assistants with Whisper STT + Piper TTS | Hailo-10H |

### When to Use the App Builder vs. a Specialist

- **Use `hl-app-builder`** when you're not sure which architecture fits, or when describing a complex app that might span categories.
- **Use a specialist directly** when you know exactly what type of app you want — it saves one routing step.

## How Agents Work

Each agent follows a structured workflow:

1. **Phase 1: Understand** — The agent responds immediately, asks key questions, presents a plan
2. **Phase 2: Load Context** — After you approve, it reads relevant skill files, patterns, and conventions
3. **Phase 3: Scan Code** — Scans official and community apps for similar implementations
4. **Phase 4: Build** — Creates all files in `community/apps/<app_name>/`
5. **Phase 5: Validate** — Checks conventions, imports, CLI, runs automated validation
6. **Phase 6: Report** — Presents what was built, how to run it, what it does

### What Gets Created

```
community/apps/<your_app>/
├── app.yaml          # App manifest (name, type, model, tags)
├── run.sh            # Launch wrapper with PYTHONPATH setup
├── <app_name>.py     # Main application code
├── README.md         # Usage and architecture docs
└── ...               # Additional modules as needed
```

Plus a contribution recipe in `community/contributions/` documenting patterns and lessons learned.

### Running Your App

```bash
# Via run.sh wrapper (recommended)
./community/apps/<your_app>/run.sh --input usb

# Or directly with PYTHONPATH
PYTHONPATH=. python3 community/apps/<your_app>/<your_app>.py --input usb
```

## Community Pipeline

Apps built by agents live in `community/apps/` and can be:
- **Pushed** to [hailo-rpi5-examples](https://github.com/hailo-ai/hailo-rpi5-examples) community projects via `push_community_apps.py`
- **Promoted** to official apps via `curate_contributions.py --promote <app_name>`

## Knowledge Base

The agentic knowledge lives in `.hailo/` and is automatically adapted for each IDE:

| Directory | Content |
|-----------|---------|
| `.hailo/agents/` | Agent definitions (7 agents) |
| `.hailo/skills/` | Detailed build skills per app type |
| `.hailo/instructions/` | Coding standards, architecture, testing |
| `.hailo/toolsets/` | SDK and API references |
| `.hailo/memory/` | Persistent patterns and pitfall avoidance |

Platform-specific files are generated from `.hailo/` by running:

```bash
python .hailo/scripts/generate_platforms.py --generate
```

This produces `.github/` (Copilot), `.claude/` + `CLAUDE.md` (Claude Code), and `.cursor/` (Cursor).

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Agent doesn't know Hailo APIs | Check that `.hailo/` directory exists and is populated |
| Agent writes relative imports | Convention bug — agent should always use absolute imports |
| App fails `--help` | Check `run.sh` sets PYTHONPATH correctly |
| Agent builds in wrong directory | Should always be `community/apps/<name>/`, not in `hailo_apps/` |
| Platform configs are stale | Run `python .hailo/scripts/generate_platforms.py --generate` |
