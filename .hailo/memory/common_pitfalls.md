# Common Pitfalls — Memory

> Bugs found, anti-patterns encountered, and lessons learned. Check before writing new code.
>
> **Domain sections**: Each section is tagged so agents load ONLY relevant pitfalls.
> - **UNIVERSAL** — All agents MUST read (imports, signals, cleanup, logging, agent workflow)
> - **PIPELINE** — GStreamer pipeline apps (queue, set_frame, VAAPI, pipeline strings)
> - **GEN-AI** — VLM / LLM / Agent / Voice apps (multiprocessing, OpenCV, VLM tuning)
> - **GAME** — Interactive / game apps (mechanics parsing, background rendering, keypoints)

---

# GAME — Game / Interactive App Pitfalls

## Game / Interactive App — Follow the User's Exact Description

### Wrong: Assuming common game archetypes
When a user says "build an Easter eggs game where an egg should be placed and
user catches it", **do NOT** assume the standard falling-objects arcade pattern.
The user described: one egg, stationary, placed randomly, catch-and-replace.
```
# ❌ User said "an egg should be placed" → agent built falling eggs from above
#    "an egg" = singular, "placed" = stationary, not falling
```

### Right: Parse the mechanics literally from the prompt
1. **Count**: "an egg" = one at a time; "eggs fall" = multiple
2. **Motion**: "placed" = stationary; "falling/dropping" = moving
3. **Flow**: "catch it … another one placed" = sequential spawn on catch
4. **Interaction**: "find" = search; "catch" = touch/collide; "dodge" = avoid

**Rule**: For interactive/game apps, extract exact mechanics from the user's
words before building. If ambiguous, ask. Never substitute a genre assumption
for what the user actually wrote. Re-read the prompt once more before coding
the game loop.

---

# UNIVERSAL — All Agents Must Read

## Phase 4 (Document) Skipped — README Not Created

Agents commonly rush from Phase 3 (Validate) straight to launch, skipping Phase 4
(Document). This leaves the app without a README.md.

### Root causes
1. **"Launch when done" tunnel vision** — The user's prompt ends with "launch it",
   so the agent marks the task complete after launching, forgetting documentation.
2. **README not in todo list** — The agent creates todo items for build + validate +
   launch but never adds a "Write README" item.
3. **Phase 4 gate not enforced** — The orchestration loop says "README, update memory"
   but agents don't treat it as a hard gate.

### Fix
- **Always include "Write README.md" as an explicit todo item** — never omit it.
- **"Launch" must be the LAST todo** — after README, after validation.
- **README.md is a required deliverable** — listed in every SKILL.md directory tree.
  If it doesn't exist when all other todos are done, the build is incomplete.

## Agent Iteration Leftover Code (CRITICAL)

When agents iterate on code (fixing errors, trying alternatives), they leave behind:
- **Unused imports** from failed attempts (e.g., `import threading` that's no longer used)
- **Duplicate function definitions** (agent rewrote `def process()` but left the old one)
- **Unreachable code** after `return`/`break`/`sys.exit()` statements
- **Commented-out code blocks** from previous approaches

This is the **#1 source of messy agent-generated code**. The `validate_app.py` script
now checks for unused imports and unreachable code. Always run Phase 4b (Code Cleanup)
before Phase 5 (Validate).

## Import Errors

### Wrong: Relative imports in app code
```python
# ❌ This breaks when running with python -m
from .backend import Backend
from ..core.common.core import resolve_hef_path
```

### Right: Always absolute
```python
# ✅ Works everywhere
from hailo_apps.python.gen_ai_apps.vlm_chat.backend import Backend
from hailo_apps.python.core.common.core import resolve_hef_path
```

**Exception**: `try/except ImportError` with fallback to relative is acceptable for dual-mode modules (see agent.py pattern).

## Signal Handling

### Wrong: Cleanup in signal handler directly
```python
def signal_handler(sig, frame):
    self.backend.close()  # May deadlock if caught during queue operation
    sys.exit(0)
```

### Right: Set flag, clean up in main loop
```python
def signal_handler(self, sig, frame):
    self.running = False  # Flag only

def run(self):
    try:
        while self.running:
            # ... main loop
    finally:
        self.backend.close()  # Clean up here
```

## Multiprocessing Queue Gotchas

### Deadlock on Full Queue
If `maxsize` is reached and you `put()` without timeout, the process blocks forever.
```python
# ❌ Can deadlock
self._request_queue.put(data)

# ✅ Always use timeout on both put and get
self._request_queue.put(data, timeout=5)
response = self._response_queue.get(timeout=timeout)
```

### Orphaned Worker Processes
If main process crashes without sending sentinel, worker blocks forever.
**Fix**: Always use `try/finally` in main process:
```python
try:
    app.run()
finally:
    app.stop()  # Sends None sentinel to worker
```

---

# GEN-AI — VLM / LLM / Agent / Voice Pitfalls

## OpenCV

### imshow Before waitKey
`cv2.imshow()` won't actually display until `cv2.waitKey()` is called. Both are needed.

### BGR vs RGB Confusion
- OpenCV reads as **BGR**
- VLM expects **RGB**  
- OpenCV displays **BGR**
- `cv2.imwrite()` expects **BGR**
- PIL/Pillow reads as **RGB**
- GStreamer `get_numpy_from_buffer()` returns **RGB**

**Rule**: Convert to RGB only when sending to VLM. Keep BGR for everything else.

### GStreamer set_frame() Requires BGR
When using `use_frame=True` in GStreamer pipeline callbacks, frames from
`get_numpy_from_buffer()` are **RGB**. You MUST convert before `set_frame()`:
```python
# Frame comes as RGB from GStreamer
frame = get_numpy_from_buffer(buffer, format, width, height)
# ... draw on frame with OpenCV ...
frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)  # MUST convert
user_data.set_frame(frame)
```
**Forgetting this conversion produces blue-tinted output.** The display pipeline
expects BGR.

---

# PIPELINE — GStreamer Pipeline App Pitfalls

## use_frame Overwritten by GStreamerApp Constructor

### Wrong: Setting use_frame only in callback class
`GStreamerApp.__init__()` unconditionally overwrites `user_data.use_frame` from
`self.options_menu.use_frame` (CLI default: `False`). Setting it in the callback
class constructor has **no effect** — the parent constructor runs after and resets it.
```python
# ❌ WRONG — gets overwritten to False by GStreamerApp.__init__()
class MyCallback(app_callback_class):
    def __init__(self):
        super().__init__()
        self.use_frame = True  # overwritten!
```
The result: the `display_user_data_frame` process never starts, so `set_frame()`
calls are silently ignored and only the raw camera feed is displayed.

### Right: Force use_frame in the app's __init__ AFTER super().__init__()
```python
# ✅ CORRECT — override after parent constructor
class MyGame(GStreamerPoseEstimationApp):
    def __init__(self, app_callback, user_data, parser=None):
        super().__init__(app_callback, user_data, parser)
        self.options_menu.use_frame = True  # needed for display process to start
        user_data.use_frame = True          # needed for callback to access frame
```
**Both** `self.options_menu.use_frame` AND `user_data.use_frame` must be set.
The options_menu flag controls whether `display_user_data_frame` process is
spawned in `GStreamerApp.run()`. The user_data flag controls frame extraction
in the callback.

## HEF Path Resolution

### Wrong: resolve_hef_path with wrong app_name
If `app_name` isn't registered in `resources_config.yaml`, resolution silently falls back to searching the filesystem — which may find the wrong model or fail.

**Fix**: Always register new apps in `resources_config.yaml` before using `resolve_hef_path`.

### Wrong: Register in defines.py but forget resources_config.yaml
Adding a constant to `defines.py` alone is NOT enough. `resolve_hef_path()` looks up the
app name in the config manager, which reads `resources_config.yaml`.
```
KeyError: 'my_new_app'  ← This means resources_config.yaml is missing the entry
```
**Fix**: For VLM apps that reuse the same model, add a YAML anchor alias:
```yaml
my_new_app: *vlm_chat_app
```

## USB Camera Device Selection

### Wrong: Hardcoding /dev/video0 for USB camera
`/dev/video0` is typically the **integrated webcam** (laptop built-in), not the USB camera.
```bash
# ❌ /dev/video0 is usually the integrated webcam
python3 my_app.py --input /dev/video0
```

### Right: Use --input usb for auto-detection
```bash
# ✅ Auto-detects the correct USB camera device
python3 my_app.py --input usb

# ✅ Or identify first, then use specific device
v4l2-ctl --list-devices  # Find the USB camera device path
python3 my_app.py --input /dev/video4
```

## Environment / Driver Checks (Pre-Launch)

### PCIe driver check is unreliable
`lsmod | grep hailo_pci` may return empty even when the device is functional
(e.g., built-in driver, different module name).

**Reliable check**: Use `hailortcli fw-control identify` and **verify output content**,
not just exit code. The CLI can return exit code 0 with empty output when no device
is present (silent false positive).
```bash
output=$(hailortcli fw-control identify 2>&1)
if [[ -z "$output" ]] || ! echo "$output" | grep -q "Device Architecture"; then
    echo "ERROR: No Hailo device detected"
    exit 1
fi
# Expected: "Device Architecture: HAILO10H" + firmware version
```

### Full pre-launch verification sequence
```bash
# 1. Device accessible (verify OUTPUT, not just exit code)
output=$(hailortcli fw-control identify 2>&1)
if [[ -z "$output" ]] || ! echo "$output" | grep -q "Device Architecture"; then
    echo "ERROR: No Hailo device detected"; exit 1
fi

# 2. Python SDK importable
python3 -c "import hailo_platform; print('hailo_platform OK')"

# 3. App framework importable
python3 -c "from hailo_apps.python.core.common.defines import *; print('hailo_apps OK')"

# 4. Input file exists (if file input)
ls -la /path/to/video.mp4
```

---

# GAME (continued)

## Custom Background Apps — Don't Blend Camera Feed

### Wrong: Blending camera feed with background
When the user provides a custom background image (games, virtual scenes), showing
the live camera feed blended with the background produces a confusing semi-transparent
display where the user sees themselves ghost-overlaid on the background.
```python
# ❌ WRONG — user sees camera feed blended with background
output = cv2.addWeighted(self.background, 0.4, frame, 0.6, 0)
```

### Right: Use background only, draw game elements on top
The camera frame should only be used for **data extraction** (pose keypoints,
detections). The rendered output should be a clean copy of the background with
game elements and body markers drawn on top.
```python
# ✅ CORRECT — clean background, no camera feed visible
output = self.background.copy()
# Draw eggs, hand markers, HUD, etc. on output
output = cv2.cvtColor(output, cv2.COLOR_RGB2BGR)
user_data.set_frame(output)
```

## OpenCV Display (GEN-AI)

### Window too small with VLM crop
`Backend.convert_resize_image()` returns 336×336 — too small for a display window.
Always resize to at least 640×640 before `cv2.imshow()`:
```python
display = cv2.resize(frame, (640, 640), interpolation=cv2.INTER_LINEAR)
```

### Overlay text overflows window
VLM responses can be 100+ characters. Never truncate to a fixed width — instead
wrap text into multiple lines and make the overlay banner height dynamic:
```python
banner_h = 35 + 22 * len(wrapped_lines)
```

### End-of-video drops pending inference
If you `break` when `get_frame()` returns `None`, any pending async inference is
lost. The user never sees the result.
**Fix**: Wait for `vlm_future.result()` before breaking, then redraw the overlay
and hold the frame on screen for ~5 seconds.

### NEVER freeze video during inference in monitoring apps
VLM inference takes 10-30 seconds. Freezing the display during analysis makes the
app appear broken and drops most of the video content.
**Fix**: Always keep video playing. Run inference in a background thread via
`ThreadPoolExecutor.submit()`. Show the latest result in the overlay while live
video continues. Freezing is ONLY for interactive capture-and-ask apps (like `vlm_chat`)
where the user explicitly captures a frame.

---

# UNIVERSAL (continued)

## YAML Config Registration — Anchor Alias Placement

### Wrong: Insert alias between a key and its value block
When adding `my_vlm_app: *vlm_chat_app` to `resources_config.yaml`, inserting it
**between** an existing key (e.g. `agent: &agent_app`) and its `models:` block
breaks YAML parsing — the parser sees `models:` as belonging to the new key.
```yaml
# ❌ WRONG — splits `agent` from its `models:` block
agent: &agent_app

my_vlm_app: *vlm_chat_app

  models:          # ← parser thinks this belongs to my_vlm_app, not agent
    hailo10h: ...
```

### Right: Insert alias AFTER the full block
```yaml
# ✅ CORRECT — agent block is complete, then alias follows
agent: &agent_app
  models:
    hailo8:
      default: None
    hailo10h:
      default:
        - name: Qwen2.5-Coder-1.5B-Instruct
          source: gen-ai-mz

my_vlm_app: *vlm_chat_app      # ← safe: goes after the full agent block
```
**Rule**: When inserting a YAML alias entry, always place it **after** the complete
block of the preceding key, not between the key and its child mapping.
Always run `python3 -c "import yaml; yaml.safe_load(open('path'))"` after editing YAML.

## Duplicate `--debug` Flag with get_standalone_parser()

### Wrong: Adding --debug when using get_standalone_parser()
`get_standalone_parser()` already defines `--debug`. Adding it again causes
`argparse.ArgumentError: argument --debug: conflicting option string: --debug`
at startup.
```python
# ❌ Crashes — --debug already exists in base parser
parser = get_standalone_parser()
parser.add_argument("--debug", action="store_true", help="Debug mode")
```

### Right: Use the existing --debug from the base parser
```python
# ✅ --debug is already available via get_standalone_parser()
parser = get_standalone_parser()
# Just use args.debug — no need to add it again
```
**Rule**: Before adding arguments to a parser from `get_standalone_parser()`,
check what the base parser already provides. Common built-in flags: `--debug`,
`--hef-path`, `--arch`, `--list-models`.

## CLI Argument Ordering with handle_list_models_flag

### Wrong: Add custom args AFTER handle_list_models_flag
`handle_list_models_flag()` uses `parse_known_args()` internally, which doesn't
fail — but if `--help` is invoked at that point, argparse only knows the base args.
Custom args added later never appear in `--help` output:
```python
# ❌ --interval won't appear in --help
parser = get_standalone_parser()
handle_list_models_flag(parser, MY_APP)
parser.add_argument("--interval", ...)  # Too late for --help
args = parser.parse_args()
```

### Right: Add ALL custom args BEFORE handle_list_models_flag
```python
# ✅ --interval appears in --help
parser = get_standalone_parser()
parser.add_argument("--interval", type=int, default=15, help="Seconds between analyses")
handle_list_models_flag(parser, MY_APP)  # Now --help shows everything
args = parser.parse_args()
```
**Rule**: All `parser.add_argument()` calls must come **before** `handle_list_models_flag()`.

## VLM MAX_TOKENS Tuning for Monitoring Apps (GEN-AI)

Qwen2-VL with `MAX_TOKENS=300` produces verbose, **repetitive** output (the model
loops the same sentences). For continuous monitoring apps that need concise answers:
- Use `MAX_TOKENS=100` to `150` — enough for 1-2 sentences
- Reinforce brevity in both the system prompt and user prompt:
  `"Be concise — one or two sentences maximum."`
- `MAX_TOKENS=200+` is only appropriate for interactive Q&A or detailed descriptions

## Event Classification — Keyword Ordering Matters (GEN-AI)

Keyword-based classification matches the **first** EventType whose keywords appear
in the response. Generic words like "food" or "floor" can match the wrong category
if checked before more specific ones.
```python
# ❌ "sniffing a bowl on the floor" matches SLEEPING because "lying" check comes first
# ❌ "sitting on the floor" matches EATING because "food" appears in context
```
**Fix**: Order keyword categories from most-specific to least-specific. Put
physical-action keywords (sniffing, running, chewing) before state/posture keywords
(sitting, lying). Also add the activity you care about to the VLM prompt itself:
`"Classify the activity as one of: sleeping, eating, drinking, playing, ..."` —
this constrains the VLM output and makes keyword matching more reliable.

---

# PIPELINE (continued)

## GStreamer Pipeline — Queue and String Pitfalls

### Missing Queue Between Elements
GStreamer needs explicit `queue` elements to create thread boundaries. Without them, everything runs in one thread and performance suffers.

### Wrong Pipeline String Concatenation
```python
# ❌ Missing ! separator or double !!
pipeline = f"{source}{inference}{display}"
pipeline = f"{source} !! {inference}"

# ✅ Single ! with spaces
pipeline = f"{source} ! {inference} ! {display}"
```

## Resource Cleanup Checklist

When building an app, ensure ALL of these are handled:
- [ ] `cv2.VideoCapture.release()` / `picam2.stop()`
- [ ] `cv2.destroyAllWindows()`
- [ ] `backend.close()` (sends sentinel to worker)
- [ ] `vlm.release()` / `llm.release()` (in worker process)
- [ ] `vdevice.release()` (in worker process, after model release)
- [ ] `ThreadPoolExecutor.shutdown(wait=True)` (if used)

## Logging Anti-Patterns

### Wrong: print() for operational messages
```python
print("Starting inference...")  # Lost in output, no timestamp, no level
```

### Right: Logger
```python
logger.info("Starting inference...")
```

### Exception: print() IS correct for:
- Real-time streamed VLM output (user-facing)
- Interactive prompts ("Press Enter to continue")
- Summary reports at end of session

## Agent / Tooling Pitfalls

### python vs python3 on Ubuntu/Debian
On Ubuntu, `python` is NOT installed by default — only `python3` exists.
Always use `python3` in terminal commands, or first verify with `which python`.
The `setup_env.sh` script activates the venv but does NOT alias `python` → `python3`.
```bash
# ❌ Fails on fresh Ubuntu
python -m hailo_apps.python.gen_ai_apps.my_vlm_app.my_vlm_app --help

# ✅ Always works
python3 -m hailo_apps.python.gen_ai_apps.my_vlm_app.my_vlm_app --help
```

### YAML File Edits — Whitespace Sensitivity
When using `replace_string_in_file` on YAML files (e.g., `resources_config.yaml`),
the match MUST be exact including invisible trailing spaces and indentation.
YAML files often have inconsistent spacing between blocks. If the first edit
attempt fails, read the exact lines around the insertion point and retry with
the precise whitespace.
**Tip**: Include 3-5 context lines from the actual `read_file` output, not
from memory or documentation.

### VS Code Auto-Approve for Agentic Workflows
By default, VS Code Copilot agent mode requires clicking "Allow" for every
tool call (file write, terminal command, etc.). A 46-tool-call build means
~46 clicks. To eliminate this:
```json
// .vscode/settings.json
{
    "chat.tools.autoApprove": true
}
```
This makes the agent fully autonomous. Add to `.vscode/settings.json` at the
workspace level (not user level) so it only applies to this repo.

### hailortcli fw-control identify — Silent False Positive
`hailortcli fw-control identify` can return **exit code 0 with no output** on
machines where the CLI is installed but no Hailo device is connected. The
pre-launch check treats exit code 0 as success and proceeds to launch, which
then fails with `HAILO_OUT_OF_PHYSICAL_DEVICES` (error 74).
```bash
# ❌ Exit code alone is not enough
hailortcli fw-control identify
# Returns exit code 0, empty output → check passes → app crashes

# ✅ Verify output content, not just exit code
output=$(hailortcli fw-control identify 2>&1)
if [[ -z "$output" ]] || ! echo "$output" | grep -q "Device Architecture"; then
    echo "ERROR: No Hailo device detected"
    exit 1
fi
```
**Rule**: When checking device availability, always verify that the output
contains `"Device Architecture"` — not just that the command succeeded.

### Agent Skipping Guided Questions (VLM Builder)
The VLM builder agent's Phase 1 specifies a **mandatory guided path**: ask the
user about app style (Monitor / Chat / Logger) and input source (USB / RPi /
Video / RTSP) before presenting the build plan. Even when the user's request
seems specific enough to infer all answers, the agent must still ask guided
questions unless the user explicitly says "just build it" or "use defaults".

**What went wrong**: Agent saw "scene monitoring" + "sample video: video.mp4" and
inferred all choices, skipping straight to the build plan confirmation. This
bypasses the collaborative workflow and misses the chance to catch wrong
assumptions (e.g., maybe the user wanted an interactive chat, not a monitor).

**Rule**: Guided questions are MANDATORY unless the user uses trigger phrases
("just build it", "use defaults", "skip questions"). Inferring from context
is not a valid reason to skip them.

### Background Terminal Does Not Inherit Venv
When using `isBackground=true` (or any mechanism that spawns a new shell),
the virtual environment and `PYTHONPATH` from the foreground terminal are
**not inherited**. The new shell starts fresh.
```bash
# ❌ Foreground terminal has venv active, but background terminal does not
# Terminal 1 (foreground): source setup_env.sh  ← venv active here
# Terminal 2 (background): python3 my_app.py    ← ModuleNotFoundError!

# ✅ Always chain source + run in the same background command
source setup_env.sh && python3 my_app.py --input usb
```
**Rule**: For any background terminal launch, always prepend
`source setup_env.sh &&` before the Python command. Never assume the venv
carries over from another terminal session.

### Template Imports Left Behind After Subclassing
When building an app that **subclasses** an existing pipeline class (e.g.,
`GStreamerPoseEstimationApp`), the SKILL.md template includes imports for the
base `GStreamerApp` pattern (`GStreamerApp`, `handle_list_models_flag`, etc.)
that are no longer needed. Agents copy these imports, then subclass a
domain-specific class instead — leaving the original template imports unused.
```python
# ❌ Template imports not needed when subclassing GStreamerPoseEstimationApp
from hailo_apps.python.core.common.core import handle_list_models_flag  # unused
from hailo_apps.python.core.gstreamer.gstreamer_app import GStreamerApp  # unused

# ✅ Only import what you actually use
from hailo_apps.python.core.gstreamer.gstreamer_app import app_callback_class
from hailo_apps.python.pipeline_apps.pose_estimation.pose_estimation_pipeline import (
    GStreamerPoseEstimationApp,
)
```
**Rule**: After writing a subclassed app, review imports against which symbols
are actually used. Remove anything from the base template that the subclass
renders unnecessary. The validation script catches these (`No unused imports`
check), but cleaning them before validation saves a round trip.
