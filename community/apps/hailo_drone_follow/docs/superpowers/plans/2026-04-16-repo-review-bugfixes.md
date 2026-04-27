# Repo-Wide Review & Bugfix Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all bugs, inconsistencies, dead code, and security issues found during a comprehensive repo review of `hailo-drone-follow`.

**Architecture:** Fixes are grouped by severity and module. Each task is self-contained and independently committable. No behavioral changes — only correctness, consistency, and hygiene.

**Tech Stack:** Python 3.10+, React (JSX), JSON, GStreamer

---

## Findings Summary

| # | Severity | Finding | Location |
|---|----------|---------|----------|
| 1 | **HIGH** | Path traversal in static file handler | `web_server.py:357-370` |
| 2 | **HIGH** | Default value mismatches: `df_params.json` vs `config.py` | 6 params |
| 3 | **HIGH** | UI slider ranges don't match `df_params.json` schema | `App.jsx` 6+ sliders |
| 4 | **MED** | Dead config fields never used anywhere | `config.py:58-59` |
| 5 | **MED** | Orbit params missing from OpenHD bridge | `openhd_bridge.py` |
| 6 | **MED** | `forward_alpha` default 0.1 in `df_params.json`, 0.15 in code | `df_params.json:154` |
| 7 | **MED** | `txrx.key` (OpenHD encryption key) in repo root, not gitignored | repo root |
| 8 | **MED** | `gstshark_*` profiling dirs not gitignored | repo root |
| 9 | **MED** | Deprecated `asyncio.get_event_loop()` in tests (28 uses) | `tests/` |
| 10 | **LOW** | `follow_mode` is `str`, not `FollowMode` enum | `config.py:49` |
| 11 | **LOW** | Private functions exported in `__all__` | `follow_api/__init__.py` |
| 12 | **LOW** | No Content-Length limit on config POST | `web_server.py:320` |
| 13 | **LOW** | CLAUDE.md missing 4 new features | `CLAUDE.md` |
| 14 | **LOW** | `orbit_speed_m_s` missing from `df_params.json` | `df_params.json` |

---

## Files to Modify

| File | Change |
|------|--------|
| `drone_follow/servers/web_server.py` | Fix path traversal, add Content-Length limit |
| `df_params.json` | Reconcile defaults with `config.py`, add `orbit_speed_m_s` |
| `drone_follow/ui/src/App.jsx` | Fix slider min/max/step to match `df_params.json` |
| `drone_follow/follow_api/config.py` | Remove dead fields `search_vel_damp`, `min_search_forward` |
| `drone_follow/servers/openhd_bridge.py` | Add orbit params to `_CONFIG_PARAMS` |
| `.gitignore` | Add `txrx.key`, `gstshark_*/` |
| `drone_follow/tests/test_velocity_api_and_smoother.py` | Replace deprecated asyncio patterns |
| `drone_follow/tests/test_controller.py` | Replace deprecated asyncio patterns |
| `drone_follow/follow_api/__init__.py` | Remove private functions from `__all__` |

---

### Task 1: Fix Path Traversal in Static File Handler

**Files:**
- Modify: `drone_follow/servers/web_server.py:351-378`

- [ ] **Step 1: Read the vulnerable handler**

```bash
PYTHONPATH=. python3 -c "
import os
static_dir = '/tmp/test_static'
os.makedirs(static_dir, exist_ok=True)
# Simulate the vulnerable code
path = '/../../../etc/passwd'.lstrip('/')
file_path = os.path.join(static_dir, path)
print(f'Resolved: {file_path}')
print(f'Escapes: {not file_path.startswith(os.path.normpath(static_dir))}')
"
```
Expected: Demonstrates that `/../../../etc/passwd` escapes `static_dir`.

- [ ] **Step 2: Add path normalization and bounds check**

In `_handle_static()`, after computing `file_path`, add a check that the resolved path stays inside `static_dir`:

```python
def _handle_static(self):
    """Serve React static build with SPA fallback to index.html."""
    if self.static_dir is None or not os.path.isdir(self.static_dir):
        self.send_error(404, "UI not built. Run: cd ui && npm install && npm run build")
        return

    path = self.path.split("?")[0].split("#")[0]  # strip query/fragment
    path = path.lstrip("/")
    if not path:
        path = "index.html"

    file_path = os.path.normpath(os.path.join(self.static_dir, path))
    # Prevent directory traversal
    if not file_path.startswith(os.path.normpath(self.static_dir) + os.sep) and \
       file_path != os.path.normpath(self.static_dir):
        self.send_error(403, "Forbidden")
        return

    if not os.path.isfile(file_path):
        file_path = os.path.join(self.static_dir, "index.html")

    if not os.path.isfile(file_path):
        self.send_error(404, "UI not built. Run: cd ui && npm install && npm run build")
        return

    content_type = self._guess_content_type(file_path)
    with open(file_path, "rb") as f:
        body = f.read()

    self.send_response(200)
    self.send_header("Content-Type", content_type)
    self.send_header("Content-Length", str(len(body)))
    self._cors_headers()
    self.end_headers()
    self.wfile.write(body)
```

- [ ] **Step 3: Add Content-Length limit on config POST**

In `_handle_post_config()`, add a size check at the top:

```python
length = int(self.headers.get("Content-Length", 0))
if length > 65536:  # 64 KB is generous for a config JSON
    self.send_error(413, "Payload too large")
    return
```

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=. pytest drone_follow/tests/ -v -p no:typeguard`
Expected: All tests pass (web_server has no unit tests, but ensure nothing regresses).

- [ ] **Step 5: Commit**

```bash
git add drone_follow/servers/web_server.py
git commit -m "security: fix path traversal in static file handler, add POST size limit

Normalize file paths and verify they stay inside static_dir before serving.
Reject config POST bodies larger than 64 KB."
```

---

### Task 2: Reconcile Default Values Between `df_params.json` and `config.py`

**Files:**
- Modify: `df_params.json`

The source of truth is `config.py` (the Python dataclass). `df_params.json` is the schema
consumed by QOpenHD's ground station UI. Their defaults must match.

**Current mismatches:**

| Parameter | `config.py` | `df_params.json` | Action |
|-----------|-------------|-------------------|--------|
| `yaw_only` | `True` | `false` | Change `df_params.json` → `true` |
| `kp_forward` | `1.5` | `3.0` | Change `df_params.json` → `1.5` |
| `kp_backward` | `2.5` | `5.0` | Change `df_params.json` → `2.5` |
| `max_forward` | `1.0` | `2.0` | Change `df_params.json` → `1.0` |
| `max_backward` | `1.5` | `3.0` | Change `df_params.json` → `1.5` |
| `forward_alpha` | `0.15` | `0.1` | Change `df_params.json` → `0.15` |

- [ ] **Step 1: Update `yaw_only` default**

In `df_params.json`, change the `yaw_only` entry:
```json
{
  "id": "yaw_only",
  ...
  "default": true,
  ...
}
```

- [ ] **Step 2: Update forward/backward gain defaults**

```json
{"id": "kp_forward",  ..., "default": 1.5, ...}
{"id": "kp_backward", ..., "default": 2.5, ...}
```

- [ ] **Step 3: Update forward/backward speed limit defaults**

```json
{"id": "max_forward",  ..., "default": 1.0, ...}
{"id": "max_backward", ..., "default": 1.5, ...}
```

- [ ] **Step 4: Update forward_alpha default**

```json
{"id": "forward_alpha", ..., "default": 0.15, ...}
```

- [ ] **Step 5: Add missing `orbit_speed_m_s` parameter**

Add a new entry in the `"lat"` group (after `smooth_down`):

```json
{
  "id": "orbit_speed_m_s",
  "mavlink_id": "DF_ORBIT_SPD",
  "type": "float",
  "default": 1.0,
  "min": 0.0,
  "max": 3.0,
  "step": 0.1,
  "group": "lat",
  "order": 5,
  "label": "Orbit speed (m/s)",
  "description": "Lateral velocity used when orbit mode is active.",
  "read_only": false
}
```

- [ ] **Step 6: Commit**

```bash
git add df_params.json
git commit -m "fix: reconcile df_params.json defaults with config.py

yaw_only: false→true, kp_forward: 3.0→1.5, kp_backward: 5.0→2.5,
max_forward: 2.0→1.0, max_backward: 3.0→1.5, forward_alpha: 0.1→0.15.
Added orbit_speed_m_s parameter (was in UI but missing from schema)."
```

---

### Task 3: Fix UI Slider Ranges to Match Schema

**Files:**
- Modify: `drone_follow/ui/src/App.jsx`

**Current mismatches:**

| Slider | UI Range | Should Be | Lines |
|--------|----------|-----------|-------|
| `kp_yaw` | max=10 | max=20 | ~548 |
| `kp_forward` | max=10 | max=20 | ~585 |
| `kp_backward` | max=10 | max=20 | ~598 |
| `target_bbox_height` | max=1.0 | max=0.9 | ~386 |
| `yaw_alpha` | min=0.05, step=0.05 | min=0.01, step=0.01 | ~658 |
| `forward_alpha` | min=0.05, step=0.05 | min=0.01, step=0.01 | ~683 |
| `right_alpha` | min=0.05, step=0.05 | min=0.01, step=0.01 | ~708 |
| `down_alpha` | min=0.05, step=0.05 | min=0.01, step=0.01 | ~732 |

- [ ] **Step 1: Fix gain slider maximums**

For `kp_yaw`, `kp_forward`, `kp_backward`: change `max="10"` → `max="20"`.

- [ ] **Step 2: Fix target_bbox_height maximum**

Change `max="1.0"` → `max="0.9"` to prevent setting bbox target to 100% of frame.

- [ ] **Step 3: Fix alpha slider min and step**

For all four alpha sliders (`yaw_alpha`, `forward_alpha`, `right_alpha`, `down_alpha`):
- Change `min="0.05"` → `min="0.01"`
- Change `step="0.05"` → `step="0.01"`

Update the `.toFixed()` display precision from `.toFixed(2)` to `.toFixed(2)` (already correct).

- [ ] **Step 4: Verify in browser**

Run: `cd drone_follow/ui && npm run build`
Start: `PYTHONPATH=. drone-follow --input usb --ui` (or sim equivalent)
Open: `http://localhost:5001`
Verify: sliders reflect new ranges.

- [ ] **Step 5: Commit**

```bash
git add drone_follow/ui/src/App.jsx
git commit -m "fix: align UI slider ranges with df_params.json schema

kp_yaw/forward/backward max 10→20, target_bbox_height max 1.0→0.9,
alpha sliders min 0.05→0.01 step 0.05→0.01."
```

---

### Task 4: Remove Dead Config Fields

**Files:**
- Modify: `drone_follow/follow_api/config.py`

`search_vel_damp` and `min_search_forward` are defined in `ControllerConfig` but never
referenced anywhere in the codebase except their own declaration, `add_args()`, and `from_args()`.
They are remnants of a previous search mode design that was never implemented.

- [ ] **Step 1: Verify fields are unused**

```bash
cd /home/giladn/tappas_apps/repos/hailo-drone-follow
grep -rn 'search_vel_damp\|min_search_forward' --include='*.py' | grep -v config.py | grep -v test
```
Expected: No matches (only config.py references these fields).

- [ ] **Step 2: Remove from dataclass**

Delete these two lines from `ControllerConfig`:
```python
    search_vel_damp: float = 0.3        # dampening factor ...
    min_search_forward: float = 0.2     # minimum forward speed ...
```

- [ ] **Step 3: Remove from `add_args()`**

Delete the `--search-vel-damp` argument registration.
(`min_search_forward` has no CLI arg, so nothing to remove there.)

- [ ] **Step 4: Remove from `from_args()`**

Delete:
```python
search_vel_damp=_arg("search_vel_damp", default=defaults.search_vel_damp),
```

- [ ] **Step 5: Run tests**

Run: `PYTHONPATH=. pytest drone_follow/tests/ -v -p no:typeguard`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add drone_follow/follow_api/config.py
git commit -m "cleanup: remove dead config fields search_vel_damp, min_search_forward

These fields were never referenced outside their own declaration.
Remnants of an unimplemented search-mode dampening feature."
```

---

### Task 5: Add Orbit Params to OpenHD Bridge

**Files:**
- Modify: `drone_follow/servers/openhd_bridge.py`
- Modify: `df_params.json` (if not already done in Task 2)

The web UI exposes `follow_mode`, `orbit_speed_m_s`, and `orbit_direction`, but these
cannot be set from QOpenHD because they're missing from `_CONFIG_PARAMS`.

- [ ] **Step 1: Add orbit params to `_CONFIG_PARAMS`**

Add these entries to the `_CONFIG_PARAMS` dict in `openhd_bridge.py`:

```python
    "orbit_speed_m_s":          ("DF_ORBIT_SPD",  float),
    "orbit_direction":          ("DF_ORBIT_DIR",  int),
```

Note: `follow_mode` is a string ("follow"/"orbit") which doesn't map cleanly to MAVLink
float params. We'll skip it — the bridge can't represent string enums. Orbit is activated
by setting `orbit_speed_m_s > 0` from the ground station instead.

- [ ] **Step 2: Add `orbit_direction` to `df_params.json`**

```json
{
  "id": "orbit_direction",
  "mavlink_id": "DF_ORBIT_DIR",
  "type": "int",
  "default": 1,
  "min": -1,
  "max": 1,
  "step": 2,
  "group": "lat",
  "order": 6,
  "label": "Orbit direction",
  "description": "+1 = clockwise, -1 = counter-clockwise. Only active in orbit mode.",
  "read_only": false
}
```

- [ ] **Step 3: Run tests**

Run: `PYTHONPATH=. pytest drone_follow/tests/ -v -p no:typeguard`
Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add drone_follow/servers/openhd_bridge.py df_params.json
git commit -m "bridge: add orbit_speed_m_s and orbit_direction to OpenHD params

These were exposed in the web UI but missing from the QOpenHD bridge,
preventing ground station tuning of orbit mode."
```

---

### Task 6: Add `.gitignore` Entries for Credentials and Profiling

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Add entries**

Append to `.gitignore`:
```
# OpenHD encryption key — never commit credentials
txrx.key

# GStreamer Shark profiling output
gstshark_*/
```

- [ ] **Step 2: Commit**

```bash
git add .gitignore
git commit -m "gitignore: add txrx.key (credential) and gstshark_*/ (profiling)"
```

---

### Task 7: Replace Deprecated `asyncio.get_event_loop()` in Tests

**Files:**
- Modify: `drone_follow/tests/test_velocity_api_and_smoother.py`
- Modify: `drone_follow/tests/test_controller.py`

`asyncio.get_event_loop()` is deprecated since Python 3.10 and will emit
`DeprecationWarning` in 3.12+. Replace with `asyncio.run()`.

- [ ] **Step 1: Replace in `test_velocity_api_and_smoother.py`**

Pattern: replace all instances of:
```python
loop = asyncio.get_event_loop()
r = loop.run_until_complete(api.send(cmd))
```
with:
```python
r = asyncio.run(api.send(cmd))
```

For fixtures and multi-call test methods, use a shared loop:
```python
async def _run():
    r1 = await api.send(step)
    r2 = await api.send(step)
    return r1, r2

r1, r2 = asyncio.run(_run())
```

- [ ] **Step 2: Replace in `test_controller.py`**

Same pattern — find the 2 instances in `TestForwardLowPass` and replace.

- [ ] **Step 3: Run tests**

Run: `PYTHONPATH=. pytest drone_follow/tests/ -v -p no:typeguard`
Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add drone_follow/tests/
git commit -m "tests: replace deprecated asyncio.get_event_loop() with asyncio.run()

28 instances replaced. Prevents DeprecationWarning on Python 3.12+
and breakage on Python 3.13+."
```

---

### Task 8: Clean Up `__all__` Exports

**Files:**
- Modify: `drone_follow/follow_api/__init__.py`

Private functions (`_calculate_forward_speed`, `_calculate_altitude_speed`) are exported
in `__all__`. They're only used by tests importing them directly from the module, which
works without `__all__`.

- [ ] **Step 1: Remove private functions from `__all__`**

```python
__all__ = [
    "Detection",
    "FollowMode",
    "VelocityCommand",
    "ControllerConfig",
    "SharedDetectionState",
    "FollowTargetState",
    "compute_velocity_command",
]
```

- [ ] **Step 2: Verify test imports still work**

Run: `PYTHONPATH=. pytest drone_follow/tests/test_controller.py -v -p no:typeguard`
Expected: Tests import `_calculate_forward_speed` directly from `controller` module, not via `__all__`, so they still work.

- [ ] **Step 3: Commit**

```bash
git add drone_follow/follow_api/__init__.py
git commit -m "cleanup: remove private functions from __all__ exports

_calculate_forward_speed and _calculate_altitude_speed are internal
helpers — tests import them directly from the controller module."
```

---

## Not Fixed (Intentional / Low Priority)

These were reviewed and deemed acceptable:

| Finding | Reason to skip |
|---------|---------------|
| `follow_mode` is `str` not enum | Would require cascading changes to bridge/UI for a 2-value field; risk exceeds benefit |
| 5 config fields missing CLI args (`yaw_alpha`, `smooth_yaw`, `target_altitude`, `max_orbit_speed`) | Intentionally hidden — tunable via JSON config or web UI, not needed on CLI |
| 13 config fields not in web UI or bridge (search, safety, FOV, loop Hz) | Intentionally internal — runtime or safety params not suitable for live tuning |
| Thread-safety on config mutations | Python GIL provides atomic float/bool reads; adding locks would complicate code for no practical gain at 10 Hz |
| Bridge listener doesn't auto-recover on socket error | Rare edge case; manual restart is acceptable for a research drone |
| CLAUDE.md missing 4 new features | Informational only — not a code bug. Can be updated separately |
| Test coverage gaps (pipeline, MAVSDK, web server) | These require hardware/GStreamer mocking infrastructure that doesn't exist yet |

---

## Verification

After all tasks are complete:

1. **Tests pass:** `PYTHONPATH=. pytest drone_follow/tests/ -v -p no:typeguard` — all green
2. **No deprecated warnings:** `PYTHONPATH=. python3 -W error::DeprecationWarning -m pytest drone_follow/tests/ -p no:typeguard` — no asyncio warnings
3. **UI builds:** `cd drone_follow/ui && npm run build`
4. **App starts:** `PYTHONPATH=. drone-follow --help` — no import errors
5. **df_params.json valid:** `python3 -c "import json; json.load(open('df_params.json'))"`
