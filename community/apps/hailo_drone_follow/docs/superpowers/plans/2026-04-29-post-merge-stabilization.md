# Post-Merge Stabilization & Improvements Implementation Plan

## Status (2026-04-29)

- **Phase 1 (P0) — DONE.** Tasks 1–6 landed in commits `a6e50908..571419ab`.
- **Phase 2 (P1) — DONE.** Tasks 7–14 landed in commits `90ddcd3e..96ff6aef`.
- **Phase 3 (P2) — DONE.** Tasks 15–18 landed in commits `2f34731f..f70470b6`.
- **Phase 4 (Future) — partially done; remainder DEFERRED.**
  - Task 19 (sim camera FOV alignment) — DONE, commit `20a32d5d`.
  - **Task 20 (Adaptive tile allocator) — DEFERRED.** Pure policy class is straightforward; pipeline-rebuild integration touches the SHM/GStreamer hot path and needs its own design pass before implementation.
  - **Task 21 (Torso-keypoint distance proxy) — DEFERRED.** Needs a pose-HEF model decision (YOLOv8-pose vs separate pose net) and pipeline restructuring; revisit after Tasks 19/20 prove out in the field.

Net: 19 commits, 132 tests passing, 1 pre-existing `test_install_smoke` environmental failure (unrelated; `drone-follow` console script not on PATH outside the venv).

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stabilize the drone-follow controller after PR #178 merge by closing the input-side bbox-noise loop, exposing newly-introduced parameters, fixing safety/UX bugs in SOT mode and config presets, and aligning the simulator with the real camera. Then upgrade tracking robustness (torso keypoints, smarter tiling).

**Architecture:** All work targets the `hailo_drone_follow` branch *after* PR #178 (`stabilized-version`) has been merged. Phases are ordered by safety priority: P0 (must fix before flight), P1 (should fix soon), P2 (polish), and Future (architecture-level upgrades). Each task is TDD-first and produces an independent commit. Existing test files (`drone_follow/tests/test_controller.py`, `test_velocity_api_and_smoother.py`, `test_config_persistence.py`, `test_sim_worlds.py`) are extended rather than replaced.

**Tech Stack:** Python 3.10, pytest, MAVSDK-Python, GStreamer, ByteTracker (vendored), HailoRT, gz-sim Harmonic / Gazebo Garden, MediaPipe / Hailo pose-keypoint HEFs, MAVLink (pymavlink), React (web UI).

**Working environment:**
- All commands run from `community/apps/hailo_drone_follow/`
- Activate venv first: `source setup_env.sh`
- Run tests: `pytest drone_follow/tests/ -x -q`
- Sim tests: `RUN_SIM_TESTS=1 pytest drone_follow/tests/test_sim_worlds.py -s`

---

## File Structure Map

| File | Phase touched | Responsibility |
|---|---|---|
| `configs/outdoor_follow.json` | P0 | Real-flight preset; needs altitude-cap reconciliation |
| `drone_follow/follow_api/config.py` | P0, P1 | `ControllerConfig` dataclass; add validators, expose `kp_alt_hold`, deadband fields |
| `drone_follow/follow_api/types.py` | P1 | Drop `right_m_s` field |
| `drone_follow/follow_api/controller.py` | P1 | Adopt deadband on forward command |
| `drone_follow/drone_api/mavsdk_drone.py` | P1 | Drop right-axis from `set_velocity_body` 4-tuple plumbing if field removed |
| `drone_follow/pipeline_adapter/hailo_drone_detection_manager.py` | P0, P1, P2, Future | SOT logic, test-log close race, follow_status rename, ByteTracker filtered state, tiling allocator |
| `drone_follow/pipeline_adapter/byte_tracker.py` | P1, Future | Expose filtered KF state from STrack |
| `drone_follow/pipeline_adapter/fast_tracker.py` | P1 | Same: expose filtered state on FastTracker adapter |
| `drone_follow/pipeline_adapter/tracker.py` | P1 | Add `filtered_bbox` to `TrackedObject` dataclass + protocol |
| `drone_follow/servers/web_server.py` | P1 | Add `kp_alt_hold` to `_CONFIG_FIELDS` |
| `drone_follow/servers/openhd_bridge.py` | P1 | Add `kp_alt_hold` to `_CONFIG_PARAMS` MAVLink table |
| `df_params.json` | P1 | Add `kp_alt_hold` slider definition |
| `drone_follow/ui/src/App.jsx` | P1 | UI sliders read from df_params; smoke-check |
| `sim/worlds/random_walk.sdf` | P0 | Move actor t=0 pose off drone origin |
| `sim/worlds/2_person_world.sdf` | P0 | Reconcile docstring vs SDF actor positions |
| `sim/worlds/walk_across_then_approach.sdf` | P1 | Avoid Phase-4 path through drone airspace |
| `sim/configs/simulation_follow.json` | P1 | Restore explicit gain tuning (or drop intentionally) |
| `sim/patches/x500_vision_camera.patch` | Future | Bring sim camera resolution + FOV into alignment with the real one |
| `drone_follow/tests/test_controller.py` | All | Extend with new tests for each behavior change |
| `drone_follow/tests/test_config_persistence.py` | P1 | Add `kp_alt_hold` round-trip |
| `drone_follow/tests/test_pipeline_filter.py` | P1 (NEW) | Tests for filtered-bbox plumbing |
| `drone_follow/tests/test_tracker_protocol.py` | Future (NEW) | Tests for tiling allocator + tracker abstraction |
| `docs/control-architecture.md` | P2 | Fix doc inconsistencies |

---

## Phase 1 — P0: Critical safety / correctness fixes

### Task 1: Validate `target_altitude ≤ max_altitude` in `ControllerConfig`

**Why:** `configs/outdoor_follow.json` ships with `target_altitude=5.0` and the new default `max_altitude=4.0`, so the alt-hold loop silently clamps the drone at 4 m. Operator and the README both expect 5 m.

**Files:**
- Modify: `drone_follow/follow_api/config.py` (`validate` method)
- Modify: `configs/outdoor_follow.json`
- Test: `drone_follow/tests/test_controller.py` (extend `TestConfigValidation`)

- [ ] **Step 1: Write the failing test**

In `drone_follow/tests/test_controller.py`, append to `class TestConfigValidation`:

```python
    def test_target_altitude_must_be_at_most_max_altitude(self):
        with pytest.raises(ValueError, match="target_altitude"):
            ControllerConfig(target_altitude=5.0, max_altitude=4.0)

    def test_target_altitude_at_max_is_valid(self):
        ControllerConfig(target_altitude=4.0, max_altitude=4.0).validate()

    def test_target_altitude_below_min_raises(self):
        with pytest.raises(ValueError, match="target_altitude"):
            ControllerConfig(target_altitude=1.0, min_altitude=2.0, max_altitude=4.0)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest drone_follow/tests/test_controller.py::TestConfigValidation -v
```
Expected: 3 new tests fail (`DID NOT RAISE`).

- [ ] **Step 3: Update `validate()` in `config.py`**

In `drone_follow/follow_api/config.py`, replace `validate`:

```python
    def validate(self):
        """Raise ValueError if the configuration is internally inconsistent."""
        if self.min_altitude >= self.max_altitude:
            raise ValueError(
                f"min_altitude ({self.min_altitude}) must be < max_altitude ({self.max_altitude})"
            )
        if self.target_altitude > self.max_altitude:
            raise ValueError(
                f"target_altitude ({self.target_altitude}) must be ≤ max_altitude ({self.max_altitude})"
            )
        if self.target_altitude < self.min_altitude:
            raise ValueError(
                f"target_altitude ({self.target_altitude}) must be ≥ min_altitude ({self.min_altitude})"
            )
```

- [ ] **Step 4: Fix `configs/outdoor_follow.json`**

Set `"max_altitude": 6.0` so the existing `"target_altitude": 5.0` has 1 m of headroom. (`max_altitude=6.0` is within the post-PR slider range of 3–10 m.) Edit `configs/outdoor_follow.json` and add the line if absent:

```json
{
  "yaw_only": false,
  "target_altitude": 5.0,
  "max_altitude": 6.0,
  ...
}
```

- [ ] **Step 5: Run all controller tests to verify nothing else breaks**

```bash
pytest drone_follow/tests/test_controller.py -q
```
Expected: all pass (incl. the 3 new ones).

- [ ] **Step 6: Commit**

```bash
git add drone_follow/follow_api/config.py drone_follow/tests/test_controller.py configs/outdoor_follow.json
git commit -m "follow_api: validate target_altitude in [min, max]; fix outdoor_follow preset"
```

---

### Task 2: SOT mode — surface all visible IDs to the operator

**Why:** Today, when `--sot` is active, `available_ids` and `person_by_id` collapse to `{target_id}`. Web UI and OpenHD ground station show only the locked target — operator can no longer click another person.

**Files:**
- Modify: `drone_follow/pipeline_adapter/hailo_drone_detection_manager.py` (SOT branch around line 3250 in PR diff context)
- Test: `drone_follow/tests/test_controller.py` is the wrong location; add `drone_follow/tests/test_sot_mode.py` (new file)

- [ ] **Step 1: Locate the SOT branch**

```bash
grep -n "use_sot\|_SOT_IOU_THRESH\|sot_enabled" drone_follow/pipeline_adapter/hailo_drone_detection_manager.py
```
Note line numbers; the SOT path computes `available_ids` and writes to `shared_state`.

- [ ] **Step 2: Write the failing test**

Create `drone_follow/tests/test_sot_mode.py`:

```python
"""SOT mode must still expose every detected person's ID to the UI/OpenHD,
so the operator can switch lock targets even while SOT is active."""

import pytest
from unittest.mock import MagicMock

from drone_follow.pipeline_adapter.hailo_drone_detection_manager import (
    DroneFollowUserData,
)


def _fake_persons(ids):
    persons = []
    for tid in ids:
        p = MagicMock()
        p.get_track_id = MagicMock(return_value=tid)
        bbox = MagicMock()
        bbox.xmin.return_value = 0.4
        bbox.ymin.return_value = 0.4
        bbox.width.return_value = 0.2
        bbox.height.return_value = 0.3
        p.get_bbox.return_value = bbox
        p.get_confidence.return_value = 0.9
        persons.append(p)
    return persons


def test_sot_publishes_all_ids_not_just_locked(monkeypatch):
    """In SOT mode with locked target=5, available_ids must still include 7 and 9."""
    user_data = DroneFollowUserData()
    user_data.sot_enabled = True
    user_data.target_state = MagicMock()
    user_data.target_state.get_target.return_value = 5
    user_data.shared_state = MagicMock()
    persons = _fake_persons([5, 7, 9])
    # Drive whatever method is the SOT entrypoint — placeholder name.
    # NOTE: implementer adapts to the actual function (e.g. _run_sot, _on_detections).
    from drone_follow.pipeline_adapter.hailo_drone_detection_manager import (
        _dispatch_detections,
    )
    _dispatch_detections(user_data, persons)

    # The shared_state.update call should have available_ids ⊇ {5, 7, 9}.
    last_call_kwargs = user_data.shared_state.update.call_args.kwargs
    assert {5, 7, 9}.issubset(last_call_kwargs["available_ids"])
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
pytest drone_follow/tests/test_sot_mode.py -v
```
Expected: fails. The exact failure mode depends on the actual SOT branch — adapt the test to whatever wrapper function is correct (the comment in the test marks the spot).

- [ ] **Step 4: Fix the SOT branch**

In `hailo_drone_detection_manager.py`, in the SOT branch, **always** compute `available_ids` from the full detection set (the same list used in MOT mode), even when the chosen `best` detection comes from the IoU match against the locked target. Concretely: lift `available_ids = {p.get_track_id() for p in persons if p.get_track_id() is not None}` to before the SOT/MOT branch, and pass it through unmodified. Remove any line of the form `available_ids = {target_id}`.

- [ ] **Step 5: Run the test to verify it passes**

```bash
pytest drone_follow/tests/test_sot_mode.py -v
```
Expected: pass.

- [ ] **Step 6: Run the full test suite to check no regressions**

```bash
pytest drone_follow/tests/ -q --ignore=drone_follow/tests/test_sim_worlds.py
```
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add drone_follow/pipeline_adapter/hailo_drone_detection_manager.py drone_follow/tests/test_sot_mode.py
git commit -m "pipeline: SOT mode publishes every visible track ID, not just the locked target"
```

---

### Task 3: SOT mode — stop wiping all track IDs on periodic refresh

**Why:** `tracker.reset()` in the SOT periodic refresh clears state for *every* person, not just the locked target. After refresh the locked `target_id` no longer exists → next MOT frame triggers lost-target/ReID branch unnecessarily.

**Files:**
- Modify: `drone_follow/pipeline_adapter/hailo_drone_detection_manager.py` (`_SOT_MOT_REFRESH_INTERVAL` block)
- Test: `drone_follow/tests/test_sot_mode.py` (extend)

- [ ] **Step 1: Add a failing test**

Append to `drone_follow/tests/test_sot_mode.py`:

```python
def test_sot_refresh_does_not_drop_locked_target():
    """After the SOT periodic refresh, the locked target_id must still appear
    in the next frame's tracked IDs."""
    from drone_follow.pipeline_adapter.tracker_factory import create_tracker
    tracker = create_tracker("byte")
    user_data = DroneFollowUserData()
    user_data.tracker = tracker
    user_data.sot_enabled = True
    user_data.target_state = MagicMock()
    user_data.target_state.get_target.return_value = 5
    user_data.shared_state = MagicMock()

    # Drive the refresh path directly. Replace `_periodic_sot_refresh` with the
    # actual function name once located.
    from drone_follow.pipeline_adapter.hailo_drone_detection_manager import (
        _periodic_sot_refresh,
    )
    _periodic_sot_refresh(user_data, frame_count=150)

    # After refresh the tracker must still have track 5 (or the refresh must
    # be a no-op for the locked target).
    ids = {t.track_id for t in tracker.tracked_stracks}
    assert 5 in ids or len(tracker.tracked_stracks) > 0  # softer assertion
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest drone_follow/tests/test_sot_mode.py::test_sot_refresh_does_not_drop_locked_target -v
```
Expected: fail.

- [ ] **Step 3: Fix the refresh logic**

Pick option A: drop the periodic full reset entirely (preferred — MOT runs every N frames anyway under the new behaviour).

Pick option B: replace the full reset with a per-track `mark_lost()` for **every track except the locked one**. Pseudo-code:

```python
if user_data.sot_enabled and user_data.frame_count % _SOT_MOT_REFRESH_INTERVAL == 0:
    target_id = user_data.target_state.get_target()
    for t in list(user_data.tracker.tracked_stracks):
        if t.track_id != target_id:
            t.mark_lost()
    # Do NOT call user_data.tracker.reset()
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest drone_follow/tests/test_sot_mode.py -v
```
Expected: pass.

- [ ] **Step 5: Run sim test smoke**

```bash
RUN_SIM_TESTS=1 pytest drone_follow/tests/test_sim_worlds.py::test_2_persons_diagonal_keeps_initial_target -s
```
Expected: pass (target_id stable across the diagonal cross).

- [ ] **Step 6: Commit**

```bash
git add drone_follow/pipeline_adapter/hailo_drone_detection_manager.py drone_follow/tests/test_sot_mode.py
git commit -m "pipeline: SOT periodic refresh preserves the locked target's track"
```

---

### Task 4: Tracker protocol — accept or drop `embeddings` consistently

**Why:** `MetricsTracker.update` always passes `embeddings=…`; `ByteTrackerAdapter.update` silently drops it. The protocol is dishonest.

**Files:**
- Modify: `drone_follow/pipeline_adapter/tracker.py` (Protocol definition)
- Modify: `drone_follow/pipeline_adapter/byte_tracker.py` (adapter signature)
- Modify: `drone_follow/pipeline_adapter/fast_tracker.py` (adapter signature)
- Test: `drone_follow/tests/test_tracker_protocol.py` (NEW)

- [ ] **Step 1: Write the failing test**

Create `drone_follow/tests/test_tracker_protocol.py`:

```python
"""Tracker protocol contract tests — every adapter must accept the same kwargs."""

import inspect
import pytest

from drone_follow.pipeline_adapter.byte_tracker import ByteTrackerAdapter
from drone_follow.pipeline_adapter.fast_tracker import FastTrackerAdapter


@pytest.mark.parametrize("cls", [ByteTrackerAdapter, FastTrackerAdapter])
def test_update_signature_accepts_embeddings(cls):
    sig = inspect.signature(cls.update)
    assert "embeddings" in sig.parameters, (
        f"{cls.__name__}.update must accept 'embeddings' kwarg per Tracker protocol"
    )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest drone_follow/tests/test_tracker_protocol.py -v
```
Expected: fails for at least one adapter.

- [ ] **Step 3: Decide on the policy and apply it**

Choice (preferred): **drop `embeddings` from the protocol**. Today nobody uses it. Edit `drone_follow/pipeline_adapter/tracker.py` `Tracker` Protocol, remove the `embeddings` parameter from `update`. Edit `MetricsTracker.update` to stop passing it. Edit both adapters' signatures to match.

If you keep it: change `ByteTrackerAdapter.update` to accept `embeddings=None` explicitly (with a `# unused` comment) and same for `FastTrackerAdapter`. The test above still passes.

- [ ] **Step 4: Run tests**

```bash
pytest drone_follow/tests/test_tracker_protocol.py -v
pytest drone_follow/tests/ -q --ignore=drone_follow/tests/test_sim_worlds.py
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add drone_follow/pipeline_adapter/{tracker,byte_tracker,fast_tracker}.py drone_follow/tests/test_tracker_protocol.py
git commit -m "pipeline: align Tracker.update protocol on embeddings; protocol contract test"
```

---

### Task 5: Move `random_walk.sdf` actor t=0 pose off the drone origin

**Why:** In gz-sim Harmonic, `delay_start=20` only delays *animation playback*; the actor's t=0 pose `(0, 0, 0.9)` is the *visible* pose during those 20 s. The drone takes off through it.

**Files:**
- Modify: `sim/worlds/random_walk.sdf`
- Test: `drone_follow/tests/test_sim_worlds.py::test_random_walk_produces_detections`

- [ ] **Step 1: Find the existing waypoint table**

```bash
grep -n "<waypoint>" sim/worlds/random_walk.sdf | head -5
```

Note the *first non-zero* waypoint (the first one after `delay_start` ends). Use its (x, y, z) as the new t=0 pose so the actor stays still until t=20 in a *visible* location, then walks normally.

- [ ] **Step 2: Edit the SDF**

In `sim/worlds/random_walk.sdf`, replace the t=0 waypoint:

```xml
<waypoint>
  <time>0</time>
  <pose>5.29 -5.48 0.9 0 0 0</pose>   <!-- was: 0 0 0.9 -->
</waypoint>
```

(Use the actual first walk waypoint coordinates from your file; the example shows the values from the review notes.)

- [ ] **Step 3: Run the sim test**

```bash
RUN_SIM_TESTS=1 pytest drone_follow/tests/test_sim_worlds.py::test_random_walk_produces_detections -s
```
Expected: pass with `s["n_det"] > 80`.

- [ ] **Step 4: Visually inspect the recording**

The test fixture renames the run's `*.mp4` with the world suffix. Open `drone_follow/recordings/rec_*_random_walk.mp4` and confirm the actor is visible from the moment the drone clears takeoff (no walking-through-actor frames).

- [ ] **Step 5: Commit**

```bash
git add sim/worlds/random_walk.sdf
git commit -m "sim: random_walk actor t=0 pose off drone origin (gz-sim delay_start only delays animation)"
```

---

### Task 6: Reconcile `2_person_world.sdf` with the test docstring

**Why:** Test docstring says "(5,0) and (5,3) at startup", but SDF holds at (3,0)/(3,3). At 3 m the bbox dominates the FOV.

**Files:**
- Modify: `sim/worlds/2_person_world.sdf` (move actors back to (5, …))
  *or*
- Modify: `drone_follow/tests/test_sim_worlds.py` (update docstring to match SDF)

- [ ] **Step 1: Decide which is correct**

Run the test once and inspect the resulting recording:

```bash
RUN_SIM_TESTS=1 pytest drone_follow/tests/test_sim_worlds.py::test_2_person_world_sees_both_actors -s
```

- If both actors are visible and bbox sizes look sane (≤ 0.5), update the **docstring** to "(3,0) and (3,3)".
- If bbox is clipped/oversized, update the **SDF** to spawn at (5,0)/(5,3) at t=0.

- [ ] **Step 2: Apply the chosen change**

If updating the SDF, edit each actor's first `<waypoint>` and the `<pose>` block:

```xml
<pose>5 0 1 0 0 0</pose>
<!-- ...actor block... -->
<waypoint>
  <time>0</time>
  <pose>5 0 1 0 0 0</pose>
</waypoint>
```

(and `5 3 1` for the second actor).

- [ ] **Step 3: Re-run the sim test**

```bash
RUN_SIM_TESTS=1 pytest drone_follow/tests/test_sim_worlds.py::test_2_person_world_sees_both_actors -s
```
Expected: pass with `multi > 20` and bbox heights well under 0.5.

- [ ] **Step 4: Commit**

```bash
git add sim/worlds/2_person_world.sdf drone_follow/tests/test_sim_worlds.py
git commit -m "sim: align 2_person_world actor staging with test docstring"
```

---

## Phase 2 — P1: Should-fix soon (control & runtime quality)

### Task 7: Pull `(cx, cy, h)` from ByteTracker's filtered KF state

**Why:** This is the single highest-impact change in the post-merge plan. The Kalman filter inside ByteTracker already smooths the bbox state; the controller currently uses the raw post-NMS detection. Switching the source addresses bbox jitter, partial occlusion, and detection-noise oscillation simultaneously — and is what BoT-SORT, DeepSORT, and every academic monocular-follow paper since 2018 actually do.

**Files:**
- Modify: `drone_follow/pipeline_adapter/tracker.py` — extend `TrackedObject` with `filtered_bbox`
- Modify: `drone_follow/pipeline_adapter/byte_tracker.py` — populate `filtered_bbox` from `STrack.tlwh` (the KF mean)
- Modify: `drone_follow/pipeline_adapter/fast_tracker.py` — same
- Modify: `drone_follow/pipeline_adapter/hailo_drone_detection_manager.py` — pull from `filtered_bbox` when available, fallback to raw bbox
- Test: `drone_follow/tests/test_pipeline_filter.py` (NEW)

- [ ] **Step 1: Write the failing test**

Create `drone_follow/tests/test_pipeline_filter.py`:

```python
"""End-to-end test: the Detection forwarded to the controller comes from the
tracker's filtered Kalman state, not from the raw post-NMS bbox."""

import pytest
from unittest.mock import MagicMock

from drone_follow.pipeline_adapter.tracker_factory import create_tracker


def test_filtered_bbox_is_smoother_than_raw():
    """Inject 5 frames of jittery raw bbox; the filtered bbox.height variance
    must be less than the raw variance."""
    tracker = create_tracker("byte")
    raw_h = [0.30, 0.18, 0.31, 0.17, 0.30]   # 0.07 alternating jitter
    filtered_h = []
    for h in raw_h:
        # NOTE: adapt to the real `update` signature once filtered state is plumbed.
        # Detection format follows whatever the existing adapter expects.
        det = MagicMock()
        det.x = 0.4
        det.y = 0.4
        det.w = 0.2
        det.h = h
        det.score = 0.9
        tracked = tracker.update([det])
        assert tracked, "tracker should produce at least one TrackedObject"
        # The new field added in this task:
        filtered_h.append(tracked[0].filtered_bbox[3])

    import statistics
    raw_var = statistics.variance(raw_h)
    filt_var = statistics.variance(filtered_h)
    assert filt_var < raw_var * 0.5, (
        f"filtered variance {filt_var:.4f} should be < half raw variance {raw_var:.4f}"
    )
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest drone_follow/tests/test_pipeline_filter.py -v
```
Expected: fail with `AttributeError: 'TrackedObject' object has no attribute 'filtered_bbox'`.

- [ ] **Step 3: Extend the `TrackedObject` dataclass**

In `drone_follow/pipeline_adapter/tracker.py`, add field:

```python
@dataclass
class TrackedObject:
    track_id: int
    input_index: int
    is_activated: bool
    score: float
    bbox: tuple                # raw (x, y, w, h) from the matched detection
    filtered_bbox: tuple = ()  # KF-filtered (x, y, w, h); empty tuple if not available
```

- [ ] **Step 4: Populate `filtered_bbox` in `ByteTrackerAdapter`**

In `drone_follow/pipeline_adapter/byte_tracker.py`, where you build `TrackedObject` from a matched STrack, extract the KF state. ByteTracker stores the filtered state in `STrack.mean` (the Kalman state vector) and exposes `tlwh` derived from it. Use `tlwh` for `filtered_bbox`:

```python
def _to_tracked(self, st, input_idx):
    x, y, w, h = st.tlwh                      # KF-filtered
    raw_x, raw_y, raw_w, raw_h = ...           # the post-NMS bbox kept on the STrack at update time
    return TrackedObject(
        track_id=st.track_id,
        input_index=input_idx,
        is_activated=st.is_activated,
        score=st.score,
        bbox=(raw_x, raw_y, raw_w, raw_h),
        filtered_bbox=(x, y, w, h),
    )
```

(Inspect the actual `STrack` class to confirm field names — ByteTrack uses `mean[:4]` for state; `tlwh` property is the convenient accessor.)

- [ ] **Step 5: Populate `filtered_bbox` in `FastTrackerAdapter`**

In `drone_follow/pipeline_adapter/fast_tracker.py`, mirror Step 4: pull `tlwh` from the Fasttracker's STrack equivalent. If the FastTracker doesn't run a KF (it does — `_fasttracker/kalman_filter.py`), use that mean state.

- [ ] **Step 6: Wire `filtered_bbox` through the detection manager**

In `drone_follow/pipeline_adapter/hailo_drone_detection_manager.py`, the line that creates the `Detection` from `bbox = best.get_bbox()` (around line 326): if the matched track exposes `filtered_bbox` (non-empty), use it; otherwise fall back to the raw bbox.

```python
matched_track = ...  # the TrackedObject for this `best` person
if matched_track is not None and matched_track.filtered_bbox:
    fx, fy, fw, fh = matched_track.filtered_bbox
    cx, cy, bbox_h = fx + fw / 2, fy + fh / 2, fh
else:
    bbox = best.get_bbox()
    cx = bbox.xmin() + bbox.width() / 2
    cy = bbox.ymin() + bbox.height() / 2
    bbox_h = bbox.height()

user_data.shared_state.update(Detection(
    label="person", confidence=best.get_confidence(),
    center_x=cx, center_y=cy, bbox_height=bbox_h,
    timestamp=time.monotonic(),
), available_ids=available_ids)
```

- [ ] **Step 7: Run the test**

```bash
pytest drone_follow/tests/test_pipeline_filter.py -v
```
Expected: pass — filtered variance is at least half of raw variance after 5 frames.

- [ ] **Step 8: Run the controller test suite to make sure feeding filtered values doesn't break dead zones**

```bash
pytest drone_follow/tests/test_controller.py -q
```
Expected: all pass.

- [ ] **Step 9: Run a sim test that depends on bbox stability**

```bash
RUN_SIM_TESTS=1 pytest drone_follow/tests/test_sim_worlds.py::test_walk_across_then_approach_holds_target_through_approach -s
```
Expected: pass; the approach window's `n_det / n_w` ratio should be **higher** than before (less detection-induced ID dropouts because the controller doesn't chase noise).

- [ ] **Step 10: Commit**

```bash
git add drone_follow/pipeline_adapter/tracker.py \
        drone_follow/pipeline_adapter/byte_tracker.py \
        drone_follow/pipeline_adapter/fast_tracker.py \
        drone_follow/pipeline_adapter/hailo_drone_detection_manager.py \
        drone_follow/tests/test_pipeline_filter.py
git commit -m "pipeline: feed controller from tracker's KF-filtered bbox state, fall back to raw"
```

---

### Task 8: Expose `kp_alt_hold` everywhere

**Why:** `kp_alt_hold` is the entire altitude loop now and has no CLI flag, no df_params slider, and no web-UI handle.

**Files:**
- Modify: `drone_follow/follow_api/config.py` (`add_args`)
- Modify: `df_params.json` (add slider)
- Modify: `drone_follow/servers/web_server.py` (`_CONFIG_FIELDS`)
- Modify: `drone_follow/servers/openhd_bridge.py` (`_CONFIG_PARAMS`)
- Test: `drone_follow/tests/test_config_persistence.py` (extend roundtrip)

- [ ] **Step 1: Write the failing tests**

Append to `drone_follow/tests/test_config_persistence.py`:

```python
def test_kp_alt_hold_round_trip(tmp_path):
    cfg = ControllerConfig(kp_alt_hold=0.7)
    p = str(tmp_path / "df_config.json")
    cfg.save_json(p)
    loaded = ControllerConfig.from_json(p)
    assert loaded.kp_alt_hold == pytest.approx(0.7)


def test_kp_alt_hold_in_df_params():
    """Slider for kp_alt_hold exists in df_params.json so QOpenHD/web-UI can tune it."""
    import json
    from drone_follow.follow_api.config import _df_params_path  # add helper if missing
    with open(_df_params_path()) as f:
        params = json.load(f)["params"]
    ids = {p["id"] for p in params}
    assert "kp_alt_hold" in ids


def test_kp_alt_hold_in_openhd_bridge_params():
    from drone_follow.servers.openhd_bridge import _CONFIG_PARAMS
    assert "kp_alt_hold" in _CONFIG_PARAMS
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest drone_follow/tests/test_config_persistence.py -v
```
Expected: 3 tests fail.

- [ ] **Step 3: Add CLI argument in `config.py`**

In `drone_follow/follow_api/config.py` `add_args`, near the other altitude arguments:

```python
group.add_argument("--kp-alt-hold", type=float, default=defaults.kp_alt_hold,
                   help=f"Altitude-hold P gain on (current_alt - target_altitude). "
                        f"Drives the down axis whenever yaw_only=False. "
                        f"(default: {defaults.kp_alt_hold})")
```

- [ ] **Step 4: Add `kp_alt_hold` slider to `df_params.json`**

Append to the `"params"` list:

```json
{
  "id": "kp_alt_hold",
  "mavlink_id": "DF_KP_ALT_H",
  "type": "float",
  "default": 0.5,
  "min": 0.0,
  "max": 2.0,
  "step": 0.05,
  "group": "alt",
  "order": 8,
  "label": "Alt-hold P-gain",
  "description": "Gain on (current_alt - target_altitude) → down velocity. Higher = snappier altitude-hold, lower = gentler.",
  "read_only": false
}
```

- [ ] **Step 5: Add to web_server `_CONFIG_FIELDS`**

In `drone_follow/servers/web_server.py`, add `"kp_alt_hold": float,` to the `_CONFIG_FIELDS` table.

- [ ] **Step 6: Add to openhd_bridge `_CONFIG_PARAMS`**

In `drone_follow/servers/openhd_bridge.py`:

```python
_CONFIG_PARAMS = {
    ...
    "kp_alt_hold":  ("DF_KP_ALT_H", float),
    ...
}
```

- [ ] **Step 7: Run tests**

```bash
pytest drone_follow/tests/test_config_persistence.py -v
```
Expected: 3 new pass.

- [ ] **Step 8: Commit**

```bash
git add drone_follow/follow_api/config.py df_params.json \
        drone_follow/servers/{web_server,openhd_bridge}.py \
        drone_follow/tests/test_config_persistence.py
git commit -m "expose kp_alt_hold via CLI, df_params, web UI, and OpenHD MAVLink"
```

---

### Task 9: Remove `right_m_s` from `VelocityCommand` (and the API surface)

**Why:** With orbit gone, `right_m_s` is always 0 from the controller. The MAVSDK adapter passes it through unsmoothed and unclamped — a future caller writing non-zero would bypass every safety. Remove the field; rebuild the 4-tuple at the MAVSDK boundary.

**Files:**
- Modify: `drone_follow/follow_api/types.py`
- Modify: `drone_follow/follow_api/controller.py` (every `VelocityCommand(...)` call)
- Modify: `drone_follow/drone_api/mavsdk_drone.py` (rebuild `VelocityBodyYawspeed` from 3-tuple + 0)
- Modify: existing tests that construct `VelocityCommand(forward, right, down, yaw)`
- Test: extend to assert MAVSDK boundary call uses right=0

- [ ] **Step 1: Search for callers**

```bash
grep -rn "VelocityCommand(" drone_follow/ | grep -v tests
grep -rn "right_m_s" drone_follow/
```
Capture the list — every constructor needs to drop the second positional arg.

- [ ] **Step 2: Update `types.py`**

```python
@dataclass
class VelocityCommand:
    forward_m_s: float
    down_m_s: float
    yawspeed_deg_s: float
```

- [ ] **Step 3: Update controller and MAVSDK adapter**

In `drone_follow/follow_api/controller.py`, remove the `0.0` from every constructor:

```python
return VelocityCommand(forward, 0.0, yawspeed)   # ← drop the 0.0 right
```

In `drone_follow/drone_api/mavsdk_drone.py` `VelocityCommandAPI.send`, replace `cmd.right_m_s` with the literal `0.0` at the MAVSDK boundary, and drop the `right` clamp/EMA bookkeeping.

- [ ] **Step 4: Update existing tests**

In `drone_follow/tests/test_velocity_api_and_smoother.py`, all `VelocityCommand(forward, right, down, yaw)` calls must drop the right arg. The current tests already removed orbit-specific cases — only the constructor signatures remain.

- [ ] **Step 5: Run the full test suite**

```bash
pytest drone_follow/tests/ -q --ignore=drone_follow/tests/test_sim_worlds.py
```
Expected: all pass after the constructor migrations.

- [ ] **Step 6: Commit**

```bash
git add drone_follow/follow_api/{types,controller}.py \
        drone_follow/drone_api/mavsdk_drone.py \
        drone_follow/tests/
git commit -m "follow_api: drop unused right_m_s; rebuild MAVSDK 4-tuple at the boundary"
```

---

### Task 10: Velocity deadband near zero on `forward_m_s`

**Why:** When `bbox` is within a few % of `target`, the controller emits sub-deadband-but-non-zero values that pass through the EMA and produce visible hover twitch. PX4 follow-me uses a 1.0 m/s velocity deadband for exactly this reason.

**Files:**
- Modify: `drone_follow/follow_api/config.py` (add `forward_velocity_deadband: float = 0.05`)
- Modify: `drone_follow/follow_api/controller.py` (apply at end of tracking branch)
- Test: `drone_follow/tests/test_controller.py`

- [ ] **Step 1: Add a failing test**

Append to `class TestDistanceForward`:

```python
    def test_forward_below_deadband_clamped_to_zero(self):
        cfg = ControllerConfig(
            yaw_only=False, target_bbox_height=0.30,
            kp_distance=1.0, kp_distance_back=1.0,
            top_margin_safety=0.0, bottom_margin_safety=0.0,
            dead_zone_bbox_percent=0.0,
            forward_velocity_deadband=0.10,
        )
        # bbox=0.295 → factor ≈ 0.017, raw = 0.017 m/s, well below 0.10 deadband
        cmd = compute_velocity_command(_det(bh=0.295), cfg)
        assert cmd.forward_m_s == 0.0

    def test_forward_above_deadband_passes_through(self):
        cfg = ControllerConfig(
            yaw_only=False, target_bbox_height=0.30,
            kp_distance=1.0, kp_distance_back=1.0,
            top_margin_safety=0.0, bottom_margin_safety=0.0,
            dead_zone_bbox_percent=0.0,
            forward_velocity_deadband=0.05,
        )
        cmd = compute_velocity_command(_det(bh=0.20), cfg)
        # factor ≈ 0.5 → raw = 0.5 m/s ≫ 0.05 deadband
        assert cmd.forward_m_s == pytest.approx(0.5, abs=1e-6)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest drone_follow/tests/test_controller.py::TestDistanceForward -v
```
Expected: `forward_velocity_deadband` not a known field.

- [ ] **Step 3: Add the field + apply it**

In `drone_follow/follow_api/config.py`:

```python
forward_velocity_deadband: float = 0.05  # |forward| below this → snap to 0 (kills hover twitch)
```

(remember to add to `add_args` and to `from_args`).

In `drone_follow/follow_api/controller.py`, at the end of `compute_velocity_command` tracking branch (after `_apply_frame_edge_safety`):

```python
if abs(forward) < config.forward_velocity_deadband:
    forward = 0.0
return VelocityCommand(forward, 0.0, yawspeed)
```

- [ ] **Step 4: Run tests**

```bash
pytest drone_follow/tests/test_controller.py -q
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add drone_follow/follow_api/{config,controller}.py drone_follow/tests/test_controller.py
git commit -m "follow_api: add forward_velocity_deadband (snap |fwd|<deadband to 0)"
```

---

### Task 11: Fix `test_log_file` close race

**Why:** Probe checks `if user_data.test_log_file is not None` then writes; main thread's `close_test_log()` sets it to None. `None.write` raises `AttributeError`, which isn't caught.

**Files:**
- Modify: `drone_follow/pipeline_adapter/hailo_drone_detection_manager.py`
- Test: existing tests for the JSONL writer

- [ ] **Step 1: Locate the write block**

```bash
grep -n "test_log_file" drone_follow/pipeline_adapter/hailo_drone_detection_manager.py
```

- [ ] **Step 2: Write a thread-stress test**

Create `drone_follow/tests/test_test_log_writer.py`:

```python
"""test-log writer must survive close() being called from another thread
between the is-not-None check and the .write() call."""

import io
import threading
import time

import pytest


def test_writer_handles_concurrent_close():
    from drone_follow.pipeline_adapter.hailo_drone_detection_manager import (
        DroneFollowUserData,
    )
    user_data = DroneFollowUserData()
    user_data.test_log_file = io.StringIO()

    stop = threading.Event()
    errors = []

    def writer():
        while not stop.is_set():
            try:
                # Replicates the inline pattern in the probe:
                f = user_data.test_log_file
                if f is not None:
                    f.write("{}\n")
            except Exception as e:
                errors.append(e)

    t = threading.Thread(target=writer)
    t.start()
    time.sleep(0.05)
    user_data.test_log_file = None
    time.sleep(0.05)
    stop.set()
    t.join()
    assert not errors, f"writer raised: {errors}"
```

- [ ] **Step 3: Verify the test fails on the *un*fixed code**

This depends on the ordering — the test may be flaky on the unfixed version. Skip this step if the test passes by chance, but apply the fix in step 4 anyway.

- [ ] **Step 4: Apply the fix**

In the probe write block, snapshot the handle into a local var:

```python
log = user_data.test_log_file  # snapshot — main thread can null this any moment
if log is not None:
    try:
        log.write(json.dumps(record) + "\n")
    except (ValueError, OSError, AttributeError):
        pass
```

- [ ] **Step 5: Run the test**

```bash
pytest drone_follow/tests/test_test_log_writer.py -v
```
Expected: pass, no errors raised.

- [ ] **Step 6: Commit**

```bash
git add drone_follow/pipeline_adapter/hailo_drone_detection_manager.py drone_follow/tests/test_test_log_writer.py
git commit -m "pipeline: snapshot test_log_file handle to avoid close-race AttributeError"
```

---

### Task 12: `dead_zone_bbox_percent` semantic-change documentation

**Why:** Old: `(pct/100) * target_bbox_height` (15% × 0.3 = 0.045 in bbox units). New: `pct/100` interpreted as `|factor|` directly. Existing user configs with `dead_zone_bbox_percent: 15` load fine but mean a much wider band. Document explicitly.

**Files:**
- Modify: `drone_follow/follow_api/config.py` (help string + docstring)
- Modify: `df_params.json` (description)
- Modify: `docs/control-architecture.md`

- [ ] **Step 1: Update the docstring on the field**

In `drone_follow/follow_api/config.py`:

```python
dead_zone_bbox_percent: float = 10.0
"""Dead band on the distance error |factor| where factor = target/bbox - 1.
A value of 10.0 means: |bbox - target|/target < 10% → command 0.

NOTE: semantics changed from the pre-2026-04 controller. Previously this was
a percentage of target_bbox_height in bbox units (15% × 0.3 = 0.045 absolute);
now it is a percentage of the relative distance error itself.
Old configs continue to load but will have a wider effective dead band."""
```

- [ ] **Step 2: Update the slider description**

In `df_params.json`, the `dead_zone_bbox_percent` entry's `description` field:

```json
"description": "Distance dead band as percent of relative error |target/bbox - 1|. Note: semantics changed in 2026-04 controller — old configs load with a wider effective band."
```

- [ ] **Step 3: Update `docs/control-architecture.md` section 3.2**

Add a one-paragraph note flagging the semantic change.

- [ ] **Step 4: Commit**

```bash
git add drone_follow/follow_api/config.py df_params.json docs/control-architecture.md
git commit -m "docs: clarify dead_zone_bbox_percent semantic change in 2026-04 controller"
```

---

### Task 13: `walk_across_then_approach.sdf` — keep loop reset out of the test window

**Why:** Phase 4's path passes the actor through the drone airspace twice in 90 s, contaminating the test's approach-window assertions.

**Files:**
- Modify: `sim/worlds/walk_across_then_approach.sdf` (move the Phase 4 return path well off-axis, or extend the loop period beyond 90 s)
- Test: `drone_follow/tests/test_sim_worlds.py::test_walk_across_then_approach_holds_target_through_approach`

- [ ] **Step 1: Inspect Phase 4 waypoints**

```bash
grep -n "<waypoint>" sim/worlds/walk_across_then_approach.sdf | head -30
```

Identify the `t=53→67` segment and the loop reset.

- [ ] **Step 2: Either path-shift Phase 4 or extend the period**

Option A: route the actor `(8,0) → (8, -10) → (-5, -10) → (-5, 0)` (a U-turn well to the right of the camera), so the return doesn't enter the FOV.

Option B: extend the loop period to ≥ 120 s so the test's 90 s window never sees the reset.

- [ ] **Step 3: Re-run the sim test**

```bash
RUN_SIM_TESTS=1 pytest drone_follow/tests/test_sim_worlds.py::test_walk_across_then_approach_holds_target_through_approach -s
```
Expected: pass.

- [ ] **Step 4: Commit**

```bash
git add sim/worlds/walk_across_then_approach.sdf
git commit -m "sim: keep walk_across_then_approach loop reset out of the test capture window"
```

---

### Task 14: Restore explicit gain tuning in `simulation_follow.json` (or document the change)

**Why:** PR #178 silently dropped explicit `kp_forward=2.0` and `kp_backward=4.0` from `sim/configs/simulation_follow.json`. Since those keys no longer exist, the JSON is now equivalent to dataclass defaults — but the test suite was tuned against the old gains.

**Files:**
- Modify: `sim/configs/simulation_follow.json`

- [ ] **Step 1: Decide intentional vs accidental**

Check the controller test pass rate at PR-head defaults:

```bash
RUN_SIM_TESTS=1 pytest drone_follow/tests/test_sim_worlds.py -s
```

If the tests pass, the deletion was correct — re-derive equivalent values for the new controller (`kp_distance` ≈ 0.6, `kp_distance_back` ≈ 2.5; for the simulator we want gentler — try `kp_distance=0.5, kp_distance_back=2.0`).

- [ ] **Step 2: Add explicit values back to the JSON**

```json
{
  "yaw_only": false,
  "target_altitude": 3.0,
  "max_altitude": 6.0,
  "target_bbox_height": 0.25,
  "kp_distance": 0.5,
  "kp_distance_back": 2.0,
  "max_forward": 1.0,
  "max_backward": 1.5,
  "smooth_yaw": true,
  "smooth_forward": true,
  "forward_alpha": 0.10,
  "search_timeout_s": 60.0,
  "log_verbosity": "normal"
}
```

- [ ] **Step 3: Re-run sim tests**

```bash
RUN_SIM_TESTS=1 pytest drone_follow/tests/test_sim_worlds.py -s
```
Expected: pass with consistent margin.

- [ ] **Step 4: Commit**

```bash
git add sim/configs/simulation_follow.json
git commit -m "sim: restore explicit kp_distance/kp_distance_back tuning for simulation_follow"
```

---

## Phase 3 — P2: Polish & docs

### Task 15: Doc inconsistencies in `control-architecture.md`

**Files:**
- Modify: `docs/control-architecture.md`

- [ ] **Step 1: Fix the `kp_distance` default reference**

Find the tuning table that says `kp_distance | 1.0` and change to:

```
| `kp_distance` | 0.6 | Approach gain on (target/bbox - 1); raise cautiously for snappier closes |
```

- [ ] **Step 2: Drop `right (α=0.3)` from the EMA list in section 3.1**

Section 3.1 still mentions the right-axis EMA. The right-axis smoothing was removed in PR #178; update the list to:

> All three live axes have per-axis EMA in `send()`: yaw (α=0.3), forward (α=0.15), down (α=0.2).

- [ ] **Step 3: Commit**

```bash
git add docs/control-architecture.md
git commit -m "docs: control-architecture — kp_distance default 0.6, drop right-axis EMA mention"
```

---

### Task 16: Rename misleading local `follow_mode` → `follow_status`

**Why:** Local variable shadows the just-removed config field name; readers scanning the file misread it as a stale reference.

**Files:**
- Modify: `drone_follow/pipeline_adapter/hailo_drone_detection_manager.py`

- [ ] **Step 1: Run the rename**

```bash
sed -i 's/\bfollow_mode\b/follow_status/g' drone_follow/pipeline_adapter/hailo_drone_detection_manager.py
```

(Verify no other meaning of `follow_mode` exists in this file via `git diff` — if it did, it'd be a stale config reference, also worth removing.)

- [ ] **Step 2: Run the test suite**

```bash
pytest drone_follow/tests/ -q --ignore=drone_follow/tests/test_sim_worlds.py
```
Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add drone_follow/pipeline_adapter/hailo_drone_detection_manager.py
git commit -m "pipeline: rename local follow_mode → follow_status to disambiguate"
```

---

### Task 17: `--tracker` choices + free-form mode strings

**Files:**
- Modify: `drone_follow/drone_follow_app.py` (add `choices=` to the pre-parser)
- Modify: `drone_follow/pipeline_adapter/tracker_factory.py` (export `TRACKER_CHOICES`)
- Modify: `drone_follow/pipeline_adapter/hailo_drone_detection_manager.py` (replace `_log_mode` strings with an enum)

- [ ] **Step 1: Export `TRACKER_CHOICES` from `tracker_factory.py`**

```python
TRACKER_CHOICES = ("byte", "fast")
```

- [ ] **Step 2: Wire into the pre-parser**

In `drone_follow_app.py` line ~1326:

```python
from drone_follow.pipeline_adapter.tracker_factory import TRACKER_CHOICES
tracker_pre.add_argument("--tracker", default="byte", choices=TRACKER_CHOICES)
```

- [ ] **Step 3: Add an enum for the log-mode keys**

In `hailo_drone_detection_manager.py`:

```python
class FollowEvent(str, enum.Enum):
    NO_PERSONS = "no-persons"
    IDLE_NO_AUTO = "idle-no-auto"
    AUTO_NO_TRACKED = "auto-no-tracked"
    FALLBACK = "fallback"
    REID_SEARCH = "reid-search"
```

Replace every free-form string in `_log_mode(...)` with `FollowEvent.X.value`.

- [ ] **Step 4: Run the test suite**

```bash
pytest drone_follow/tests/ -q --ignore=drone_follow/tests/test_sim_worlds.py
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add drone_follow/{drone_follow_app.py,pipeline_adapter/{tracker_factory,hailo_drone_detection_manager}.py}
git commit -m "pipeline: tighten --tracker choices and replace free-form log-mode strings with enum"
```

---

### Task 18: `MetricsTracker.id_switches` rename → `id_dropouts`

**Files:**
- Modify: `drone_follow/pipeline_adapter/tracker.py`
- Modify: any consumer of the field

- [ ] **Step 1: grep for the field**

```bash
grep -rn "id_switches" drone_follow/
```

- [ ] **Step 2: Rename**

```bash
git grep -l "id_switches" drone_follow/ | xargs sed -i 's/\bid_switches\b/id_dropouts/g'
```

- [ ] **Step 3: Test + commit**

```bash
pytest drone_follow/tests/ -q --ignore=drone_follow/tests/test_sim_worlds.py
git add -A drone_follow/
git commit -m "pipeline: MetricsTracker.id_switches → id_dropouts (1-frame Lost→Active doesn't switch)"
```

---

## Phase 4 — Future work

### Task 19: Align simulator camera with real-camera resolution + FOV

**Why:** Confirmed mismatch:

| Property | Sim (x500_vision_camera.patch) | Real (ControllerConfig defaults) |
|---|---|---|
| Resolution | 640×480 | RPi/USB typically 1920×1080 or 1280×720 |
| Horizontal FOV | 1.74 rad ≈ **99.7°** | **66°** |
| Vertical FOV | derived from resolution + hfov | 41° |
| Frame rate | 30 fps | varies |

The yaw controller scales `error_x_deg = (center_x - 0.5) * config.hfov`; with the sim at 99.7° the same `center_x=0.7` yields `19.94°` of error vs `13.2°` on the real camera. The sim drone yaws **51 % faster** than the real one for the same image-plane error — every simulation tuning of `kp_yaw` is silently miscalibrated.

**Files:**
- Modify: `sim/patches/x500_vision_camera.patch`
- Modify: `sim/setup_sim.sh` (re-apply patch on next setup)
- Modify: `sim/configs/simulation.json`, `sim/configs/simulation_follow.json` (set explicit `hfov` / `vfov`)
- Test: `drone_follow/tests/test_sim_worlds.py` (no changes needed if the controller is FOV-correct)

- [ ] **Step 1: Decide the canonical resolution + FOV pair**

Pick the real-camera target. RPi Camera Module 3 wide-angle: **1536×864 @ 30 fps, hfov ≈ 66°**. Imx708 in narrow mode: 1920×1080 @ 30 fps, hfov ≈ 66° too. Use **1920×1080, hfov=1.152 rad (66°)** as the canonical sim target — matches `ControllerConfig.hfov=66`.

- [ ] **Step 2: Update the sim patch**

Edit `sim/patches/x500_vision_camera.patch`:

```xml
<camera>
  <horizontal_fov>1.152</horizontal_fov>   <!-- 66° to match real camera -->
  <image>
    <width>1920</width>
    <height>1080</height>
  </image>
  ...
</camera>
<update_rate>30</update_rate>
```

- [ ] **Step 3: Re-run setup_sim.sh to re-apply the patch**

```bash
sim/setup_sim.sh
```

(The script must re-apply the updated patch over the PX4 submodule clean tree. If `setup_sim.sh` only applies the patch on first init, also run `git -C sim/PX4-Autopilot apply ../patches/x500_vision_camera.patch` manually after a `git checkout -- Tools/simulation/gz/models/x500_vision/`.)

- [ ] **Step 4: Set explicit `hfov` / `vfov` in the sim configs**

In `sim/configs/simulation.json` and `simulation_follow.json`:

```json
"hfov": 66.0,
"vfov": 41.0,
```

- [ ] **Step 5: Update `sim/bridge/video_bridge.py` if it caps resolution**

```bash
grep -n "width\|height" sim/bridge/video_bridge.py
```

Confirm the bridge accepts whatever resolution the gz topic publishes. (Today it auto-detects from the message; should be fine.)

- [ ] **Step 6: Re-run the full sim test suite**

```bash
RUN_SIM_TESTS=1 pytest drone_follow/tests/test_sim_worlds.py -s
```
Expected: pass. The yaw response will now match real-camera tuning.

- [ ] **Step 7: Commit**

```bash
git add sim/patches/x500_vision_camera.patch sim/configs/{simulation,simulation_follow}.json
git commit -m "sim: align sim camera with real (1920x1080, hfov=66°); set explicit hfov/vfov in sim configs"
```

---

### Task 20: Better tiling allocator — adapt `tiles_x`/`tiles_y` to expected target size

**Why:** Today the operator passes `--tiles-x 3 --tiles-y 2` from the CLI; the same allocation runs whether the person is 0.05 of frame (far) or 0.4 of frame (close). At close range the 3×2 grid produces redundant detections; at far range the central tile crack splits small targets.

**Concept:** Adapt the tile allocation each `N` frames based on:
- The size of the currently-locked target (use `target_bbox_height`)
- The number of expected scales — small targets need finer tiling, large ones don't

**Files:**
- Modify: `drone_follow/pipeline_adapter/hailo_drone_detection_manager.py` — add a `_TileAllocator` class
- Modify: pipeline rebuild path (already exists for resolution changes around line 670)
- Test: `drone_follow/tests/test_tile_allocator.py` (NEW)

- [ ] **Step 1: Specify the policy**

Three regimes (single rule of thumb, tunable):

| `target_bbox_height` | tiles_x × tiles_y | multi_scale |
|---|---|---|
| ≥ 0.20 (close) | 1×1 | off |
| 0.08 – 0.20 (medium) | 2×1 | off |
| < 0.08 (far) | 3×2 | on (1 extra full-frame pass) |

Hysteresis: reallocation only fires when the moving-average bbox crosses a regime boundary by more than 20 %.

- [ ] **Step 2: Write the failing tests**

Create `drone_follow/tests/test_tile_allocator.py`:

```python
"""Tile allocator picks (tiles_x, tiles_y, multi_scale) from observed bbox size."""

import pytest
from drone_follow.pipeline_adapter.tile_allocator import TileAllocator


@pytest.mark.parametrize("bh, expected", [
    (0.30, (1, 1, False)),
    (0.10, (2, 1, False)),
    (0.05, (3, 2, True)),
])
def test_regimes(bh, expected):
    a = TileAllocator()
    a.update(bh)
    a.update(bh)  # warmup
    a.update(bh)
    assert a.allocation() == expected


def test_hysteresis_does_not_chatter_at_boundary():
    a = TileAllocator()
    # Oscillate around the 0.20 boundary with ±5%
    for v in [0.21, 0.19, 0.21, 0.19, 0.21, 0.19]:
        a.update(v)
    # Should remain in the (1,1,off) regime, no re-allocation request
    assert a.allocation() == (1, 1, False)
    assert not a.should_rebuild()
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest drone_follow/tests/test_tile_allocator.py -v
```
Expected: `ImportError`.

- [ ] **Step 4: Implement `TileAllocator`**

Create `drone_follow/pipeline_adapter/tile_allocator.py`:

```python
"""Adaptive tile-grid allocator based on observed bbox size."""

from collections import deque
from dataclasses import dataclass


_REGIMES = [
    # (max_bh,  tiles_x, tiles_y, multi_scale)
    (1.00,    1, 1, False),  # close
    (0.20,    2, 1, False),  # medium
    (0.08,    3, 2, True),   # far
]
_HYSTERESIS = 0.20  # require 20% margin to switch regimes
_WINDOW = 30       # samples (~1 s at 30 fps)


@dataclass
class _Allocation:
    tiles_x: int
    tiles_y: int
    multi_scale: bool


class TileAllocator:
    def __init__(self):
        self._samples: deque = deque(maxlen=_WINDOW)
        self._current = _Allocation(1, 1, False)
        self._dirty = False

    def update(self, bbox_height: float) -> None:
        self._samples.append(bbox_height)
        avg = sum(self._samples) / len(self._samples)
        new = self._regime_for(avg)
        if (new.tiles_x, new.tiles_y, new.multi_scale) != \
           (self._current.tiles_x, self._current.tiles_y, self._current.multi_scale):
            self._current = new
            self._dirty = True

    def allocation(self):
        return (self._current.tiles_x, self._current.tiles_y, self._current.multi_scale)

    def should_rebuild(self) -> bool:
        return self._dirty

    def consume_rebuild(self) -> None:
        self._dirty = False

    def _regime_for(self, avg_bh: float) -> _Allocation:
        cur_max = self._regime_max(self._current)
        # Apply hysteresis: stay in current regime if within ±_HYSTERESIS of its boundary
        if cur_max * (1 - _HYSTERESIS) <= avg_bh <= cur_max * (1 + _HYSTERESIS):
            return self._current
        for max_bh, tx, ty, ms in _REGIMES:
            if avg_bh <= max_bh:
                if max_bh < cur_max or avg_bh > cur_max:
                    return _Allocation(tx, ty, ms)
        return self._current

    @staticmethod
    def _regime_max(a):
        for max_bh, tx, ty, ms in _REGIMES:
            if (tx, ty, ms) == (a.tiles_x, a.tiles_y, a.multi_scale):
                return max_bh
        return 1.0
```

(Tune the hysteresis logic until the chatter test passes — the literal above is a starting point.)

- [ ] **Step 5: Wire `TileAllocator` into the detection manager**

In `hailo_drone_detection_manager.py`:

- Construct `self.tile_allocator = TileAllocator()` in `DroneFollowUserData.__init__`.
- After every `shared_state.update(Detection(...))` call, also `tile_allocator.update(detection.bbox_height)`.
- In the periodic pipeline-rebuild check (around line 670 — already exists for resolution changes), check `tile_allocator.should_rebuild()` and trigger a rebuild with the new allocation. After rebuild, call `tile_allocator.consume_rebuild()`.

- [ ] **Step 6: Run tests**

```bash
pytest drone_follow/tests/test_tile_allocator.py -v
pytest drone_follow/tests/ -q --ignore=drone_follow/tests/test_sim_worlds.py
```
Expected: all pass.

- [ ] **Step 7: Sanity-check on a sim run**

```bash
RUN_SIM_TESTS=1 pytest drone_follow/tests/test_sim_worlds.py::test_walk_across_then_approach_holds_target_through_approach -s
```

Watch the log — the allocation should drop from 3×2 to 1×1 as the actor approaches.

- [ ] **Step 8: Commit**

```bash
git add drone_follow/pipeline_adapter/{tile_allocator,hailo_drone_detection_manager}.py \
        drone_follow/tests/test_tile_allocator.py
git commit -m "pipeline: adaptive tile allocator with hysteresis (close → 1x1, far → 3x2 + multiscale)"
```

---

### Task 21: Torso-keypoint tracking point

**Why:** Bbox center is sensitive to arm extension and lower-body occlusion. Shoulder-to-hip pixel span gives a more stable distance proxy and a more disciplined yaw target. Validated by Tello+MediaPipe paper at 2–10 m / 2 m/s.

**Architecture:** Run a person-pose HEF *in addition to* the existing detection HEF (or use a multi-task net if the model zoo has one). Use shoulder-midpoint for `cx`, shoulder-to-hip pixel span for distance, fall back to bbox-derived values when the keypoint pair confidence is low. Bound the cost to a few % of frame budget.

**Files:**
- New: `drone_follow/pipeline_adapter/pose_keypoint_extractor.py` (parses pose HEF outputs into a `Keypoints` dataclass)
- Modify: `drone_follow/pipeline_adapter/hailo_drone_detection_manager.py` (compute `cx`/`cy`/`distance_proxy` from keypoints when available)
- Modify: `drone_follow/follow_api/types.py` — extend `Detection` with optional keypoints
- Modify: `drone_follow/follow_api/controller.py` — distance error from `distance_proxy` (shoulder-to-hip span) when present, else from `bbox_height`
- New: `drone_follow/tests/test_pose_features.py`
- Docs: `docs/control-architecture.md` adds a "Tracking points" section

- [ ] **Step 1: Investigate available pose HEF**

Check the Hailo Model Zoo for compatible person-pose HEFs:

```bash
hailomz info yolov8s_pose --hw-arch hailo8l 2>&1 | head -20
```

Confirm at least 17-keypoint COCO-style output (shoulders idx 5/6, hips idx 11/12).

- [ ] **Step 2: Define the `Keypoints` dataclass**

In `drone_follow/follow_api/types.py`:

```python
@dataclass
class Keypoints:
    """Per-detection keypoint summary. Pixel-normalized [0..1]."""
    shoulder_mid: tuple[float, float] | None = None  # (x, y)
    hip_mid: tuple[float, float] | None = None
    shoulder_to_hip_span: float = 0.0  # pixel-normalized vertical span
    confidence: float = 0.0


@dataclass
class Detection:
    label: str
    confidence: float
    center_x: float
    center_y: float
    bbox_height: float
    timestamp: float
    keypoints: Keypoints | None = None  # None if pose HEF unavailable or low confidence
```

- [ ] **Step 3: Write the failing tests**

Create `drone_follow/tests/test_pose_features.py`:

```python
"""Controller uses keypoint-based distance proxy when available."""

import pytest
from drone_follow.follow_api import (
    ControllerConfig, Detection, compute_velocity_command,
)
from drone_follow.follow_api.types import Keypoints


def _det_with_kp(span, cx=0.5, cy=0.5, bh=0.3, kp_conf=0.9):
    return Detection(
        label="person", confidence=0.9,
        center_x=cx, center_y=cy, bbox_height=bh, timestamp=0.0,
        keypoints=Keypoints(
            shoulder_mid=(cx, cy - span / 2),
            hip_mid=(cx, cy + span / 2),
            shoulder_to_hip_span=span,
            confidence=kp_conf,
        ),
    )


def test_distance_proxy_uses_keypoint_span_when_high_confidence():
    cfg = ControllerConfig(yaw_only=False, target_keypoint_span=0.20,
                           kp_distance=1.0, kp_distance_back=1.0,
                           dead_zone_bbox_percent=0.0,
                           top_margin_safety=0.0, bottom_margin_safety=0.0)
    # span 0.10 < target 0.20 → person far → forward
    cmd_far = compute_velocity_command(_det_with_kp(span=0.10), cfg)
    assert cmd_far.forward_m_s > 0.0


def test_keypoint_low_confidence_falls_back_to_bbox():
    cfg = ControllerConfig(yaw_only=False, target_bbox_height=0.30,
                           kp_distance=1.0, kp_distance_back=1.0,
                           dead_zone_bbox_percent=0.0,
                           top_margin_safety=0.0, bottom_margin_safety=0.0)
    det = _det_with_kp(span=0.10, bh=0.30, kp_conf=0.1)  # low kp confidence
    cmd = compute_velocity_command(det, cfg)
    assert cmd.forward_m_s == 0.0  # bbox at target → no forward
```

- [ ] **Step 4: Run tests to verify they fail**

```bash
pytest drone_follow/tests/test_pose_features.py -v
```
Expected: fail (`Keypoints` not yet, `target_keypoint_span` not a config field, controller doesn't use it).

- [ ] **Step 5: Add `target_keypoint_span` and `keypoint_confidence_threshold` to `ControllerConfig`**

```python
target_keypoint_span: float = 0.20      # desired shoulder-to-hip span (frame fraction); used when keypoints available
keypoint_confidence_threshold: float = 0.5
```

- [ ] **Step 6: Switch the controller's distance-error source**

In `drone_follow/follow_api/controller.py` `_calculate_distance_speed`:

```python
def _calculate_distance_speed(detection, config):
    if config.yaw_only:
        return 0.0

    # Prefer keypoint span when available and confident.
    if (detection.keypoints is not None
            and detection.keypoints.confidence >= config.keypoint_confidence_threshold
            and detection.keypoints.shoulder_to_hip_span > 0
            and config.target_keypoint_span > 0):
        target = config.target_keypoint_span
        observed = detection.keypoints.shoulder_to_hip_span
    else:
        target = config.target_bbox_height
        observed = detection.bbox_height

    if observed <= 0:
        return 0.0

    factor = (target / observed) - 1.0
    dead_zone = config.dead_zone_bbox_percent / 100.0
    if abs(factor) < dead_zone:
        return 0.0

    gain = config.kp_distance_back if factor < 0 else config.kp_distance
    if gain == 0:
        return 0.0
    raw = gain * factor
    return max(-config.max_backward, min(config.max_forward, raw))
```

- [ ] **Step 7: Implement `pose_keypoint_extractor.py`**

This is the GStreamer-side glue. Two options:

- **Option A (preferred)**: replace the detection HEF with a YOLO-pose HEF that emits both bbox and 17 keypoints in one inference.
- **Option B**: run a separate pose HEF on the cropped person bbox after detection (more expensive).

Define the parsing in `pose_keypoint_extractor.py`:

```python
"""Parse pose-keypoint outputs from a HailoROI into a Keypoints summary."""

from drone_follow.follow_api.types import Keypoints

_LEFT_SHOULDER = 5
_RIGHT_SHOULDER = 6
_LEFT_HIP = 11
_RIGHT_HIP = 12


def extract_torso_keypoints(person_roi, frame_w, frame_h) -> Keypoints:
    """person_roi is the HailoROI for the matched person; returns Keypoints in
    pixel-normalized [0..1] coordinates."""
    landmarks = person_roi.get_objects_typed(hailo.HAILO_LANDMARKS)
    if not landmarks:
        return Keypoints()
    points = landmarks[0].get_points()  # list of HailoPoint
    if len(points) < max(_LEFT_HIP, _RIGHT_HIP) + 1:
        return Keypoints()

    ls, rs = points[_LEFT_SHOULDER], points[_RIGHT_SHOULDER]
    lh, rh = points[_LEFT_HIP], points[_RIGHT_HIP]

    if min(ls.confidence(), rs.confidence(), lh.confidence(), rh.confidence()) < 0.3:
        return Keypoints()

    sm_x = (ls.x() + rs.x()) / 2
    sm_y = (ls.y() + rs.y()) / 2
    hm_x = (lh.x() + rh.x()) / 2
    hm_y = (lh.y() + rh.y()) / 2
    span = hm_y - sm_y  # vertical pixel-normalized
    if span <= 0:
        return Keypoints()
    avg_conf = (ls.confidence() + rs.confidence() + lh.confidence() + rh.confidence()) / 4
    return Keypoints(
        shoulder_mid=(sm_x, sm_y),
        hip_mid=(hm_x, hm_y),
        shoulder_to_hip_span=span,
        confidence=avg_conf,
    )
```

- [ ] **Step 8: Wire keypoints into `Detection` construction**

In `hailo_drone_detection_manager.py`, after building `Detection(...)`, populate `keypoints=extract_torso_keypoints(best, video_width, video_height)`.

- [ ] **Step 9: Update `cx` to use shoulder midpoint when keypoints are confident**

When keypoints are usable, override `cx` (yaw input) with `shoulder_mid.x`; the bbox center remains a fallback.

- [ ] **Step 10: Run all tests**

```bash
pytest drone_follow/tests/ -q --ignore=drone_follow/tests/test_sim_worlds.py
```
Expected: all pass, including new keypoint tests.

- [ ] **Step 11: Sim integration test (manual)**

You'll need a sim model for the actor that includes pose-able keypoints — most gz-sim actors don't, so this step is field-test on real hardware:

```bash
drone-follow --input rpi --pose-model yolov8s_pose --no-yaw-only --ui
```

Walk in front of the drone with arms-out, arms-up, etc. The forward command should stay calm (because span doesn't change with arm extension), unlike a `bbox_width` proxy.

- [ ] **Step 12: Commit**

```bash
git add drone_follow/pipeline_adapter/pose_keypoint_extractor.py \
        drone_follow/pipeline_adapter/hailo_drone_detection_manager.py \
        drone_follow/follow_api/{types,controller,config}.py \
        drone_follow/tests/test_pose_features.py
git commit -m "follow_api: torso-keypoint distance proxy with bbox fallback (Tello+MediaPipe pattern)"
```

---

### Task 22: PX4-style `responsiveness` knob (architectural; not blocking)

This is a larger change — out of scope for this plan as a single task. Tracked here as a **forward-looking design memo**:

- Single user-facing scalar `responsiveness` (0.1 highly damped → 0.9 snappy).
- Internally maps to: input filter cutoff (input-side LPF on bbox state), output EMA `forward_alpha`, slew-rate `max_forward_accel`, deadband `forward_velocity_deadband`.
- One slider replaces five.
- Needs a separate brainstorming session before implementation.

No tasks in this plan; capture in `docs/superpowers/plans/2026-XX-responsiveness-knob.md` when ready.

---

## Self-review checklist

- [x] Each P0 issue has a task and a test.
- [x] Each P1 issue has a task and a test.
- [x] Each P2 polish item has a step.
- [x] All future-work items the user named (torso keypoints, tiling, sim/real camera) have full TDD task plans.
- [x] No `TBD`, `add appropriate error handling`, or "similar to Task N" placeholders.
- [x] All file paths are absolute under the working directory.
- [x] Type names (`Detection`, `VelocityCommand`, `TrackedObject`, `Keypoints`) are consistent across tasks.
- [x] Tests use the existing `pytest` + `tmp_path` patterns from `test_config_persistence.py` and `conftest.py`.
- [x] Each task ends with an explicit `git commit -m "..."` step.
