````instructions
# Agent Protocols

> Behavioral contracts that every AI agent MUST follow when working in this repository.
> These protocols ensure consistent, high-quality, verifiable outputs across any agent
> (Copilot Chat, Copilot Coding Agent, Claude Code, or any LLM-based agent).

---

## Protocol 1: Context-First Execution

**NEVER write code before loading context.**

```
REQUIRED SEQUENCE:
1. Read the SKILL.md for the task type (FULL file, single read — never partial)
2. Read .hailo/memory/common_pitfalls.md
3. THEN plan
4. THEN implement
```

**SKILL.md is sufficient** — Do NOT read reference source code (e.g., pose_estimation.py,
vlm_chat.py, detection.py). SKILL.md contains complete patterns, extraction code, and
subclass examples. Reading source code wastes tool calls and adds no new information.

Only read source code if the SKILL.md explicitly says "see <file> for this specific pattern"
and the pattern is not already in SKILL.md.

**Read files fully** — Always read SKILL.md in a single `read_file` call covering the entire
file. Splitting into partial reads (e.g., lines 1-300 then 300-600) wastes a round trip.
Check file length first if unsure, but SKILL.md files are typically <400 lines.

Why: Without context, agents hallucinate imports, invent nonexistent APIs, and violate conventions. Every memory file exists because an agent previously made a mistake that is now documented.

**Enforcement**: If the first tool call in a coding task is `create_file` or `replace_string_in_file`, the agent is violating this protocol.

---

## Protocol 2: Explicit Phase Gates

**NEVER advance to the next phase without validating the current one.**

Each phase produces deliverables. Each deliverable has a validation command. Run the command. If it fails, fix it before moving on.

### Standard Gate Checks

| Phase | Gate Check Command | Expected Output |
|---|---|---|
| Directory created | `ls <app_dir>/__init__.py` | File exists |
| Constants registered | `grep "APP_NAME" hailo_apps/python/core/common/defines.py` | Constant found (only if using resolve_hef_path) |
| Module importable | `python3 -c "from hailo_apps.python... import X; print('OK')"` | `OK` |
| CLI works | `python3 -m <module> --help` | Help text, exit 0 |
| No lint errors | `get_errors` tool | Empty or acceptable |
| Tests pass | `python3 -m pytest tests/ -k <test_name>` | All pass |

### Gate Failure Protocol

```
IF gate_check FAILS:
  1. Read the error message
  2. Search .hailo/memory/common_pitfalls.md for the error
  3. If found → apply documented fix
  4. If not found → diagnose, fix, then UPDATE common_pitfalls.md
  5. Re-run gate check
  6. REPEAT until PASS
  NEVER skip a failing gate
```

---

## Protocol 3: Structured Todo Management

**Every multi-step task MUST use `manage_todo_list`.**

### Todo Naming Convention

```
Phase 0: <verb> <object>     e.g., "Load VLM context files"
Phase 1: <verb> <object>     e.g., "Register app in defines.py"
Phase 2: <verb> <object>     e.g., "Implement EventTracker class"
Phase 3: <verb> <object>     e.g., "Validate imports resolve"
Phase 4: <verb> <object>     e.g., "Write README with examples"
```

### Rules
- Mark ONE todo `in-progress` at a time
- Mark `completed` IMMEDIATELY when done — don't batch
- If a gate fails, add a new "Fix: <issue>" todo
- Keep todos at 3-7 word titles (displayed in UI)

---

## Protocol 4: Sub-Agent Delegation

**Delegate to sub-agents when tasks are independent and self-contained.**

### Delegation Decision Matrix

```
Is the task...
├── Reading multiple files in parallel?       → DELEGATE (context loader)
├── Implementing an independent module?       → DELEGATE (with full spec)
├── Running validation checks?                → DELEGATE (validation runner)
├── Making sequential edits to one file?      → KEEP (main agent)
├── Requiring accumulated conversation state? → KEEP (main agent)
└── A simple single-step operation?           → KEEP (no overhead needed)
```

### Sub-Agent Contract Template

Every sub-agent prompt MUST include these sections:

```markdown
## Task
[One clear sentence]

## Files to Read (context)
[Exact file paths — sub-agents are stateless, they need everything spelled out]

## Constraints
[Coding conventions, import rules, patterns to follow]

## Output Specification
[Exactly what to create or return]

## Self-Validation
[Commands the sub-agent should run before returning]
```

### Sub-Agent Types

**Anti-pattern: Sub-agent to read source code already covered by SKILL.md**
```
# ❌ WRONG — launching a sub-agent to find pose_estimation_pipeline.py contents
# when SKILL.md already documents GStreamerPoseEstimationApp and how to subclass it
runSubagent("Find pose estimation pipeline class and read its source code")

# ✅ RIGHT — SKILL.md has complete subclass patterns, just use them directly
# No sub-agent needed. Read SKILL.md → build.
```

Use sub-agents for: parallel file creation, independent module builds, validation runs.
Do NOT use sub-agents for: looking up information that's already in SKILL.md or memory files.

| Type | When | Prompt Focus |
|---|---|---|
| **Context Loader** | Phase 0 | "Read X files, return condensed brief" |
| **Module Builder** | Phase 2 | "Create file X with class Y following Z pattern" |
| **Test Writer** | Phase 3 | "Write tests for module X, check edge cases Y" |
| **Validator** | Phase 3 | "Run checks A,B,C — return PASS/FAIL report" |
| **Doc Writer** | Phase 4 | "Write README for app X with usage examples" |
| **Pattern Scout** | Any | "Search codebase for how X is done, return examples" |

---

## Protocol 5: Convention Verification

**Before marking any implementation phase complete, verify ALL conventions.**

### The Convention Checklist (run for every new .py file)

```bash
# 1. Absolute imports only
grep -n "^from \." <file>           # Should return NOTHING
grep -n "^import \." <file>         # Should return NOTHING

# 2. Logger used correctly
grep -n "get_logger" <file>         # Should find get_logger(__name__)

# 3. No hardcoded paths
grep -n "\.hef" <file>              # Should only appear in resolve_hef_path() calls
grep -n "/home/" <file>             # Should return NOTHING

# 4. VDevice sharing (if applicable)
grep -n "VDevice" <file>            # Should use SHARED_VDEVICE_GROUP_ID

# 5. Entry point exists (main module only)
grep -n "def main\|__name__" <file> # Should find entry point
```

---

## Protocol 6: Memory Feedback Loop

**When you discover something new, update the memory system.**

### What Triggers a Memory Update

| Discovery | Update File |
|---|---|
| New API pattern that works | `.hailo/memory/<domain>.md` |
| Bug or gotcha found | `.hailo/memory/common_pitfalls.md` |
| Performance optimization | `.hailo/memory/pipeline_optimization.md` |
| New recipe/workflow | `.hailo/knowledge/knowledge_base.yaml` |

### Memory Update Format

```markdown
## [Title] — discovered [date]

**Context**: What were you trying to do?
**Problem**: What went wrong or what was non-obvious?
**Solution**: What worked?
**Code**:
\```python
# minimal reproducible example
\```
```

---

## Protocol 7: Graceful Recovery

**When things go wrong, follow the recovery ladder.**

```
Error encountered →
  1. Read the full error message
  2. Search memory files for this error pattern
  3. Search codebase for similar code that works
  4. Check .hailo/knowledge/knowledge_base.yaml for known patterns
  5. If all else fails:
     a. Create a minimal reproducer
     b. Document the issue in memory
     c. Ask the user for guidance
  NEVER: Silently ignore errors or guess at fixes
```

---

## Protocol 8: Copilot Coding Agent (GitHub Issues)

**For use with GitHub's Copilot Coding Agent triggered from Issues.**

When Copilot Coding Agent picks up an issue:

1. **Read copilot-instructions.md** (auto-loaded)
2. **Parse the issue body** for:
   - Task type (new app / bug fix / feature / docs)
   - App archetype (pipeline / standalone / gen-ai)
   - Specific requirements
3. **Follow the orchestration phases** from `.hailo/instructions/orchestration.md`
4. **Create a PR** with:
   - All code changes
   - Updated memory files (if applicable)
   - Test evidence (CLI --help output, import validation)
   - Summary of what was built and how to test it

### Issue Label Triggers

| Label | Agent Action |
|---|---|
| `copilot` | Copilot Coding Agent picks up the issue |
| `new-app` | Follow full Phase 0-4 orchestration |
| `bug-fix` | Reproduce → Root cause → Fix → Validate → Memory |
| `enhancement` | Load context → Plan → Implement → Validate |
| `docs` | Phase 4 only (documentation) |

---

## Protocol 9: Multi-File Atomic Changes

**When creating a new app, all files must be created before any validation.**

```
BAD:  Create file A → Validate A → Create file B → Validate B
      (File A may import from B, validation fails unnecessarily)

GOOD: Create file A → Create file B → Create file C → Validate ALL
      (All cross-references resolve)
```

Within a phase, create ALL files first, THEN validate the phase as a whole.

---

## Protocol 10: Execution Speed

**Minimize tool calls and eliminate redundant work. Speed is a first-class concern.**

### 10a: Fast-Path for Clear Requests

```
IF the user's request is specific and unambiguous
   (clear app type + purpose + input source):
   → Skip interactive questions
   → Skip plan approval (present plan inline, start building)
   → Treat as "Quick build" mode automatically

ONLY ask questions when:
   - App type is genuinely ambiguous
   - Critical design choice affects architecture (e.g., monitoring vs interactive)
   - User explicitly says "let's discuss options"
```

**Example fast-path**: "Build a scene monitoring VLM app and launch with /path/to/video.mp4"
→ App type: VLM. Purpose: scene monitor. Input: file. Style: monitoring (continuous).
→ No questions needed. Present plan inline and build.

### 10b: SKILL.md Is Sufficient — Don't Read Source Code

```
DO    read: SKILL.md + toolset API refs + memory files
DON'T read: reference implementation source code (vlm_chat.py, backend.py, etc.)

SKILL.md contains:
  - Complete code templates with all imports
  - Constructor signatures and method APIs
  - Patterns, pitfalls, and configuration constants
  - The FULL pattern needed to build a standard app

ONLY read reference source code when:
  - The task requires unusual customization NOT covered by SKILL.md
  - You need to understand an internal mechanism (e.g., queue protocol)
  - SKILL.md explicitly directs you to read a specific file
```

### 10c: validate_app.py Is the Single Gate

```
DO    run: python3 .hailo/scripts/validate_app.py <app_dir> --smoke-test
DON'T run: manual grep checks, individual import tests, manual lint

The validation script checks 20+ things:
  - File existence, syntax, no relative imports
  - Logger usage, CLI parser, entry point
  - SIGINT handler, no hardcoded paths
  - README quality, CLI --help, module import

One command replaces 10+ manual checks.
```

### 10d: Community Apps Don't Need Registration

```
Community apps (run via run.sh) do NOT need:
  - Constants in defines.py
  - Entries in resources_config.yaml

Registration is only for PROMOTED apps (official apps in the main menu).
SKILL.md explicitly states this — follow it.
```

### 10e: Parallelize Independent Operations

```
BATCH these together (all independent reads):
  - SKILL.md + toolset + memory files → one parallel read

BATCH these together (all file creates):
  - __init__.py + app.yaml + run.sh + main app + support modules + README

DON'T do sequentially:
  - Read file A → Read file B → Read file C  (parallelize!)
  - Create file A → validate → Create file B → validate  (create all, validate once)
```

### 10f: Target Tool Call Budget

| Task Type | Target Tool Calls | Max |
|---|---|---|
| Simple VLM/LLM variant | 8-12 | 15 |
| Pipeline app | 10-14 | 18 |
| Standalone app | 10-14 | 18 |
| Complex agent app | 12-16 | 20 |
| Bug fix | 5-8 | 12 |

Exceeding the max indicates unnecessary work (redundant reads, manual checks,
unnecessary confirmations). Review and optimize.

---

## Protocol 11: Pre-Launch Device Verification

**Before launching ANY Hailo app, verify the device is accessible.**

**CRITICAL**: Check output content, not just exit code. `hailortcli` can return
exit code 0 with empty output when no device is present (silent false positive).

```bash
# RELIABLE check — verify output contains device info
output=$(hailortcli fw-control identify 2>&1)
if [[ -z "$output" ]] || ! echo "$output" | grep -q "Device Architecture"; then
    echo "ERROR: No Hailo device detected"
    # STOP — do not launch the app
fi
# Expected: "Device Architecture: HAILO10H" (or HAILO8, HAILO8L) + firmware version
```

**Do NOT use** `lsmod | grep hailo_pci` — it's unreliable (built-in drivers, different module names).
**Do NOT rely on exit code alone** — `hailortcli` can return 0 with empty output.

### Full Pre-Launch Sequence

```bash
# 1. Device accessible (verify OUTPUT content)
output=$(hailortcli fw-control identify 2>&1)
if [[ -z "$output" ]] || ! echo "$output" | grep -q "Device Architecture"; then
    echo "ERROR: No Hailo device detected"; exit 1
fi

# 2. Python SDK importable
python3 -c "import hailo_platform; print('hailo_platform OK')"

# 3. App framework importable
python3 -c "from hailo_apps.python.core.common.defines import *; print('hailo_apps OK')"

# 4. Input source exists (for file inputs)
ls -la /path/to/video.mp4

# 5. For short videos: check duration and set --interval appropriately
python3 -c "import cv2; c=cv2.VideoCapture('/path/to/video'); print(f'{c.get(cv2.CAP_PROP_FRAME_COUNT)/c.get(cv2.CAP_PROP_FPS):.0f}s')"
```

**If any check fails**: Report the failure clearly and STOP. Do NOT launch.

---

## Protocol Summary Card

```
┌──────────────────────────────────────────────┐
│          AGENT PROTOCOL QUICK REF            │
├──────────────────────────────────────────────┤
│  1. CONTEXT FIRST  — read before you code    │
│  2. PHASE GATES    — validate before advance │
│  3. TODO LIST      — track everything        │
│  4. SUB-AGENTS     — delegate when indep.    │
│  5. CONVENTIONS    — verify every file       │
│  6. MEMORY LOOP    — learn and record        │
│  7. RECOVERY       — never silently fail     │
│  8. ISSUE AGENT    — label-triggered         │
│  9. ATOMIC FILES   — create all, validate    │
│ 10. SPEED          — fast-path, no bloat     │
│ 11. DEVICE CHECK   — hailortcli before run   │
└──────────────────────────────────────────────┘
```

````
