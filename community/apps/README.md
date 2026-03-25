# Community Apps

Staging area for AI-agent-built applications before official review and promotion.

## Purpose

When AI agents build new Hailo applications, the code is placed here — **not** in `hailo_apps/python/`. This keeps the official package clean while allowing experimentation and review.

Apps here are functional but haven't been officially reviewed, tested across hardware variants, or promoted to the core package.

## App Structure

Each community app is a self-contained directory:

```
community/apps/<app_name>/
├── app.yaml              ← App manifest (required)
├── __init__.py
├── <app_name>.py         ← Main entry point
├── README.md
└── run.sh                ← Launch wrapper (sets PYTHONPATH)
```

### app.yaml Format

```yaml
name: my_app
title: My App Title
description: One-line description of what the app does
author: AI Agent (auto-generated)
date: "2026-03-25"
type: gen_ai              # gen_ai | pipeline | standalone
hailo_arch: hailo10h      # hailo8 | hailo8l | hailo10h
model: Qwen2-VL-2B-Instruct
tags: [vlm, monitoring, camera]
status: draft             # draft | reviewed | promoted
```

### Status Lifecycle

| Status | Meaning |
|---|---|
| `draft` | Just created by an agent, not yet reviewed |
| `reviewed` | Human reviewed, confirmed working |
| `promoted` | Moved to `hailo_apps/python/` — this directory is deleted |

## How to Run a Community App

Community apps are **not** part of the `hailo_apps` Python package. Use the included `run.sh` wrapper which sets `PYTHONPATH` correctly:

```bash
# Via run.sh (recommended)
./community/apps/my_app/run.sh --input usb

# Or manually
PYTHONPATH=/path/to/repo python3 community/apps/my_app/my_app.py --input usb
```

## How Apps Get Here

AI agents are instructed to place new apps in this directory. The agent:
1. Creates the app code + `app.yaml` manifest
2. Creates a matching contribution recipe in `community/contributions/<category>/`
3. The app uses absolute imports from `hailo_apps.python.core.*` (core utilities)
4. The app does NOT register in `defines.py` or `resources_config.yaml` (that happens during promotion)

## Promotion to Official

When an app is ready for official inclusion:

```bash
python .hailo/scripts/curate_contributions.py --promote <app_name>
```

This:
1. Validates app structure and conventions
2. Moves directory to `hailo_apps/python/<category>/<app_name>/`
3. Registers constants in `defines.py`
4. Adds YAML entry in `resources_config.yaml`
5. Removes `app.yaml` and `run.sh` (no longer needed)
6. Deletes the community/apps entry

## Important Notes

- Community apps **can** import from `hailo_apps.python.core.*` and `hailo_apps.python.gen_ai_apps.vlm_chat.backend` (reusing the official Backend)
- Community apps **cannot** be imported by official code (no reverse dependency)
- Community apps are excluded from `pip install -e .` — they are not part of the package
- Each app MUST have an `app.yaml` manifest and a `README.md`
