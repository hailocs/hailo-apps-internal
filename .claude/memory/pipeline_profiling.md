# Pipeline Profiling Notes

## Quick Reference
- Profiler skill: `/profile-pipeline` (see `.claude/skills/profile-pipeline/SKILL.md`)
- Scripts: `.claude/skills/profile-pipeline/scripts/`
- Knowledge base: `.claude/skills/profile-pipeline/knowledge/knowledge_base.yaml`

## Key Defaults
- `QUEUE()`: max_size_buffers=3, leaky=no
- `INFERENCE_PIPELINE_WRAPPER` bypass: max_size_buffers=20
- `GStreamerApp` pipeline_latency=300ms
- `SOURCE_PIPELINE`: videoscale n-threads=2, videoconvert n-threads=3

## Common Bottleneck Fixes
- **videoconvert slow**: increase n-threads (up to 4), use NV12 format
- **videoscale slow**: increase n-threads, reduce source resolution
- **hailonet slow**: tune batch-size (no fixed constraint in HEF — always configurable at runtime), scheduler-timeout-ms
- **Queue fill >70%**: increase max_size_buffers
- **High jitter (P95 > 2x mean)**: investigate upstream bottleneck
- **CPU >90%**: reduce resolution or frame rate

## Important Constraints
- **NEVER suggest leaky queues mid-pipeline** — leaky queues between cropper/aggregator pairs cause frame count misalignment and pipeline hangs. The aggregator expects matching frame counts on bypass and crop paths.

## UX Notes
- After analysis, always offer to generate performance graphs (bar chart of proctime, latency waterfall, queue fill). Users prefer visual data.
- **Always open generated graphs** with `xdg-open <path>` so the user can see them on screen. Don't just embed in chat — open the file.
- Graph templates script: `.claude/skills/profile-pipeline/scripts/plot_graphs.py`
  - `python plot_graphs.py <trace_dir> --open` — generates all 4 graphs and opens them
  - Can also import: `from plot_graphs import generate_all, plot_proctime, plot_npu_breakdown, plot_latency_waterfall, plot_queue_levels`
  - Waterfall uses inline labels (name + duration on each bar segment)
  - Queue chart auto-colors by pipeline section (pose=red, palm=orange, cropper=purple, etc.)

## Discovered Patterns
(Updated by `/profile-pipeline learn` after experiments)
