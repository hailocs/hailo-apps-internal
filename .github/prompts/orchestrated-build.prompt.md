# Meta-Prompt: Orchestrated Application Build

> **Universal orchestrated prompt template** — adapt this for ANY app type.
> This enforces the full plan-and-execute loop with sub-agent delegation and phase gates.

## Usage

1. Copy the template below
2. Replace all `<PLACEHOLDERS>` with your specific values
3. Paste into GitHub Copilot Chat (agent mode)

The agent will automatically:
- Load context via sub-agent
- Plan phases with todo tracking
- Delegate independent modules to sub-agents
- Validate at every phase gate
- Update memory when done

---

## Template

```
Build a "<APP_DISPLAY_NAME>" application — <one sentence description of what it does>.

YOU MUST follow the orchestrated workflow from .github/instructions/orchestration.md
YOU MUST follow agent protocols from .github/instructions/agent-protocols.md
Do NOT skip phases or gates.

### PHASE 0: Context Loading (Sub-Agent)

Launch a sub-agent to load ALL relevant context before writing any code:

  runSubagent: "Load <APP_NAME> development context"
  Read ALL of these files and return a condensed context brief:

  MEMORY (always read):
    - .github/memory/MEMORY.md
    - .github/memory/common_pitfalls.md

  DOMAIN (read the relevant ones):
    - .github/memory/gen_ai_patterns.md          ← if Gen AI app
    - .github/memory/pipeline_optimization.md     ← if GStreamer pipeline app
    - .github/memory/camera_and_display.md        ← if uses camera
    - .github/memory/hailo_platform_api.md        ← if uses HailoRT directly

  SKILLS (read the relevant ones):
    - .github/skills/<primary_skill>.md
    - .github/skills/<secondary_skill>.md
    - .github/skills/hl-plan-and-execute.md
    - .github/skills/hl-validate.md

  TOOLSETS (read the relevant ones):
    - .github/toolsets/<relevant_api>.md

  REFERENCE CODE (read full source):
    - <reference_app_main_file>
    - <reference_app_supporting_files>
    - hailo_apps/python/core/common/defines.py

  ORCHESTRATION:
    - .github/instructions/orchestration.md
    - .github/instructions/agent-protocols.md

  Return a structured brief:
    - Reference app patterns to follow
    - All import paths needed (exact strings)
    - Existing app constants (to avoid conflicts)
    - Known pitfalls for this domain
    - Convention checklist (top 5)

After receiving the brief, create a todo list with ALL phases.

### PHASE 1: Planning & Registration

1. Register app constant: <APP_CONSTANT> = "<app_name>" in defines.py
2. Create directory: hailo_apps/python/<app_category>/<app_name>/
3. Create __init__.py
4. Create stub files for all modules (empty or with signatures only)

PHASE 1 GATE:
  grep "<APP_CONSTANT>" hailo_apps/python/core/common/defines.py
  ls hailo_apps/python/<app_category>/<app_name>/__init__.py

### PHASE 2: Core Implementation

For each independent module → delegate to a sub-agent:
  runSubagent: "Build <module_name>.py"
  [Provide: file path, class specs, method signatures, imports, conventions]
  [Include: self-validation command to run after creating]

For dependent modules → implement in main agent using context brief.

PHASE 2 GATE:
  python3 -c "from hailo_apps.python.<app_category>.<app_name>.<module> import <Class>; print('OK')"
  (run for each module)

### PHASE 3: Integration & Validation

Check 1 — CLI validation:
  python3 -m hailo_apps.python.<app_category>.<app_name>.<main_module> --help

Check 2 — Convention compliance:
  grep -rn "^from \.\|^import \." hailo_apps/python/<app_category>/<app_name>/*.py  → EMPTY
  grep -rn "get_logger" hailo_apps/python/<app_category>/<app_name>/*.py  → FOUND
  grep -rn "/home/\|/tmp/" hailo_apps/python/<app_category>/<app_name>/*.py  → EMPTY

Check 3 — Lint/error check:
  Use get_errors tool on all .py files

PHASE 3 GATE: ALL checks pass. Fix and re-run if any fail.

### PHASE 4: Documentation & Memory

Sub-agent: Write README.md with description, requirements, usage examples.
Main agent: Update .github/memory/ if new patterns discovered.
Main agent: Add recipe to .github/knowledge/knowledge_base.yaml if applicable.

PHASE 4 GATE (FINAL):
  test -f <app_dir>/README.md && echo "PASS"
  python3 -c "from hailo_apps.python.<app_category>.<app_name>.<main_module> import <MainClass>; print('FINAL PASS')"
  python3 -m hailo_apps.python.<app_category>.<app_name>.<main_module> --help

Mark all todos complete. Report deliverables.
```

---

## Quick-Fill Examples

### VLM Variant App

| Placeholder | Value |
|---|---|
| `<APP_DISPLAY_NAME>` | Security Camera Monitor |
| `<APP_NAME>` | security_monitor |
| `<APP_CONSTANT>` | SECURITY_MONITOR_APP |
| `<app_category>` | gen_ai_apps |
| `<primary_skill>` | hl-build-vlm-app |
| `<secondary_skill>` | hl-monitoring |
| `<relevant_api>` | vlm-backend-api |
| `<reference_app_main_file>` | hailo_apps/python/gen_ai_apps/vlm_chat/vlm_chat.py |

### Pipeline Detection App

| Placeholder | Value |
|---|---|
| `<APP_DISPLAY_NAME>` | PPE Detection Pipeline |
| `<APP_NAME>` | ppe_detection |
| `<APP_CONSTANT>` | PPE_DETECTION_APP |
| `<app_category>` | pipeline_apps |
| `<primary_skill>` | hl-build-pipeline-app |
| `<secondary_skill>` | hl-event-detection |
| `<relevant_api>` | gstreamer-elements |
| `<reference_app_main_file>` | hailo_apps/python/pipeline_apps/detection/detection_app.py |

### Standalone Inference App

| Placeholder | Value |
|---|---|
| `<APP_DISPLAY_NAME>` | Badge Reader |
| `<APP_NAME>` | badge_reader |
| `<APP_CONSTANT>` | BADGE_READER_APP |
| `<app_category>` | standalone_apps |
| `<primary_skill>` | hl-build-standalone-app |
| `<secondary_skill>` | hl-camera |
| `<relevant_api>` | core-framework-api |
| `<reference_app_main_file>` | hailo_apps/python/standalone_apps/face_recognition/face_recon.py |

### Agent with Tool Calling

| Placeholder | Value |
|---|---|
| `<APP_DISPLAY_NAME>` | Home Assistant Agent |
| `<APP_NAME>` | home_assistant |
| `<APP_CONSTANT>` | HOME_ASSISTANT_APP |
| `<app_category>` | gen_ai_apps |
| `<primary_skill>` | hl-build-agent-app |
| `<secondary_skill>` | hl-build-voice-app |
| `<relevant_api>` | gen-ai-utilities |
| `<reference_app_main_file>` | hailo_apps/python/gen_ai_apps/agent_tools_example/agent.py |

---

## Copilot Coding Agent (GitHub Issues) Format

To trigger this via a GitHub Issue (for Copilot Coding Agent):

```markdown
## Title: Build <APP_DISPLAY_NAME> Application

## Labels: copilot, new-app

## Body:
Build a "<APP_DISPLAY_NAME>" application that <description>.

### App Type: <pipeline | standalone | gen-ai>

### Skill: .github/skills/<primary_skill>.md

### Orchestration: Follow .github/instructions/orchestration.md

### Requirements:
- <requirement 1>
- <requirement 2>
- <requirement 3>

### Files to Create:
- hailo_apps/python/<category>/<app_name>/<main_module>.py
- hailo_apps/python/<category>/<app_name>/<support_module>.py
- hailo_apps/python/<category>/<app_name>/README.md

### Acceptance Criteria:
- [ ] `python3 -m hailo_apps.python.<category>.<app_name>.<main_module> --help` exits 0
- [ ] No relative imports
- [ ] Uses get_logger(__name__)
- [ ] Uses resolve_hef_path() for models
- [ ] README.md with usage examples
- [ ] All phase gates pass