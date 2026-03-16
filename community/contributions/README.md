# Community Contributions

Community-contributed optimization insights from real-world Hailo deployments.

## Why Contribute?

- **Help other developers** — your finding saves someone else hours of debugging
- **Get credited** — your name appears in the git commit, PR, and contribution file
- **Improve AI agents** — future `/profile-pipeline` sessions will suggest your recipe automatically
- **Grow the knowledge base** — real-world insights are more valuable than any docs

## How Contributions Are Generated

Contributions are created via the Claude Code `/contribute-insights` skill, typically at the end of an optimization session (e.g., after `/profile-pipeline`). The process:

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

| Directory | Description |
|-----------|-------------|
| `pipeline-optimization/` | GStreamer pipeline tuning (queue sizes, thread counts, leaky queues) |
| `bottleneck-patterns/` | Recurring performance patterns and root causes |
| `model-tuning/` | Model-specific optimizations (batch sizes, scheduling) |
| `hardware-config/` | Hardware-specific settings, architecture differences |
| `general/` | Other insights (debugging techniques, tooling, workflows) |

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

**Frontmatter:** `title`, `category`, `date`, `contributor`, `reproducibility`

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
