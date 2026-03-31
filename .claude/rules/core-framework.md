---
paths:
  - "**/core/**"
---

# Core Framework — Contextual Instructions

You are working on the **core framework** (shared utilities, GStreamerApp base class, parsers, logging, HEF utilities).

## Required Context Files

Read these files before making changes (paths relative to `.hailo/`):

- `instructions/architecture.md` — System architecture, module dependency graph
- `instructions/coding-standards.md` — Import rules, logging, conventions
- `toolsets/core-framework-api.md` — Full API reference for core modules
- `memory/hailo_platform_api.md` — VDevice, HEF resolution patterns
- `memory/common_pitfalls.md` — Known anti-patterns to avoid

## Additional Context (load if relevant)

- If GStreamer: `instructions/gstreamer-pipelines.md`, `toolsets/gstreamer-elements.md`
- If models/HEF: `skills/hl-model-management.md`, `toolsets/hailort-api.md`

## Critical Notes for Core Changes

- Core is imported by ALL app types — changes have wide impact
- `defines.py` is the app registry — used by every app for constants
- `resolve_hef_path()` in `core.py` is the single source of truth for model path resolution
- `get_logger(__name__)` is the only acceptable logging pattern
- Parser functions (`get_pipeline_parser`, `get_standalone_parser`) must stay backward-compatible
- Always run tests after core changes: `pytest tests/ -v`

## Key Modules

- `hailo_apps/python/core/common/defines.py` — App name constants, shared IDs
- `hailo_apps/python/core/common/core.py` — `resolve_hef_path()`, core utilities
- `hailo_apps/python/core/common/parser.py` — CLI argument parsers
- `hailo_apps/python/core/common/hailo_logger.py` — Logging setup
- `hailo_apps/python/core/gstreamer/gstreamer_app.py` — GStreamerApp base class
- `hailo_apps/python/core/gstreamer/gstreamer_helper_pipelines.py` — Pipeline string builders
