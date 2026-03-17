# Hailo Apps Infrastructure

AI applications for Hailo-8, Hailo-8L, and Hailo-10H edge accelerators.
20+ ready-to-run apps: real-time computer vision pipelines, standalone inference, and GenAI voice/vision agents.

## Claude Code Memory (persistent knowledge base)

Knowledge base lives in `.claude/memory/` (checked into the repo). Always consult and update these files:

- `.claude/memory/MEMORY.md` — Top-level index, key patterns, quick reference
- `.claude/memory/gesture_detection.md` — Gesture detection app notes, bugs found & fixed
- `.claude/memory/tappas_coordinate_spaces.md` — TAPPAS scaling_bbox, coordinate spaces, overlay rendering
- `.claude/memory/pipeline_profiling.md` — Pipeline profiler notes, bottleneck patterns

**Rules:**
- Read relevant memory files at the start of a task to build on previous work
- Update memory files when discovering stable patterns, fixing bugs, or learning new project conventions
- Organize by topic (create new files for new topics, link from MEMORY.md)
- Keep entries concise and factual — no session-specific or speculative content
- When corrected on something from memory, fix the source file immediately

## Quick Reference

```bash
source setup_env.sh                # Activate environment (always do this first)
hailo-compile-postprocess          # Compile C++ postprocess plugins
hailo-post-install                 # Full post-install (downloads resources + compiles)
hailo-download-resources           # Download model HEFs and media
```

## Repository Layout

```
hailo_apps/
├── python/
│   ├── pipeline_apps/         # GStreamer real-time video apps (12 apps)
│   ├── standalone_apps/       # Lightweight HailoRT-only apps (7 apps)
│   ├── gen_ai_apps/           # Hailo-10H GenAI apps (7 apps)
│   └── core/                  # Shared framework
│       ├── common/            # Utilities, defines, buffer_utils, logger
│       └── gstreamer/         # GStreamerApp base class, helper pipelines
├── postprocess/cpp/           # C++ GStreamer elements (meson build)
│   └── overlay_community/     # Custom overlay element (see its README.md)
├── config/                    # YAML configs (resources, tests, app definitions)
└── installation/              # Install scripts
doc/                           # User guide + developer guide
tests/                         # Pytest suite
community/
└── contributions/             # Community-contributed insights (PRs to dev)
    ├── README.md
    ├── pipeline-optimization/
    ├── bottleneck-patterns/
    ├── model-tuning/
    ├── hardware-config/
    └── general/
```

## Three App Types

### Pipeline Apps (`hailo_apps/python/pipeline_apps/`)
Real-time GStreamer video pipelines for cameras, RTSP, and video files.

- **Pattern:** `app.py` (callback + main) + `app_pipeline.py` (GStreamerApp subclass)
- Subclass `GStreamerApp`, override `get_pipeline_string()`
- Build pipelines with helpers: `SOURCE_PIPELINE()`, `INFERENCE_PIPELINE()`, `DISPLAY_PIPELINE()`
- Callbacks must be non-blocking — receive buffer with full metadata (detections, landmarks, etc.)
- Run via CLI (`hailo-detect`, `hailo-pose`, `hailo-seg`, ...) or `python -m`
- Apps: detection, pose_estimation, instance_segmentation, face_recognition, depth, clip, tiling, multisource, reid_multisource, paddle_ocr, gesture_detection
- Details: `doc/developer_guide/app_development.md`

### Standalone Apps (`hailo_apps/python/standalone_apps/`)
Lightweight single-script apps using direct HailoRT API — no GStreamer or TAPPAS needed.

- **Pattern:** Single Python script using `HailoAsyncInference` for async inference queues
- CPU-side post-processing with built-in tracking (BYTETracker), visualization, FPS monitoring
- Work with images, video files, and camera streams
- Good for learning HailoRT, batch processing, and quick prototyping
- Apps: object_detection, instance_segmentation, lane_detection, pose_estimation, super_resolution, oriented_object_detection, paddle_ocr
- Model/input resolution configured dynamically from `resources_config.yaml`
- Details: `hailo_apps/python/standalone_apps/README.md`

### GenAI Apps (`hailo_apps/python/gen_ai_apps/`) — Hailo-10H only
Generative AI applications using `hailo_platform.genai` SDK for LLM/VLM/Speech2Text.

- **Full apps:** voice_assistant (speech-to-text + LLM + TTS), vlm_chat (vision + language), agent_tools_example (voice-to-action with function calling)
- **Simple examples:** simple_llm_chat, simple_vlm_chat, simple_whisper_chat, hailo_ollama
- Shared utilities in `gen_ai_utils/`: LLM context management, voice processing (VAD, audio recording, TTS via Piper)
- Install extra deps: `pip install -e ".[gen-ai]"`
- Details: `hailo_apps/python/gen_ai_apps/README.md`

## Config System

YAML-driven configuration in `hailo_apps/config/`:

| File | Purpose |
|---|---|
| `config.yaml` | Installation settings, HailoRT/TAPPAS version validation, venv config |
| `resources_config.yaml` | Models per app per architecture, shared videos/images/JSON resources |
| `test_definition_config.yaml` | Test app definitions, test suites, CLI entry points |

Unified API via `config_manager` module with caching. Details: `hailo_apps/config/README.md`

## Key Components

### C++ Postprocess Plugins
Built with meson under `hailo_apps/postprocess/cpp/`. Compiled to GStreamer `.so` plugins.
Build: `hailo-compile-postprocess`

### hailooverlay_community
Custom GStreamer overlay element — drop-in replacement for `hailooverlay` with: custom per-detection colors, YAML style config, sprite/stamp system, label filtering, stats overlay.
Full docs and Python examples: `hailo_apps/postprocess/cpp/overlay_community/README.md`

## Testing

```bash
cd tests/
pytest test_runner.py -v           # Pipeline app tests (parametrized by app/model/arch/method)
pytest test_standalone_runner.py   # Standalone app smoke tests
pytest test_gen_ai.py              # GenAI tests (skipped on non-Hailo-10H)
pytest test_face_recon.py          # Face recognition tests
```

Tests use `test_utils.py` helpers and are driven by YAML config. Run methods: `module`, `pythonpath`, `cli`.

## Hardware

| Architecture | Value | Use case |
|---|---|---|
| Hailo-8 | `hailo8` | Full performance, all pipeline + standalone apps |
| Hailo-8L | `hailo8l` | Lower power, compatible model subset |
| Hailo-10H | `hailo10h` | GenAI (LLM, VLM, Whisper) + vision pipelines |

Runtime detection: `from hailo_apps.python.core.common.installation_utils import detect_hailo_arch`

## Claude Code Tools

### Skill: `/profile-pipeline`
GStreamer pipeline performance profiler. Auto-sets up GST-Shark, captures traces, analyzes bottlenecks, suggests optimizations, runs A/B experiments, and learns from results.

- `/profile-pipeline` — Guided profiling flow
- `/profile-pipeline <app_path>` — Profile a specific app
- `/profile-pipeline <trace_dir>` — Analyze existing trace
- `/profile-pipeline compare <dir1> <dir2>` — A/B comparison
- `/profile-pipeline learn` — Save findings to knowledge base
- Scripts: `.claude/skills/profile-pipeline/scripts/`
- Knowledge base: `.claude/skills/profile-pipeline/knowledge/knowledge_base.yaml`

### Skill: `/contribute-insights`
Share optimization insights with the Hailo community. Formats findings, sanitizes sensitive data, reviews with the user (mandatory approval), and submits a PR to the dev branch. Contributors are credited by name.

- `/contribute-insights` — Interactive mode, asks what you learned
- `/contribute-insights '<json>'` — Accepts structured data from other agents
- Called automatically at end of `/profile-pipeline` sessions

### Skill: `/app-builder`
Interactive agent that helps create new Hailo AI applications. Discovers requirements, recommends the best starting template from 25+ existing apps, scaffolds the project, guides implementation, and integrates with `/profile-pipeline` and `/contribute-insights`.

- `/app-builder` — Start interactive discovery conversation
- `/app-builder <description>` — Parse intent, jump to recommendation (e.g., `/app-builder "count people entering a store"`)
- `/app-builder list` — Show catalog of all apps organized by category
- `/app-builder from <app-name>` — Start from a specific template app
- `/app-builder standalone` / `genai` / `pipeline` — Constrain to app type
- Knowledge base: `.claude/skills/app-builder/knowledge/` (app catalog, decision tree, pipeline patterns, templates)
- Per-app CLAUDE.md files: Each app directory contains a `CLAUDE.md` with architecture, pipeline structure, and extension guides

### Cross-Agent Knowledge

#### Community Contributions (for all agents)
Agents should query `community/contributions/` for relevant prior art before suggesting optimizations:
- Use `Grep` to search contribution files by tags, app name, or category
- Reference matching contributions when suggesting optimizations: "A community member found that..."
- After successful sessions, offer `/contribute-insights` to share findings back

## Documentation Index

| Resource | Path |
|---|---|
| User Guide | `doc/user_guide/README.md` |
| Developer Guide | `doc/developer_guide/README.md` |
| App Development Tutorial | `doc/developer_guide/app_development.md` |
| GStreamer Helpers Reference | `doc/developer_guide/gstreamer_helper_pipelines.md` |
| Writing C++ Postprocess | `doc/developer_guide/writing_postprocess.md` |
| Community Overlay Element | `hailo_apps/postprocess/cpp/overlay_community/README.md` |
| Config System | `hailo_apps/config/README.md` |
| Each app has its own README.md in its directory |  |
