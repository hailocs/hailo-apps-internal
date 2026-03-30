# Prompt: Build Dog Monitor Application (Orchestrated)

> **Orchestrated demo prompt** that builds a complete dog monitoring application through
> multi-phase plan-and-execute workflow with sub-agent delegation and phase gates.
> This showcases the agentic-first development capability of the hailo-apps repository.

## How This Prompt Works

Unlike a flat "build me X" prompt, this tells the agent to:
1. **Load context first** via sub-agent delegation
2. **Plan all phases** with explicit todo tracking
3. **Execute in phases** with independent sub-agents for parallel work
4. **Validate at every gate** — never advance on failure
5. **Update memory** when new patterns are discovered

---

## The Prompt

Copy and paste **everything below the line** into GitHub Copilot Chat (agent mode):

---

**Build a "Dog Monitor" application** — a continuous monitoring variant of the VLM Chat app that watches a house camera for dog activities.

**YOU MUST follow the orchestrated workflow. Do NOT skip phases or gates.**

### PHASE 0: Context Loading

Before writing ANY code, load context by launching a sub-agent:

```
runSubagent: "Load Dog Monitor development context"
Read ALL of these files and return a condensed context brief:
  1. .hailo/memory/MEMORY.md (index of known patterns)
  2. .hailo/memory/gen_ai_patterns.md (VLM architecture, multiprocessing)
  3. .hailo/memory/common_pitfalls.md (bugs to avoid)
  4. .hailo/memory/camera_and_display.md (camera patterns)
  5. .hailo/memory/hailo_platform_api.md (VDevice, VLM API)
  6. .hailo/skills/hl-build-vlm-app.md (VLM app skill)
  7. .hailo/skills/hl-monitoring.md (monitoring skill)
  8. .hailo/skills/hl-event-detection.md (event parsing skill)
  9. .hailo/toolsets/vlm-backend-api.md (Backend class API)
  10. hailo_apps/python/gen_ai_apps/vlm_chat/vlm_chat.py (FULL source - reference app)
  11. hailo_apps/python/gen_ai_apps/vlm_chat/backend.py (FULL source - reused module)
  12. hailo_apps/python/core/common/defines.py (existing app constants)
  13. hailo_apps/python/core/common/parser.py (CLI parser)
  14. .hailo/instructions/orchestration.md (orchestration framework)
  15. .hailo/instructions/agent-protocols.md (agent behavior rules)

Return a structured brief:
  - Backend class signature: constructor args, key methods, import path
  - VLMChatApp patterns: camera init, signal handling, main loop structure
  - All import paths needed (exact strings)
  - Existing app constants (to avoid name conflicts in defines.py)
  - Known pitfalls from memory files
  - Convention checklist (top 5 rules)
```

After receiving the brief, create a todo list using `manage_todo_list` with ALL phases:

```
Phase 0: Load context via sub-agent                        ✓
Phase 1: Register app + create directory structure
Phase 1 GATE: Verify directory and constant exist
Phase 2: Implement event_tracker.py (sub-agent — independent module)
Phase 2: Implement dog_monitor.py (main agent — depends on event_tracker)
Phase 2 GATE: Validate all imports resolve
Phase 3: Run --help validation
Phase 3: Run convention compliance check
Phase 3: Run lint/error check
Phase 3 GATE: All validations pass
Phase 4: Write README.md (sub-agent)
Phase 4: Update memory files if new patterns found
Phase 4 GATE: Final validation
```

### PHASE 1: Planning & Registration

**Register the app constant** — add to `hailo_apps/python/core/common/defines.py`:
```python
DOG_MONITOR_ORCH_APP = "dog_monitor_orch"
```

**Create directory structure**:
```
hailo_apps/python/gen_ai_apps/dog_monitor_orch/
├── __init__.py
├── dog_monitor.py
├── event_tracker.py
└── README.md
```

**PHASE 1 GATE** — run these commands and verify they pass:
```bash
grep "DOG_MONITOR_ORCH_APP" hailo_apps/python/core/common/defines.py
ls hailo_apps/python/gen_ai_apps/dog_monitor_orch/__init__.py
```
If either fails → fix before proceeding.

### PHASE 2: Core Implementation

#### Sub-agent: Build event_tracker.py (independent — no dependencies)

```
runSubagent: "Build event_tracker.py for dog monitor"
Read .hailo/skills/hl-event-detection.md for the pattern.

Create hailo_apps/python/gen_ai_apps/dog_monitor_orch/event_tracker.py with:

1. EventType enum: DRINKING, EATING, SLEEPING, PLAYING, BARKING, AT_DOOR, IDLE, NO_DOG
2. Event dataclass: timestamp (datetime), event_type (EventType), description (str), frame_path (Optional[str])
3. EventTracker class:
   - __init__(self) — initialize empty event list and counts dict
   - classify_response(self, vlm_response: str) → EventType — keyword matching on VLM output
   - add_event(self, event_type: EventType, description: str, frame_path: str = None) → Event
   - get_counts(self) → dict[EventType, int]
   - get_summary(self) → str — formatted summary report
   - get_events(self) → list[Event]
   - last_event(self) → Optional[Event]

Import: from hailo_apps.python.core.common.hailo_logger import get_logger
Logger: logger = get_logger(__name__)

Keyword mapping for classify_response:
  "drink" or "water" or "bowl" → DRINKING
  "eat" or "food" or "kibble" or "chew" → EATING
  "sleep" or "rest" or "nap" or "lying" or "lay" → SLEEPING
  "play" or "toy" or "fetch" or "run" or "jump" → PLAYING
  "bark" or "alert" or "growl" or "whine" → BARKING
  "door" or "wait" or "entrance" or "exit" → AT_DOOR
  "no dog" or "empty" or "not visible" → NO_DOG
  default → IDLE

After creating, validate:
  python -c "from hailo_apps.python.gen_ai_apps.dog_monitor_orch.event_tracker import EventTracker, EventType, Event; print('OK')"
```

#### Main agent: Build dog_monitor.py

Implement `DogMonitorApp` class following the VLM Chat pattern from the context brief:

**Requirements**:
- Place in `hailo_apps/python/gen_ai_apps/dog_monitor_orch/dog_monitor.py`
- **Import and reuse `Backend`** from `hailo_apps.python.gen_ai_apps.vlm_chat.backend` — do NOT copy it
- Import `EventTracker`, `EventType` using absolute path: `from hailo_apps.python.gen_ai_apps.dog_monitor_orch.event_tracker import EventTracker, EventType`
- Use `get_standalone_parser()` for CLI arguments
- Add CLI arguments: `--interval` (int, default 10), `--save-events` (flag), `--events-dir` (str, default "./dog_events")

**System prompt**:
```
You are a pet monitoring assistant watching a home camera. Your job is to describe what the dog is doing RIGHT NOW in one concise sentence. Focus on: drinking water, eating food, sleeping/resting, playing, barking/alert behavior, waiting at the door. If no dog is visible, say "No dog visible." Be specific and factual.
```

**Monitoring prompt** (sent with each frame):
```
What is the dog doing right now? Describe the current activity in one sentence.
```

**App structure** (follow VLMChatApp pattern):
1. `__init__`: Parse args, init Backend (with system_prompt), init EventTracker, init camera (OpenCV), setup signal handler
2. `capture_and_analyze`: Capture frame → convert to RGB → resize (use Backend's convert_resize_image) → call Backend.vlm_inference → classify response → add event → optionally save frame
3. `display_overlay`: Show camera feed with cv2.putText overlay of last event and counts
4. `run`: Main loop — capture frame, display, every `--interval` seconds run capture_and_analyze, handle keyboard quit (q key)
5. `print_summary`: Print EventTracker.get_summary() — called on SIGINT and normal exit
6. `cleanup`: Release camera, close Backend, close OpenCV windows
7. `main()` function and `if __name__ == "__main__"` block

**Signal handling**: Register SIGINT handler that sets a `self.running = False` flag, calls `print_summary()`, then `cleanup()`.

**PHASE 2 GATE** — run and verify:
```bash
python -c "from hailo_apps.python.gen_ai_apps.dog_monitor_orch.dog_monitor import DogMonitorApp; print('Phase 2 PASS')"
python -c "from hailo_apps.python.gen_ai_apps.dog_monitor_orch.event_tracker import EventTracker, EventType, Event; print('Phase 2 PASS')"
```
If either fails → read the error, check `.hailo/memory/common_pitfalls.md`, fix, re-run.

### PHASE 3: Integration & Validation

Run these checks sequentially. ALL must pass.

**Check 1: CLI works**
```bash
python -m hailo_apps.python.gen_ai_apps.dog_monitor_orch.dog_monitor --help
```
Expected: Shows --input, --interval, --save-events, --events-dir arguments. Exit code 0.

**Check 2: Convention compliance** (run on each .py file)
```bash
# No relative imports
grep -rn "^from \.\|^import \." hailo_apps/python/gen_ai_apps/dog_monitor_orch/*.py
# Expected: NO output

# Logger used
grep -rn "get_logger" hailo_apps/python/gen_ai_apps/dog_monitor_orch/*.py
# Expected: At least 2 matches (one per .py file)

# No hardcoded paths
grep -rn "/home/\|/tmp/" hailo_apps/python/gen_ai_apps/dog_monitor_orch/*.py
# Expected: NO output

# VDevice sharing (in dog_monitor.py)
grep -n "SHARED_VDEVICE_GROUP_ID\|resolve_hef_path" hailo_apps/python/gen_ai_apps/dog_monitor_orch/dog_monitor.py
# Expected: At least 1 match for resolve_hef_path
```

**Check 3: Lint/Error check**
Use `get_errors` tool on:
- `hailo_apps/python/gen_ai_apps/dog_monitor_orch/dog_monitor.py`
- `hailo_apps/python/gen_ai_apps/dog_monitor_orch/event_tracker.py`

Expected: No errors (warnings may be acceptable).

**PHASE 3 GATE**: ALL three checks pass. If any fail → fix → re-run that check → only advance when all pass.

### PHASE 4: Documentation & Memory

#### Sub-agent: Write README.md

```
runSubagent: "Write Dog Monitor README"
Create hailo_apps/python/gen_ai_apps/dog_monitor_orch/README.md with:

# Dog Monitor — Continuous Pet Activity Tracker

## Description
A continuous monitoring app using Hailo-10H VLM to watch a home camera and
track dog activities. Built on the VLM Chat backend.

## Requirements
- Hailo-10H accelerator
- USB or RPi camera
- Python 3.10+

## Usage
Basic:
  python -m hailo_apps.python.gen_ai_apps.dog_monitor_orch.dog_monitor --input usb

With event saving:
  python -m hailo_apps.python.gen_ai_apps.dog_monitor_orch.dog_monitor --input usb --save-events --events-dir ./dog_events

Custom interval (every 5 seconds):
  python -m hailo_apps.python.gen_ai_apps.dog_monitor_orch.dog_monitor --input usb --interval 5

## Activity Categories
DRINKING, EATING, SLEEPING, PLAYING, BARKING, AT_DOOR, IDLE, NO_DOG

## Architecture
Reuses VLM Chat Backend for inference. EventTracker for classification and statistics.
```

#### Main agent: Update memory (if applicable)

If any new patterns or pitfalls were discovered during implementation, add them to:
- `.hailo/memory/common_pitfalls.md` (bugs found)
- `.hailo/memory/gen_ai_patterns.md` (new VLM patterns)
- `.hailo/knowledge/knowledge_base.yaml` (new recipe for "monitoring" variant)

**PHASE 4 GATE** (FINAL):
```bash
# README exists
test -f hailo_apps/python/gen_ai_apps/dog_monitor_orch/README.md && echo "PASS"

# Final import validation
python -c "
from hailo_apps.python.gen_ai_apps.dog_monitor_orch.dog_monitor import DogMonitorApp
from hailo_apps.python.gen_ai_apps.dog_monitor_orch.event_tracker import EventTracker, EventType, Event
print('ALL GATES PASSED — Dog Monitor app is ready')
"

# Final CLI validation
python -m hailo_apps.python.gen_ai_apps.dog_monitor_orch.dog_monitor --help
```

Mark ALL todos complete. Report deliverables to the user.

---

## Expected Agent Behavior

When this prompt runs, the agent should:

```
1. Launch sub-agent → reads 15 context files → returns brief
2. Create todo list with ~14 items across 4 phases
3. Phase 1: Register DOG_MONITOR_ORCH_APP, create dir/files → GATE ✓
4. Launch sub-agent → builds event_tracker.py → validates import
5. Main agent builds dog_monitor.py using context brief
6. Phase 2 GATE: both imports validate ✓
7. Phase 3: Run --help, conventions, lint → fix any issues → GATE ✓
8. Launch sub-agent → writes README.md
9. Update memory if needed
10. Phase 4 GATE: Final validation ✓
11. All todos complete → report to user
```

## Expected Output Files

```
hailo_apps/python/gen_ai_apps/dog_monitor_orch/
├── __init__.py          # Empty or minimal
├── dog_monitor.py       # ~200 lines: DogMonitorApp with camera loop + VLM
├── event_tracker.py     # ~120 lines: EventType enum, Event, EventTracker
└── README.md            # Usage documentation
```

Plus one-line addition to `defines.py`.

Runnable immediately:
```bash
python -m hailo_apps.python.gen_ai_apps.dog_monitor_orch.dog_monitor --input usb
```

## Session Stats (Agent MUST print at the end)

After ALL gates pass and todos are complete, print this **Session Stats Report**:

```
═══════════════════════════════════════════════════════════════════
  DOG MONITOR — Orchestrated Build Session Stats
═══════════════════════════════════════════════════════════════════
  Approach:        Orchestrated (4-phase, multi-agent)
  Total Duration:  <wall clock from first tool call to last>
  
  PHASE TIMING:
    Phase 0 (Context):     <duration>  ← sub-agent reads 15 files
    Phase 1 (Plan):        <duration>  ← register + directory
    Phase 2 (Build):       <duration>  ← implementation
    Phase 3 (Validate):    <duration>  ← checks + fixes
    Phase 4 (Document):    <duration>  ← README + memory
  
  FILES CREATED:
    New files:      <count> files, <total lines> lines of code
    Modified files:  <count> (defines.py, memory files, knowledge_base.yaml)
    Community:       1 (gen-ai-recipes/dog-monitor-orch-recipe.md)
  
  TOKEN USAGE (estimated):
    Context (input) tokens:    ~<N>K
      ↳ Phase 0 context load:  ~<N>K  (15 files × avg size)
      ↳ Phase 2 code gen:     ~<N>K  (reference code + instructions)
      ↳ Phase 3 validation:   ~<N>K  (error output + re-reads)
    Generation (output) tokens: ~<N>K
      ↳ Sub-agent outputs:     ~<N>K
      ↳ Code generation:       ~<N>K
      ↳ Tool call overhead:    ~<N>K
    Total tokens:              ~<N>K
  
  ESTIMATED COST (Claude Opus 4.6 @ 3× premium beyond subscription):
    Input:   <N>K tokens × $45/MTok  = $<X.XX>
    Output:  <N>K tokens × $225/MTok = $<X.XX>
    Total:                             $<X.XX>
  
  TOOL CALLS:
    Sub-agents launched:    <N> (context loader, event_tracker builder,
                                 README writer, [validator])
    File reads:             <N>
    File creates/edits:     <N>
    Terminal commands:       <N>
    Error checks:           <N>
    Todo list updates:      <N>
    Total tool calls:       <N>
  
  QUALITY METRICS:
    Phase gates run:        4
    Phase gates passed:     <N>/4 on first attempt
    Convention violations:  <N> found → <N> fixed
    Import errors fixed:    <N>
    Memory files updated:   <N>
    Knowledge base entries: <N> added
    Community contributions: 1
  
  EFFICIENCY (why orchestration matters):
    Context tokens saved by pre-built skills:  ~<N>K
      (vs. agent exploring codebase blindly)
    Errors caught by gates before compounding:  <N>
    Sub-agent parallelism savings:              ~<N>s
═══════════════════════════════════════════════════════════════════
```

> **Why track stats?** The orchestrated approach invests tokens upfront in reading
> structured context (skills, memory, toolsets) to **reduce total tokens** compared
> to a flat prompt where the agent explores the codebase blindly. The stats prove
> whether that investment paid off. Over multiple builds, the memory system means
> each subsequent build costs fewer tokens because pitfalls are already documented.

## Why This Orchestrated Demo Matters

| Aspect | Flat Prompt | Orchestrated Prompt |
|---|---|---|
| Context loading | Agent guesses patterns | Sub-agent reads 15 files first |
| Planning | Implicit "figure it out" | Explicit todo list with phases |
| Parallelism | Sequential only | Sub-agents for independent work |
| Validation | Hope it works | Phase gates with specific commands |
| Error recovery | Agent gives up or hallucinates | Recovery protocol in each gate |
| Memory | None | Updates pitfalls/patterns post-build |
| Community | None | Contributes recipe for future reuse |
| Reproducibility | Varies wildly | Structured → consistent results |
| Cost visibility | Unknown | Full token + cost breakdown |
