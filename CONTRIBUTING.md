# Contributing to Hailo Apps

Thank you for your interest in contributing to the Hailo AI community! This guide explains how to contribute apps and knowledge findings.

> **Where do PRs go?** All community contributions are submitted as pull requests to the public **[hailo-rpi5-examples](https://github.com/hailo-ai/hailo-rpi5-examples)** repository. Since app code uses `hailo_apps.*` imports, you'll need a local [hailo-apps](https://github.com/hailo-ai/hailo-apps) clone for development and testing.

## What You Can Contribute

### 1. Apps

Complete applications that run on Hailo accelerators (Hailo-8, Hailo-8L, Hailo-10H).

**Types:**
- **Pipeline apps** — GStreamer-based real-time video processing
- **Standalone apps** — Direct HailoRT inference
- **Gen AI apps** — LLM, VLM, voice, or agent apps on Hailo-10H

### 2. Knowledge Findings

Insights from real-world Hailo deployments: optimization tricks, debugging findings, hardware-specific tips. Knowledge findings are submitted alongside an app — place them in your app's `contributions/` subfolder.

**Categories:** `pipeline-optimization`, `bottleneck-patterns`, `gen-ai-recipes`, `hardware-config`, `model-tuning`, `camera-display`, `voice-audio`, `general`

---

## Contributing an App

### Directory Structure (in hailo-rpi5-examples)

Place your app in `community_projects/<app_name>/` (flat layout — no type subdirectories):

```
community_projects/my_app/
├── app.yaml              # Required: manifest
├── my_app.py             # Required: main entry point (must match directory name)
├── __init__.py            # Required: empty or with imports
├── run.sh                 # Required: convenience wrapper
├── README.md              # Required: documentation
├── requirements.txt       # Required: dependencies (or note that hailo-apps manages them)
├── <other_modules>.py     # Optional: additional modules
└── contributions/         # Optional: knowledge findings related to this app
    └── YYYY-MM-DD_my_app_<slug>.md
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

The `type` field determines where the app lives when copied into hailo-apps for running:

| `type` value | hailo-apps target directory |
|---|---|
| `pipeline` | `community/apps/pipeline_apps/<app_name>/` |
| `standalone` | `community/apps/standalone_apps/<app_name>/` |
| `gen_ai` | `community/apps/gen_ai_apps/<app_name>/` |

### Coding Conventions

Your app **must** follow these conventions to pass validation:

1. **Absolute imports only**: `from hailo_apps.python.core.common.xyz import ...` (no relative imports)
2. **Use `get_logger(__name__)`** from `hailo_apps.python.core.common.hailo_logger` (not bare `print`)
3. **Use a CLI parser**: `get_pipeline_parser()`, `get_standalone_parser()`, or `argparse`
4. **Entry point**: Include `if __name__ == "__main__"` block or `def main()`
5. **Signal handler**: Register `signal.SIGINT` for graceful shutdown
6. **HEF resolution**: Use `resolve_hef_path()` — never hardcode `.hef` paths
7. **No hardcoded paths**: No `/home/...`, `/tmp/...`, or `/dev/videoN` — use `--input usb`

### Knowledge Findings (Optional)

If you discovered useful patterns, optimizations, or debugging tips while building your app, include them as knowledge findings in your app's `contributions/` subfolder:

```
community_projects/my_app/contributions/2026-03-29_my_app_queue-tuning.md
```

Use the [Knowledge Finding Format](#knowledge-finding-format) described below.

---

## Submitting Your Contribution

### Step 1: Fork hailo-rpi5-examples

```bash
# Fork https://github.com/hailo-ai/hailo-rpi5-examples on GitHub, then:
git clone https://github.com/<your-username>/hailo-rpi5-examples.git
cd hailo-rpi5-examples
git checkout -b my-contribution
```

### Step 2: Create Your App

Create your app directory in `community_projects/<app_name>/` following the [directory structure](#directory-structure-in-hailo-rpi5-examples) above.

### Step 3: Develop and Test

Since app code uses `from hailo_apps.python.core...` imports, you need a hailo-apps clone to develop and run:

```bash
# 1. Clone and set up hailo-apps (one-time)
git clone https://github.com/hailo-ai/hailo-apps.git
cd hailo-apps
source setup_env.sh
pip install -e .

# 2. Copy your app into the hailo-apps tree for development
#    Use the type mapping: pipeline → pipeline_apps/, standalone → standalone_apps/, gen_ai → gen_ai_apps/
cp -r /path/to/hailo-rpi5-examples/community_projects/my_app \
      community/apps/pipeline_apps/my_app

# 3. Run your app from within hailo-apps
./community/apps/pipeline_apps/my_app/run.sh --input usb
# or: PYTHONPATH=. python3 community/apps/pipeline_apps/my_app/my_app.py --input usb

# 4. When done developing, copy changes back to your hailo-rpi5-examples fork
cp -r community/apps/pipeline_apps/my_app/* \
      /path/to/hailo-rpi5-examples/community_projects/my_app/
```

**Optional validation** (requires the hailo-apps clone):

```bash
cd hailo-apps
python .hailo/scripts/validate_app.py community/apps/pipeline_apps/my_app --smoke-test
```

This runs ~15 static checks + runtime smoke tests. Smoke tests gracefully skip if Hailo hardware isn't available.

### Step 4: Open a Pull Request

```bash
# From your hailo-rpi5-examples fork
cd /path/to/hailo-rpi5-examples
git add community_projects/my_app/
git commit -m "community: add my_app"
git push origin my-contribution
# Open a PR to https://github.com/hailo-ai/hailo-rpi5-examples
```

Fill in the PR template with the app checklist.

---

## How to Use a Community App

To run a community app from [hailo-rpi5-examples](https://github.com/hailo-ai/hailo-rpi5-examples), copy it into your local hailo-apps clone:

```bash
# 1. Set up hailo-apps (if not already done)
git clone https://github.com/hailo-ai/hailo-apps.git
cd hailo-apps
source setup_env.sh
pip install -e .

# 2. Get the community app from hailo-rpi5-examples
#    Check the app's app.yaml "type" field for the correct target directory
git clone https://github.com/hailo-ai/hailo-rpi5-examples.git /tmp/rpi5-examples
cp -r /tmp/rpi5-examples/community_projects/<app_name> \
      community/apps/<type>_apps/<app_name>

# 3. Run it
./community/apps/<type>_apps/<app_name>/run.sh --input usb
```

> **Why copy?** Community apps use `from hailo_apps.python.core...` imports which only resolve when the app is inside the hailo-apps directory tree with the package installed.

---

## What Happens After You Submit

1. **Maintainer reviews** your PR in hailo-rpi5-examples and runs validation
2. **PR is merged** into hailo-rpi5-examples — the app is now publicly available
3. For knowledge findings: **Maintainer pulls** findings back into the internal knowledge base (tiered system — full content to memory files, summaries to skill/toolset docs)
4. For apps: **Promotion** may move your app to the official `hailo_apps/` package

---

## Knowledge Finding Format

Knowledge findings are submitted as markdown files with YAML frontmatter:

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

## Questions?

Open an issue or check the [community apps README](community/apps/README.md) and [contributions README](community/contributions/README.md) for more details.
