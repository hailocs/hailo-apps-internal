# Hailo Apps — Persistent Memory Index

> Cross-session knowledge base. AI agents should read relevant files before starting tasks and update them when discovering new patterns.

## Memory Files

| File | Topic | When to Read |
|---|---|---|
| [gen_ai_patterns.md](gen_ai_patterns.md) | VLM/LLM app architecture, multiprocessing, token streaming | Building any Gen AI app |
| [pipeline_optimization.md](pipeline_optimization.md) | GStreamer bottlenecks, queue tuning, scheduler-timeout | Profiling or optimizing pipelines |
| [camera_and_display.md](camera_and_display.md) | Camera init, BGR/RGB conversion, OpenCV display patterns | Camera-related work |
| [hailo_platform_api.md](hailo_platform_api.md) | VDevice, VLM.generate(), HEF resolution, device sharing | Any HailoRT interaction |
| [common_pitfalls.md](common_pitfalls.md) | Bugs found and fixed, anti-patterns to avoid | Any development task |

## Key Project Patterns

- **Pipeline apps**: `app.py` (callback + main) + `app_pipeline.py` (GStreamerApp subclass)
- **Gen AI apps**: Main class + Backend (multiprocessing) + optional event tracking
- **All apps**: Signal handling (SIGINT), graceful shutdown, resource cleanup
- `hailocropper` sends **parent detection** as ROI to inner pipeline, not the crop sub-detection
- `INFERENCE_PIPELINE_WRAPPER` sets a non-identity `scaling_bbox` on the ROI (letterbox transform)
- **New VLM apps need TWO registrations**: `defines.py` AND `resources_config.yaml`
- **YAML alias entries**: Insert AFTER the complete preceding block — never between a key and its `models:` mapping
- **CLI custom args**: Add ALL `parser.add_argument()` calls BEFORE `handle_list_models_flag()`
- **MAX_TOKENS for monitoring**: Use 100–150 (not 300) to avoid repetitive VLM output
- **Event keyword order**: Specific actions first, generic states last — first match wins
- **Video duration check**: For file inputs, verify duration > interval before launch
- **Display**: Always resize VLM frames to 640×640+, wrap overlay text, print events to terminal
- **Driver check**: Use `hailortcli fw-control identify`, NOT `lsmod | grep hailo_pci` — and verify output contains "Device Architecture", not just exit code (can return 0 with empty output)
- **Guided questions**: VLM builder agent MUST ask guided questions (app style, input source) even when user's request seems specific — fast-path only on explicit "just build it"
- **python3 not python**: Ubuntu has no `python` binary; always use `python3` in commands
- **YAML edits**: Whitespace-exact matching required; re-read target lines if first edit fails
- **Validation script**: `validate_app.py` runs 11 static checks + 2 optional runtime smoke tests (`--smoke-test`) — single gate replaces manual greps
- **Auto-approve**: Add `"chat.tools.autoApprove": true` to `.vscode/settings.json` for agentic builds
- **VLM inference timing**: ~4.7s avg on Hailo-10H with Qwen2-VL-2B at MAX_TOKENS=300
- **Short videos**: Use `--interval 5` for clips under 120s to get meaningful observation count

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
