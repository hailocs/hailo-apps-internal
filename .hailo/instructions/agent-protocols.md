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
1. Read .hailo/memory/MEMORY.md
2. Read skill file for the task type
3. Read reference implementation source code
4. THEN plan
5. THEN implement
```

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
| Constants registered | `grep "APP_NAME" hailo_apps/python/core/common/defines.py` | Constant found |
| Module importable | `python -c "from hailo_apps.python... import X; print('OK')"` | `OK` |
| CLI works | `python -m <module> --help` | Help text, exit 0 |
| No lint errors | `get_errors` tool | Empty or acceptable |
| Tests pass | `python -m pytest tests/ -k <test_name>` | All pass |

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
| Community insight | `community/contributions/<category>/` |

### Contribution Recipe Format

After building any app, create a contribution recipe in `community/contributions/<category>/`:

**File naming**: `YYYY-MM-DD_<app>_<slug>.md`

**Required YAML frontmatter**:
```yaml
---
title: "Short descriptive title"
contributor: "Your Name or AI Agent (auto-generated)"
date: "YYYY-MM-DD"
category: gen-ai-recipes    # or pipeline-optimization, bottleneck-patterns, etc.
hailo_arch: hailo10h
app: <app_name>
tags: [relevant, tags, here]
reproducibility: verified
---
```

**Required sections**: Summary, Context, Finding, Solution, Results, Applicability.

These recipes are later curated into `.hailo/` via `python .hailo/scripts/curate_contributions.py --curate`.

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

## Protocol 10: Community App Lifecycle

**All agent-built apps go to `community/apps/`, not `hailo_apps/`.**

### Why

The `hailo_apps/` package is the official, reviewed codebase. Agent-built apps need
review before promotion. The `community/apps/` staging area isolates experimental
code while still allowing it to import and reuse core utilities.

### App Creation Flow

```
Agent builds app →
  1. Create community/apps/<app_name>/ with app.yaml, run.sh, code, README
  2. Create community/contributions/<category>/<date>_<app_name>_recipe.md
  3. Do NOT modify defines.py or resources_config.yaml
  4. Run via: ./community/apps/<app_name>/run.sh --input <source>
```

### Required app.yaml Fields

```yaml
name: <app_name>          # Snake case
title: <Title>            # Human readable
description: <one-liner>
author: <name or "AI Agent (auto-generated)">
date: "YYYY-MM-DD"
type: gen_ai              # gen_ai | pipeline | standalone
hailo_arch: hailo10h      # hailo8 | hailo8l | hailo10h
model: <model-name>
tags: [tag1, tag2]
status: draft             # draft | reviewed | promoted
```

### Promotion (human-triggered)

```bash
python .hailo/scripts/curate_contributions.py --promote <app_name>
```

This moves the app to `hailo_apps/python/<category>/<app_name>/`, registers it in
`defines.py` and `resources_config.yaml`, and deletes the community copy.

### Curation (knowledge artifacts)

```bash
python .hailo/scripts/curate_contributions.py --curate       # Interactive
python .hailo/scripts/curate_contributions.py --curate --auto # Auto-accept valid
```

This processes `community/contributions/` into `.hailo/` using a **tiered system**:

| Tier | Behavior | Target files |
|------|----------|-------------|
| **Tier 1** (full append) | Complete contribution content appended | `memory/*.md`, `knowledge/*.yaml` |
| **Tier 2** (summary append) | Short 3-line summary with cross-reference to Tier 1 | `## Community Findings` sections in skills, toolsets, instructions |
| **Tier 3** (never auto-modified) | Core structural files | `coding-standards.md`, `agent-protocols.md`, `orchestration.md`, `copilot-instructions.md` |

After curation, originals are deleted. Run `generate_platforms.py --generate` to sync
`.hailo/` changes to `.github/` and `.claude/`. The `curate_and_propose.py` wrapper
does this automatically and opens a PR.

**Categories**: `pipeline-optimization`, `bottleneck-patterns`, `gen-ai-recipes`,
`hardware-config`, `model-tuning`, `camera-display`, `voice-audio`, `general`.

---

## Protocol Summary Card

```
┌─────────────────────────────────────────────┐
│          AGENT PROTOCOL QUICK REF           │
├─────────────────────────────────────────────┤
│ 1. CONTEXT FIRST — read before you code     │
│ 2. PHASE GATES  — validate before advance   │
│ 3. TODO LIST    — track everything          │
│ 4. SUB-AGENTS   — delegate when independent │
│ 5. CONVENTIONS  — verify every file         │
│ 6. MEMORY LOOP  — learn and record          │
│ 7. RECOVERY     — never silently fail       │
│ 8. ISSUE AGENT  — label-triggered workflow  │
│ 9. ATOMIC FILES — create all, then validate │
│10. COMMUNITY    — apps → community/apps/    │
│                   recipes → contributions/  │
│                   curate → .hailo/          │
└─────────────────────────────────────────────┘
```

````
