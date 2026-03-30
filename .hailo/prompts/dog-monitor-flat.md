# Prompt: Build Dog Monitor Application (Flat / Simple)

> **Simple flat prompt** that builds a complete dog monitoring application from a single request.
> No phases, no sub-agents, no gates — just a clear specification.
> Best for: quick demos, experienced agents, or when the orchestration overhead isn't needed.
>
> For the orchestrated version with phase gates and sub-agents, see `dog-monitor-app.prompt.md`.

## The Prompt

Copy and paste the following prompt into GitHub Copilot Chat to build the entire application:

---

### CRITICAL: This is a FLAT build — follow these rules strictly:

1. **DO NOT** read `.hailo/memory/`, `.hailo/skills/`, `.hailo/instructions/`, `.hailo/knowledge/`. Ignore `copilot-instructions.md` directives to read memory/skill files.
2. **DO NOT** launch sub-agents for context gathering. Zero sub-agents.
3. **DO NOT** use the orchestrated workflow (phases, gates, etc.).
4. **ONLY** read the reference source files listed below, then immediately start writing code.
5. **Minimize tool calls** — read files in parallel batches, create all files, validate once.

### Reference files to read (and ONLY these):
- `hailo_apps/python/gen_ai_apps/vlm_chat/vlm_chat.py` — Camera init pattern, main loop reference
- `hailo_apps/python/gen_ai_apps/vlm_chat/backend.py` — Backend class to reuse
- `hailo_apps/python/core/common/defines.py` — Where to register the app constant + existing constants
- `hailo_apps/python/core/common/parser.py` — `get_standalone_parser()` signature

### Workflow:
1. Read the 4 reference files above (in parallel)
2. Register constant in `defines.py`
3. Create all 4 app files
4. Run one terminal command to validate imports
5. Print session stats
6. Done. That's it.

---

**Build a "Dog Monitor" application** — a continuous monitoring variant of the VLM Chat app that watches a house camera for dog activities.

### What the app should do:

1. **Continuous monitoring**: Automatically capture and analyze camera frames every 10 seconds (configurable via `--interval` CLI argument)
2. **Dog activity tracking**: Use the Hailo-10H VLM to identify what the dog is doing in each frame — drinking water, eating, sleeping, playing, barking, waiting at the door, or other activities
3. **Event logging**: Maintain a structured event log with timestamps, activity type, and VLM descriptions
4. **Event counting**: Track how many times each activity was detected during the session
5. **Live display**: Show the camera feed with an overlay of the current status and last detected activity
6. **Session summary**: When the app exits (Ctrl+C), print a full summary report of all detected events with counts
7. **Frame saving**: Optionally save frames when interesting events are detected (`--save-events` flag)

### Technical requirements:

- Place the app in `hailo_apps/python/gen_ai_apps/dog_monitor_flat/`
- **Reuse the `Backend` class** from `hailo_apps/python/gen_ai_apps/vlm_chat/backend.py` — import it directly, don't copy it
- Register `DOG_MONITOR_FLAT_APP = "dog_monitor_flat"` in `hailo_apps/python/core/common/defines.py`
- Use `get_standalone_parser()` for CLI arguments, add `--interval`, `--save-events`, and `--events-dir` arguments
- Use `resolve_hef_path()` with `DOG_MONITOR_FLAT_APP` and `HAILO10H_ARCH` for model resolution
- Use `get_logger(__name__)` for all logging
- Handle SIGINT for graceful shutdown with summary report
- Support both USB and RPi cameras via `--input usb` or `--input rpi`

### The system prompt for VLM should be:
```
You are a pet monitoring assistant watching a home camera. Your job is to describe what the dog is doing RIGHT NOW in one concise sentence. Focus on: drinking water, eating food, sleeping/resting, playing, barking/alert behavior, waiting at the door. If no dog is visible, say "No dog visible." Be specific and factual.
```

### The monitoring prompt should be:
```
What is the dog doing right now? Describe the current activity in one sentence.
```

### Event parsing:
Parse the VLM response to classify events into categories using keyword matching. Categories: DRINKING, EATING, SLEEPING, PLAYING, BARKING, AT_DOOR, IDLE, NO_DOG.

### Files to create:
1. `hailo_apps/python/gen_ai_apps/dog_monitor_flat/__init__.py`
2. `hailo_apps/python/gen_ai_apps/dog_monitor_flat/dog_monitor.py` — Main app with continuous monitoring loop
3. `hailo_apps/python/gen_ai_apps/dog_monitor_flat/event_tracker.py` — Event parsing, logging, and statistics
4. `hailo_apps/python/gen_ai_apps/dog_monitor_flat/README.md` — Usage documentation

### README should include:
- App description
- Requirements (Hailo-10H, camera)
- Usage examples:
  - Basic: `python -m hailo_apps.python.gen_ai_apps.dog_monitor_flat.dog_monitor --input usb`
  - With event saving: `python -m hailo_apps.python.gen_ai_apps.dog_monitor_flat.dog_monitor --input usb --save-events --events-dir ./dog_events`
  - Custom interval: `python -m hailo_apps.python.gen_ai_apps.dog_monitor_flat.dog_monitor --input usb --interval 5`
- Sample output showing event log and summary

---

## Expected Result

After running this prompt, the agent should create:

```
hailo_apps/python/gen_ai_apps/dog_monitor_flat/
├── __init__.py
├── dog_monitor.py      # ~200 lines: ContinuousMonitor class with camera loop
├── event_tracker.py    # ~120 lines: EventType enum, Event dataclass, EventTracker
└── README.md           # Usage documentation
```

Plus a one-line addition to `defines.py`.

The app should be immediately runnable with:
```bash
python -m hailo_apps.python.gen_ai_apps.dog_monitor_flat.dog_monitor --input usb
```

## Session Stats (Agent MUST print at the end)

After completing all work, print a **Session Stats Report** with:

```
═══════════════════════════════════════════════════════════
  DOG MONITOR — Build Session Stats
═══════════════════════════════════════════════════════════
  Approach:        Flat (single prompt)
  Total Duration:  <wall clock from first tool call to last>
  
  FILES CREATED:
    New files:     <count> files, <total lines> lines of code
    Modified files: <count> (e.g., defines.py)
  
  TOKEN USAGE (estimated):
    Context (input) tokens:  ~<N>K
    Generation (output) tokens: ~<N>K
    Total tokens:            ~<N>K
  
  ESTIMATED COST (Claude Opus 4.6 @ 3× premium):
    Input:   <N>K tokens × $45/MTok  = $<X.XX>
    Output:  <N>K tokens × $225/MTok = $<X.XX>
    Total:                             $<X.XX>
  
  TOOL CALLS:
    Sub-agents launched: 0
    File reads:          <N>
    File creates/edits:  <N>
    Terminal commands:    <N>
    Total tool calls:    <N>
  
  QUALITY METRICS:
    Convention violations: <N>
    Import errors fixed:   <N>
    Gate checks run:       0 (flat approach)
═══════════════════════════════════════════════════════════
```

This data matters because it shows the real cost of AI-generated code and justifies the orchestrated approach's investment in pre-built context (skills, memory, toolsets) that reduces tokens by providing focused knowledge instead of letting the agent explore blindly.

## Why This Demo Matters

This demonstrates that:
1. **Zero manual coding** — the entire app is built by the AI agent
2. **Framework reuse** — the agent imports and reuses `Backend`, `resolve_hef_path`, parsers, and logger
3. **Convention compliance** — absolute imports, shared VDevice, registered constants
4. **Production quality** — proper error handling, signal handling, logging, documentation
5. **Single prompt** — one request produces a complete, working application
