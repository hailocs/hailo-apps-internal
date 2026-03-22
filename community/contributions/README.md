# Community Contributions

Community-contributed optimization insights from real-world Hailo deployments.

## Why Contribute?

- **Help other developers** — your finding saves someone else hours of debugging
- **Get credited** — your name appears in the git commit and PR
- **Improve AI agents** — future agent sessions will suggest your recipe automatically
- **Grow the knowledge base** — real-world insights are more valuable than any docs

## Categories

| Directory | Description |
|---|---|
| `pipeline-optimization/` | GStreamer pipeline tuning (queue sizes, thread counts) |
| `bottleneck-patterns/` | Recurring performance patterns and root causes |
| `model-tuning/` | Model-specific optimizations (batch sizes, scheduling) |
| `gen-ai-recipes/` | Gen AI app patterns, VLM prompt engineering, event detection |
| `hardware-config/` | Hardware-specific settings, architecture differences |
| `general/` | Other insights (debugging techniques, tooling, workflows) |

## Contribution File Format

File naming: `YYYY-MM-DD_<app>_<slug>.md`

```markdown
---
title: "Short descriptive title"
category: gen-ai-recipes
contributor: "Your Name"
date: "2026-03-18"
hailo_arch: hailo10h
app: dog_monitor
tags: [vlm, continuous-monitoring, event-detection]
reproducibility: verified
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

## Applicability
When does this pattern apply? What to look for.
```

## How Agents Use Contributions

AI agents query this directory for relevant prior art before suggesting approaches:
- Search by `tags`, `app`, `category`, and `hailo_arch` in the YAML frontmatter
- Matching contributions are referenced as recommendations
- The contributor's name is cited when their finding is used
