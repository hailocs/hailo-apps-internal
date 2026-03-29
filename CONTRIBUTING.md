# Contributing to Hailo Apps

Thank you for your interest in contributing to the Hailo AI community! This guide explains how to contribute apps and knowledge findings.

## What You Can Contribute

### 1. Apps

Complete applications that run on Hailo accelerators (Hailo-8, Hailo-8L, Hailo-10H).

**Types:**
- **Pipeline apps** — GStreamer-based real-time video processing
- **Standalone apps** — Direct HailoRT inference with OpenCV
- **Gen AI apps** — LLM, VLM, voice, or agent apps on Hailo-10H

### 2. Knowledge Findings

Insights from real-world Hailo deployments: optimization tricks, debugging findings, hardware-specific tips.

**Categories:** `pipeline-optimization`, `bottleneck-patterns`, `gen-ai-recipes`, `hardware-config`, `model-tuning`, `camera-display`, `voice-audio`, `general`

---

## Contributing an App

### Directory Structure

Place your app in `community/apps/<type>/<app_name>/`:

```
community/apps/pipeline_apps/my_app/
├── app.yaml              # Required: manifest
├── my_app.py             # Required: main entry point (must match directory name)
├── __init__.py            # Required: empty or with imports
├── run.sh                 # Required: convenience wrapper
├── README.md              # Required: documentation
└── <other_modules>.py     # Optional: additional modules
```

### app.yaml Manifest

```yaml
name: my_app
title: "My App Title"
description: "One-line description of what this app does"
author: "Your Name"
date: "2026-03-29"
type: pipeline              # pipeline | standalone | gen_ai
hailo_arch: hailo8l         # hailo8 | hailo8l | hailo10h
model: yolov8n              # primary model used
tags: [detection, tracking]
status: draft               # always submit as draft
```

### Coding Conventions

Your app **must** follow these conventions to pass validation:

1. **Absolute imports only**: `from hailo_apps.python.core.common.xyz import ...` (no relative imports)
2. **Use `get_logger(__name__)`** from `hailo_apps.python.core.common.hailo_logger` (not bare `print`)
3. **Use a CLI parser**: `get_pipeline_parser()`, `get_standalone_parser()`, or `argparse`
4. **Entry point**: Include `if __name__ == "__main__"` block or `def main()`
5. **Signal handler**: Register `signal.SIGINT` for graceful shutdown
6. **HEF resolution**: Use `resolve_hef_path()` — never hardcode `.hef` paths
7. **No hardcoded paths**: No `/home/...`, `/tmp/...`, or `/dev/videoN` — use `--input usb`

### Validate Before Submitting

Run the validation script locally if you have the repo cloned:

```bash
python .hailo/scripts/validate_app.py community/apps/<type>/<app_name> --smoke-test
```

This runs ~15 static checks + runtime smoke tests. The smoke tests gracefully skip if Hailo hardware isn't available.

---

## Contributing a Knowledge Finding

### File Format

Place your finding in the appropriate category subdirectory:

```
community/contributions/<category>/YYYY-MM-DD_<app>_<slug>.md
```

Example: `community/contributions/pipeline-optimization/2026-03-29_my_app_queue-tuning.md`

### Required Format

```markdown
---
title: "Short descriptive title"
category: pipeline-optimization
contributor: "Your Name"
date: "2026-03-29"
tags: [queue-size, hailonet, latency]
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

## Applicability
When does this pattern apply? What to look for.
```

**Required frontmatter:** `title`, `category`, `contributor`, `date`, `tags`

**Optional frontmatter:** `hailo_arch`, `app`, `reproducibility`, `source_agent`

---

## Submitting Your Contribution

### Step 1: Fork and Branch

```bash
git clone https://github.com/<your-username>/hailo-apps.git
cd hailo-apps
git checkout -b my-contribution
```

### Step 2: Create Your Files

Add your app or contribution following the structure above.

### Step 3: Test (for apps)

```bash
source setup_env.sh
pip install -e .
python .hailo/scripts/validate_app.py community/apps/<type>/<app_name> --smoke-test
```

### Step 4: Open a Pull Request

Push your branch and open a PR targeting this repository. Fill in the PR template.

---

## What Happens After You Submit

1. **Maintainer reviews** your PR and runs validation
2. **PR is merged** into the repo
3. For contributions: **Curation** processes your finding into the knowledge base (tiered system — full content to memory files, summaries to skill/toolset docs)
4. For apps: **Promotion** may move your app to the official `hailo_apps/` package
5. For apps: **Publishing** may push your app to the public [hailo-rpi5-examples](https://github.com/hailo-ai/hailo-rpi5-examples) repo

## Questions?

Open an issue or check the [community apps README](community/apps/README.md) and [contributions README](community/contributions/README.md) for more details.
