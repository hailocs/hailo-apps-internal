# Community Contributions

Community-contributed optimization insights from real-world Hailo deployments.

## Why Contribute?

- **Help other developers** — your finding saves someone else hours of debugging
- **Get credited** — your name appears in the git commit, PR, and contribution file
- **Improve AI agents** — future `/hl-profile` sessions will suggest your recipe automatically
- **Grow the knowledge base** — real-world insights are more valuable than any docs

## How Contributions Are Generated

Contributions are created via the Claude Code `/hl-contribute` skill, typically at the end of an optimization session (e.g., after `/hl-profile`). The process:

1. The agent formats the finding as a structured `.md` file
2. Sensitive data (paths, IPs, credentials) is automatically scrubbed
3. **You review and approve everything** before submission
4. A PR is created targeting the `dev` branch with your name as contributor

## Contributing Manually

If you're not using Claude Code, you can contribute directly:

1. Create a `.md` file following the format below
2. Place it in the appropriate category subdirectory
3. Submit a PR targeting `dev`

## Categories

| Directory | Description | Tier 1 target | Tier 2 targets |
|-----------|-------------|---------------|----------------|
| `pipeline-optimization/` | GStreamer pipeline tuning (queue sizes, thread counts, leaky queues) | `memory/pipeline_optimization.md` | `hl-build-pipeline-app.md`, `gstreamer-pipelines.md`, `gstreamer-elements.md` |
| `bottleneck-patterns/` | Recurring performance patterns and root causes | `memory/pipeline_optimization.md` | `hl-build-pipeline-app.md` |
| `gen-ai-recipes/` | VLM/LLM patterns, multiprocessing, architecture tips | `memory/gen_ai_patterns.md` | `hl-build-vlm-app.md`, `hl-build-llm-app.md`, `gen-ai-utilities.md` |
| `model-tuning/` | Model-specific optimizations (batch sizes, scheduling) | `knowledge/best_practices.yaml` | `hl-model-management.md` |
| `hardware-config/` | Hardware-specific settings, architecture differences | `memory/hailo_platform_api.md` | `hailo-sdk.md` |
| `camera-display/` | Camera init, BGR/RGB, OpenCV patterns, display setup | `memory/camera_and_display.md` | `hl-camera.md` |
| `voice-audio/` | Whisper STT, Piper TTS, VAD, audio pipeline patterns | `memory/gen_ai_patterns.md` | `hl-build-voice-app.md`, `gen-ai-utilities.md` |
| `general/` | Other insights (debugging techniques, tooling, workflows) | `memory/common_pitfalls.md` | *(none)* |

### Tiered Curation System

When `curate_contributions.py --curate` processes a contribution, it writes to two tiers:

- **Tier 1 (full append):** The complete contribution is appended to the memory or knowledge file. This is the permanent record.
- **Tier 2 (summary append):** A short 3-line summary is appended to the `## Community Findings` section in relevant skill, toolset, and instruction files, with a cross-reference to the full entry in the Tier 1 file.
- **Tier 3 (never auto-modified):** Core structural files like `coding-standards.md`, `agent-protocols.md`, `orchestration.md` are never touched by curation.

## Contribution File Format

File naming: `YYYY-MM-DD_<app>_<slug>.md`

Example: `2026-03-16_gesture-detection_scheduler-timeout-batch-stall.md`

```markdown
---
title: "Short descriptive title"
category: pipeline-optimization
source_agent: profile-pipeline
contributor: "Jane Doe"
github_user: "janedoe"          # optional
date: "2026-03-16"
hailo_arch: hailo8
app: gesture_detection
tags: [scheduler-timeout, hailonet, latency]
reproducibility: verified       # verified | observed | theoretical
---

## Summary
One-paragraph description of the finding.

## Context
Hardware, app, pipeline element, problem description.

## Finding
Root cause explanation.

## Solution
Exact change (code diff or description).

## Results
Before/after metrics table.

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| Latency | 257ms  | 93ms  | -64%   |

## Applicability
When does this pattern apply? What to look for.
```

### Required Fields

**Frontmatter:** `title`, `category`, `date`, `contributor`, `tags`

**Optional:** `hailo_arch`, `app`, `reproducibility`, `source_agent`

**Body sections:** Summary, Context, Finding, Solution, Results, Applicability

### Reproducibility Levels

| Level | Meaning |
|-------|---------|
| `verified` | Tested with before/after measurements |
| `observed` | Seen in practice but not formally benchmarked |
| `theoretical` | Reasoning-based, not yet tested |

## How Agents Use Contributions

Claude Code agents query this directory for relevant prior art before suggesting optimizations:

- Agents search by `tags`, `app`, `category`, and `hailo_arch` in the YAML frontmatter
- Matching contributions are referenced as: "A community contributor found that..."
- The contributor's name is cited when their finding is used

This creates a feedback loop: your contribution helps the next developer, whose session may produce another contribution, and so on.
