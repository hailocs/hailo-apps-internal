````instructions
# Multi-Agent Orchestration Framework

> How to structure agentic work into phases, delegate to sub-agents, validate at each gate, and produce production-quality applications through plan-and-execute loops.

## Core Principle: Plan → Execute → Validate → Advance

Every non-trivial task MUST follow this loop:

```
┌─────────────────────────────────────────────────┐
│  PHASE GATE: Can we advance?                    │
│  ✓ All files created?                           │
│  ✓ Imports resolve?                             │
│  ✓ Conventions followed?                        │
│  ✓ Tests/lint pass?                             │
│  ✗ → Fix issues before advancing                │
└──────────────────────┬──────────────────────────┘
                       │
    ┌──────────────────┴───────────────────┐
    │         PLAN-AND-EXECUTE LOOP        │
    │                                      │
    │  1. PLAN: Read context, break into   │
    │     phases, create todo list         │
    │  2. EXECUTE: Work one phase at a     │
    │     time, delegate to sub-agents     │
    │  3. VALIDATE: Check each deliverable │
    │     at the phase gate                │
    │  4. ADVANCE: Only proceed when the   │
    │     gate passes                      │
    └──────────────────────────────────────┘
```

---

## Phase Definitions for App Development

### Phase 0: Context Loading (ALWAYS FIRST)

**Goal**: Load all relevant knowledge before writing any code.

#### Context Budget: Match Depth to Complexity

Not all tasks need the same amount of context. Over-reading costs time and tokens.

| Task complexity | Context reads needed | Examples |
|---|---|---|
| **Simple variant** (reuses existing app pattern) | SKILL.md + 1 reference file + common_pitfalls.md | People counter, custom overlay, class filter |
| **Standard new app** (new logic, existing infra) | SKILL.md + coding-standards.md + 1-2 reference files + common_pitfalls.md | Monitoring app, dashboard, multi-source |
| **Complex/novel app** (new patterns, multi-module) | Full routing table + multiple reference files + toolset APIs | Agent with tools, cascaded pipeline, voice+VLM |

**Fast-path rule**: If the SKILL.md contains a complete buildable template AND the task is a straightforward variant of that template, read only:
1. The relevant `SKILL.md` (has template code with exact imports)
2. The closest reference implementation source file (1 file, not the whole app)
3. `.github/memory/common_pitfalls.md`

Skip toolset references, helper pipeline internals, and framework source code — the SKILL template already encodes the correct usage.

#### Full Context Loading (for standard/complex tasks)

```
MANDATORY READS (in this order):
1. .github/memory/MEMORY.md                    ← Index of known patterns
2. .github/memory/<relevant_domain>.md         ← Domain-specific knowledge
3. .github/skills/<skill>.md      ← The skill being used
4. .github/knowledge/knowledge_base.yaml       ← Recipes & patterns
5. .github/toolsets/<relevant_api>.md           ← API reference
6. Reference implementation source code        ← Read actual code, not just docs
```

**Phase Gate**: Agent must be able to answer:
- What app archetype am I building? (pipeline / standalone / gen-ai)
- What existing modules will I reuse?
- What are the critical conventions?
- What pitfalls have been documented for this domain?

**Sub-agent delegation**: Launch a sub-agent to read all context files in parallel:
```
runSubagent: "Read these files and return a condensed context brief:
  - .github/memory/MEMORY.md
  - .github/memory/gen_ai_patterns.md
  - .github/skills/hl-build-vlm-app.md
  - .github/toolsets/vlm-backend-api.md
  - hailo_apps/python/gen_ai_apps/vlm_chat/vlm_chat.py
  - hailo_apps/python/gen_ai_apps/vlm_chat/backend.py
  Return: key patterns, function signatures, import paths, pitfalls"
```

### Phase 1: Planning & Registration

**Goal**: Define the file structure, register the app, plan all interfaces.

**Tasks**:
1. Create the todo list with ALL phases and tasks
2. Register app constant in `defines.py` (official apps) OR create `app.yaml` + `run.sh` (community apps)
3. Define the module structure (which files, what each contains)
4. Define all class/function signatures (interfaces only, no implementation)
5. Identify all imports needed

**Phase Gate** checklist:
- [ ] App registered: constant in `defines.py` (official) OR `app.yaml` present (community)
- [ ] Directory created with `__init__.py`
- [ ] All file stubs created with class/function signatures
- [ ] Import paths validated (run `python -c "from hailo_apps.python... import ..."` for official, or `PYTHONPATH=. python -c "..."` for community)
- [ ] Todo list reflects all remaining work

### Phase 2: Core Implementation

**Goal**: Implement the main application logic.

**Sub-agent delegation strategy**: Break into independent units that can be built in parallel:
```
Sub-agent A: "Implement event_tracker.py with EventType enum, Event dataclass,
             EventTracker class. Follow patterns from .github/skills/hl-event-detection.md"

Sub-agent B: "Implement the main app class in dog_monitor.py following the VLM chat
             pattern from vlm_chat.py. Reuse Backend from vlm_chat/backend.py"
```

**Phase Gate** checklist:
- [ ] All classes and functions implemented
- [ ] All imports are absolute (`from hailo_apps.python.core.common...`)
- [ ] `resolve_hef_path()` used for model resolution
- [ ] `SHARED_VDEVICE_GROUP_ID` used for VDevice
- [ ] `get_logger(__name__)` used everywhere
- [ ] Signal handling (SIGINT) implemented for graceful shutdown
- [ ] No hardcoded paths or magic numbers
- [ ] Run `python -c "from hailo_apps.python.gen_ai_apps.<app> import *"` SUCCESS

### Phase 3: Integration & Validation

**Goal**: Ensure the app works end-to-end.

**Tasks**:
1. Run lint/type checks on all new files
2. Verify CLI argument parsing works: `python -m <module> --help`
3. Cross-reference with memory files for known pitfalls
4. Check that error messages are user-friendly
5. Verify resource cleanup (VDevice release, camera close, file handles)

**Phase Gate** checklist:
- [ ] `python -m hailo_apps.python.gen_ai_apps.<app>.<main> --help` works
- [ ] No lint errors (`get_errors` tool returns clean)
- [ ] Signal handler prints session summary
- [ ] All resources cleaned up in `finally` blocks
- [ ] README.md with usage examples

### Phase 4: Documentation & Memory Update

**Goal**: Document the app and update the knowledge base.

**Tasks**:
1. Create README.md with description, requirements, usage, sample output
2. Update `.github/memory/` if new patterns were discovered
3. Update `.github/knowledge/knowledge_base.yaml` with new recipe
4. Verify all convention compliance one final time

**Phase Gate** (FINAL):
- [ ] README.md exists with usage examples
- [ ] `--help` output matches README
- [ ] Memory files updated if new patterns found
- [ ] All todo items marked complete

---

## Sub-Agent Delegation Patterns

### When to Delegate to a Sub-Agent

| Situation | Delegate? | Rationale |
|---|---|---|
| Reading 5+ context files | YES | Parallel reads, condensed brief saves tokens |
| Implementing independent modules | YES | No shared state, can work in parallel |
| Searching for patterns across codebase | YES | Sub-agent can grep/search exhaustively |
| Sequential edits to one file | NO | Single agent maintains coherent state |
| Validation that needs full context | NO | Main agent has accumulated context |
| Writing tests for code just written | YES | Test writer doesn't need implementation context |

### Sub-Agent Prompt Template

Always structure sub-agent prompts with these 5 sections:

```
## Task
[One sentence describing what to do]

## Context
[Files to read, patterns to follow, constraints]

## Constraints
- Follow absolute imports: from hailo_apps.python.core...
- Use get_logger(__name__) for logging
- [domain-specific constraints]

## Deliverable
[Exactly what to create/return — file paths, code, or information]

## Validation
[How to verify the work is correct — commands to run, checks to perform]
```

### Example: Context-Loading Sub-Agent

```
runSubagent:
  description: "Load VLM development context"
  prompt: |
    ## Task
    Read all context files needed to build a VLM-based monitoring app and return
    a condensed context brief.

    ## Context
    Read these files in full:
    1. .github/memory/MEMORY.md
    2. .github/memory/gen_ai_patterns.md
    3. .github/memory/common_pitfalls.md
    4. .github/skills/hl-build-vlm-app.md
    5. .github/toolsets/vlm-backend-api.md
    6. hailo_apps/python/gen_ai_apps/vlm_chat/vlm_chat.py (full source)
    7. hailo_apps/python/gen_ai_apps/vlm_chat/backend.py (full source)
    8. hailo_apps/python/core/common/defines.py (search for existing app constants)

    ## Deliverable
    Return a structured brief with:
    - All import paths needed (exact strings)
    - Backend class constructor signature and key methods
    - VLMChatApp patterns to reuse (camera loop, signal handling, state machine)
    - Known pitfalls from memory files
    - Existing app constants from defines.py (to avoid naming conflicts)
```

### Example: Implementation Sub-Agent

```
runSubagent:
  description: "Build event tracker module"
  prompt: |
    ## Task
    Create the file hailo_apps/python/gen_ai_apps/dog_monitor/event_tracker.py

    ## Context
    Read .github/skills/hl-event-detection.md for the pattern.
    This module tracks dog activities detected by VLM analysis.

    ## Constraints
    - from hailo_apps.python.core.common.hailo_logger import get_logger
    - EventType enum: DRINKING, EATING, SLEEPING, PLAYING, BARKING, AT_DOOR, IDLE, NO_DOG
    - Event dataclass: timestamp, event_type, description, frame_path (optional)
    - EventTracker class: add_event(), get_summary(), get_counts(), classify_response(str) → EventType
    - classify_response uses keyword matching on VLM output

    ## Deliverable
    Create the file using create_file tool. Return the file path and line count.

    ## Validation
    After creating, run: python -c "from hailo_apps.python.gen_ai_apps.dog_monitor.event_tracker import EventTracker, EventType, Event; print('OK')"
```

### Example: Validation Sub-Agent

```
runSubagent:
  description: "Validate dog monitor app"
  prompt: |
    ## Task
    Validate the dog_monitor application for correctness and convention compliance.

    ## Checks to Perform
    1. Run: python -c "from hailo_apps.python.gen_ai_apps.dog_monitor.dog_monitor import DogMonitorApp"
    2. Run: python -m hailo_apps.python.gen_ai_apps.dog_monitor.dog_monitor --help
    3. Use get_errors tool on all .py files in the dog_monitor directory
    4. Verify these conventions in each .py file:
       - All imports are absolute (from hailo_apps.python...)
       - get_logger(__name__) is used
       - No hardcoded file paths
       - SIGINT handler exists in main module
    5. Verify README.md exists and has usage examples

    ## Deliverable
    Return a validation report:
    - PASS/FAIL for each check
    - List of issues found (if any)
    - Suggested fixes for each issue
```

---

## Plan-and-Execute Loop Protocol

### Step 1: Create the Plan

At the start of every multi-step task, create a todo list that maps to phases:

```
manage_todo_list:
  Phase 0: Load Context
    - Read memory files and skill instructions
    - Read reference implementation source
    - Compile context brief
  Phase 1: Planning & Registration
    - Register app constant in defines.py
    - Create directory and __init__.py
    - Define all interfaces (signatures only)
  Phase 2: Core Implementation
    - Implement module A (via sub-agent)
    - Implement module B (via sub-agent)
    - Implement main app class
  Phase 3: Integration & Validation
    - Run import validation
    - Run CLI --help validation
    - Run lint/error check
    - Fix any issues found
  Phase 4: Documentation
    - Create README.md
    - Update memory files
    - Final validation
```

### Step 2: Execute with Gate Checks

Between each phase, run explicit validation:

**For official apps** (in `hailo_apps/python/`):
```python
# After Phase 1:
python -c "from hailo_apps.python.gen_ai_apps.dog_monitor import __init__; print('Phase 1 PASS')"
# After Phase 2:
python -c "from hailo_apps.python.gen_ai_apps.dog_monitor.dog_monitor import DogMonitorApp; print('Phase 2 PASS')"
# After Phase 3:
python -m hailo_apps.python.gen_ai_apps.dog_monitor.dog_monitor --help
```

**For community apps** (in `community/apps/`):
```bash
# After Phase 1:
ls community/apps/gen_ai_apps/dog_monitor/app.yaml && echo 'Phase 1 PASS'
# After Phase 2:
PYTHONPATH=. python -c "import sys; sys.path.insert(0,'community/apps/gen_ai_apps/dog_monitor'); from dog_monitor import DogMonitorApp; print('Phase 2 PASS')"
# After Phase 3:
./community/apps/gen_ai_apps/dog_monitor/run.sh --help
```

### Step 3: Recover from Failures

If a phase gate fails:

1. **Read the error message** carefully
2. **Check memory files** — the error may be a documented pitfall
3. **Fix the issue** in the current phase — do NOT advance
4. **Re-run the gate check** — must pass before proceeding
5. **Update memory** if this was a new pitfall

---

## Orchestration for Different Task Types

### New VLM App Variant
```
Phases: Context → Register → Backend adaptation → Main app → Events/tracking → Validate → Docs
Sub-agents: Context loader, event module builder, validation checker
Gate checks: Import validation, --help, lint
```

### New Pipeline App
```
Phases: Context → Register → Pipeline string composition → Callback impl → Validate → Docs
Sub-agents: Context loader, pipeline string builder (test with gst-launch-1.0)
Gate checks: Import validation, pipeline parse test, --help
```

### New Agent Tool
```
Phases: Context → Tool class impl → YAML config → Register → Validate → Docs
Sub-agents: Context loader, tool implementation, validation
Gate checks: Tool instantiation, config loading, --help
```

### Bug Fix
```
Phases: Reproduce → Root cause → Fix → Validate → Memory update
Sub-agents: Context loader (memory + related code), validation runner
Gate checks: Bug no longer reproduces, no regressions
```

---

## Concurrency Model

```
                    ┌─────────────┐
                    │  Main Agent │ (orchestrator)
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
        ┌─────┴─────┐ ┌───┴───┐ ┌─────┴─────┐
        │ Sub-agent  │ │ Sub-  │ │ Sub-agent  │
        │ Context    │ │ agent │ │ Validation │
        │ Loader     │ │ Impl  │ │ Runner     │
        └────────────┘ └───────┘ └────────────┘
              │            │            │
              ▼            ▼            ▼
         Context       Code files    PASS/FAIL
         brief         created       report
```

**Important**: Sub-agents are stateless. Each gets a complete, self-contained prompt. They cannot communicate with each other. The main agent merges their outputs.

---

## Anti-Patterns to Avoid

| Anti-Pattern | Why It Fails | Do This Instead |
|---|---|---|
| Skipping Phase 0 | Write code with wrong patterns | Always load context first |
| No phase gates | Errors compound across phases | Validate before advancing |
| One giant sub-agent prompt | Too much context, hallucinations | Break into focused prompts |
| Never reading memory | Repeat known bugs | Check memory at task start |
| Advancing past failures | Broken foundation | Fix first, advance second |
| No todo list | Lose track, skip steps | Always create plan first |
| Sub-agent for sequential edits | Half-applied changes | Keep sequential edits in main agent |

````
