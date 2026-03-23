# Hailo Apps — Persistent Memory Index

> Cross-session knowledge base. AI agents should read relevant files before starting tasks and update them when discovering new patterns.

## Memory Files

| File | Topic | When to Read |
|---|---|---|
| [gen_ai_patterns.md](gen_ai_patterns.md) | VLM/LLM app architecture, multiprocessing, token streaming | Building any Gen AI app |
| [pipeline_optimization.md](pipeline_optimization.md) | GStreamer bottlenecks, queue tuning, scheduler-timeout | Profiling or optimizing pipelines |
| [camera_and_display.md](camera_and_display.md) | Camera init, BGR/RGB conversion, OpenCV display patterns | Camera-related work |
| [hailo_platform_api.md](hailo_platform_api.md) | VDevice, VLM.generate(), HEF resolution, device sharing | Any Hailo SDK interaction |
| [common_pitfalls.md](common_pitfalls.md) | Bugs found and fixed, anti-patterns to avoid | Any development task |

## Key Project Patterns

- **Pipeline apps**: `app.py` (callback + main) + `app_pipeline.py` (GStreamerApp subclass)
- **Gen AI apps**: Main class + Backend (multiprocessing) + optional event tracking
- **All apps**: Signal handling (SIGINT), graceful shutdown, resource cleanup
- `hailocropper` sends **parent detection** as ROI to inner pipeline, not the crop sub-detection
- `INFERENCE_PIPELINE_WRAPPER` sets a non-identity `scaling_bbox` on the ROI (letterbox transform)
- **New VLM apps need TWO registrations**: `defines.py` AND `resources_config.yaml`
- **Display**: Always resize VLM frames to 640×640+, wrap overlay text, print events to terminal
- **Driver check**: Use `hailortcli fw-control identify`, NOT `lsmod | grep hailo_pci`

## Build Commands

```bash
source setup_env.sh                      # Always first
hailo-compile-postprocess                # Compile C++ postprocess
hailo-post-install                       # Full post-install
hailortcli parse-hef <path.hef>          # Inspect HEF model metadata
```

## Rules for Updating Memory

1. **Do update** when you discover a stable pattern, fix a non-obvious bug, or learn a new convention
2. **Don't update** with session-specific information, speculation, or unverified guesses
3. **Keep entries concise** — a memory file should be scannable in 30 seconds
4. **Link from this index** when creating new memory files
