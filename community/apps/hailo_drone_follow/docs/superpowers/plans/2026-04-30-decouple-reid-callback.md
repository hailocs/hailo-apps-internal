# Decouple ReID Work from GStreamer Streaming Thread

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move ReID gallery work (`reid_manager.update_gallery`) out of the GStreamer streaming thread (`app_callback`) onto a background worker thread, so the streaming thread can return promptly and the real-time pipeline doesn't stall on per-frame ReID work.

**Architecture:**
A new `ReIDWorker` runs in a daemon thread fed by a bounded `queue.Queue`. The streaming-thread callback in `hailo_drone_detection_manager.py` calls `reid_worker.submit_gallery_update(frame_bgr, hailo_bbox, w, h, original_id)` and returns immediately. The worker pulls submissions off the queue and calls `reid_manager.update_gallery(...)` off the streaming thread. `try_reidentify` stays synchronous — it runs only when the target is lost and its result must apply to the current frame's `person_by_id`. Adding async `try_reidentify` is a follow-up if needed.

**Why a thread, not a process:** the user asked for "different process," but for the stated goal (don't block the streaming thread):
- Hailo NPU calls release the GIL, so the worker thread genuinely runs concurrently with the streaming thread during `extract_embedding`.
- A worker thread can share `numpy` arrays and Hailo C++ buffer-derived objects with no IPC cost.
- A `multiprocessing.Process` would need either shared-memory frame transfer or full numpy serialization, plus a separate Hailo VDevice — significant complexity for likely-small additional gain.

The `ReIDWorker` class has a narrow API (`submit_gallery_update`, `start`, `stop`) so swapping to a process-based implementation later is a contained change. Decision flagged in Task 6 — re-evaluate after measuring.

**Tech Stack:** Python `threading`, `queue.Queue`, existing `pytest` test layout under `drone_follow/tests/`.

**Out of scope:** Async `try_reidentify` (requires careful frame-delay handling — separate plan if needed); refactoring `reid_manager.py`'s internals; any change to the tracker or detection pipeline.

---

## File Structure

| Path | Status | Responsibility |
|---|---|---|
| `community/apps/hailo_drone_follow/drone_follow/pipeline_adapter/reid_worker.py` | **Create** | `ReIDWorker` class — daemon thread + bounded queue, calls into existing `ReIDManager.update_gallery` off the streaming thread. |
| `community/apps/hailo_drone_follow/drone_follow/tests/test_reid_worker.py` | **Create** | Unit tests for `ReIDWorker` lifecycle and submit/drop behavior. Uses a fake `ReIDManager` (no Hailo NPU). |
| `community/apps/hailo_drone_follow/drone_follow/pipeline_adapter/hailo_drone_detection_manager.py` | **Modify** | (a) Construct/store `reid_worker` in `DroneFollowUserData.__init__`. (b) Replace direct `reid_manager.update_gallery(...)` calls in `_app_callback_inner` with `reid_worker.submit_gallery_update(...)`. (c) Stop the worker on pipeline shutdown. |
| `community/apps/hailo_drone_follow/drone_follow/drone_api/mavsdk_drone.py` | **Modify** | Add `--reid-sync` CLI flag (action="store_true") so the old synchronous behavior can be restored at runtime if regressions appear. Default: async. |

---

## Task 1: ReIDWorker — failing tests

**Files:**
- Create: `community/apps/hailo_drone_follow/drone_follow/tests/test_reid_worker.py`

- [ ] **Step 1: Write the failing tests**

```python
# community/apps/hailo_drone_follow/drone_follow/tests/test_reid_worker.py
"""Unit tests for ReIDWorker — runs ReIDManager.update_gallery off the streaming thread."""

import threading
import time

import numpy as np
import pytest

from drone_follow.pipeline_adapter.reid_worker import ReIDWorker


class _FakeReIDManager:
    """Stand-in for ReIDManager — records calls and (optionally) blocks."""

    def __init__(self, sleep_s: float = 0.0):
        self._sleep_s = sleep_s
        self._calls = []
        self._lock = threading.Lock()

    def update_gallery(self, frame_bgr, hailo_bbox, video_width, video_height):
        if self._sleep_s:
            time.sleep(self._sleep_s)
        with self._lock:
            self._calls.append((frame_bgr.shape, hailo_bbox, video_width, video_height))

    @property
    def calls(self):
        with self._lock:
            return list(self._calls)


def _frame(h=720, w=1280):
    return np.zeros((h, w, 3), dtype=np.uint8)


def test_submit_returns_immediately_even_when_handler_is_slow():
    fake = _FakeReIDManager(sleep_s=0.1)
    worker = ReIDWorker(fake, max_queue=4)
    worker.start()
    try:
        t0 = time.monotonic()
        worker.submit_gallery_update(_frame(), object(), 1280, 720)
        elapsed = time.monotonic() - t0
        # Submit must not wait on the slow handler.
        assert elapsed < 0.02, f"submit blocked for {elapsed * 1000:.1f}ms"
    finally:
        worker.stop()


def test_worker_processes_submissions_off_caller_thread():
    fake = _FakeReIDManager()
    worker = ReIDWorker(fake, max_queue=4)
    worker.start()
    try:
        bbox = object()
        worker.submit_gallery_update(_frame(), bbox, 1280, 720)
        # Wait up to 1s for the worker to process.
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and not fake.calls:
            time.sleep(0.01)
        assert len(fake.calls) == 1
        shape, recv_bbox, w, h = fake.calls[0]
        assert shape == (720, 1280, 3)
        assert recv_bbox is bbox
        assert (w, h) == (1280, 720)
    finally:
        worker.stop()


def test_overflow_drops_oldest_to_keep_freshest_frame():
    """When the queue is full, the worker prefers the newest frame.

    Why: ReID gallery is most useful with current pixels — a stale frame buffered
    behind newer ones is worse than dropping it. Dropping NEWEST would defeat
    the point (old gallery never updates with current target appearance).
    """
    fake = _FakeReIDManager(sleep_s=0.5)  # blocks the worker so the queue fills
    worker = ReIDWorker(fake, max_queue=2)
    worker.start()
    try:
        # First submission starts running in the worker (queue empty).
        worker.submit_gallery_update(_frame(), "bbox-0", 1280, 720)
        # Next 3 fill+overflow the queue while the worker is asleep.
        for i in range(1, 4):
            worker.submit_gallery_update(_frame(), f"bbox-{i}", 1280, 720)
        # Let the worker drain.
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and len(fake.calls) < 3:
            time.sleep(0.01)
        seen_bboxes = [c[1] for c in fake.calls]
        # bbox-0 ran first; bbox-3 is the freshest and must NOT be dropped.
        assert "bbox-0" in seen_bboxes
        assert "bbox-3" in seen_bboxes
    finally:
        worker.stop()


def test_stop_is_idempotent_and_joins_thread():
    fake = _FakeReIDManager()
    worker = ReIDWorker(fake, max_queue=2)
    worker.start()
    worker.stop()
    worker.stop()  # second call is a no-op
    assert not worker.is_alive()


def test_submit_after_stop_is_silently_ignored():
    """Race-safe: pipeline may still emit one buffer between EOS and stop()."""
    fake = _FakeReIDManager()
    worker = ReIDWorker(fake, max_queue=2)
    worker.start()
    worker.stop()
    worker.submit_gallery_update(_frame(), object(), 1280, 720)
    time.sleep(0.05)
    assert fake.calls == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source /home/giladn/tappas_apps/repos/hailo-apps-infra/setup_env.sh
pytest community/apps/hailo_drone_follow/drone_follow/tests/test_reid_worker.py -v
```

Expected: 5 failures, all with `ImportError: cannot import name 'ReIDWorker'` (the module doesn't exist yet).

- [ ] **Step 3: Commit**

```bash
git add community/apps/hailo_drone_follow/drone_follow/tests/test_reid_worker.py
git commit -m "test: failing tests for ReIDWorker async dispatch"
```

---

## Task 2: ReIDWorker — implementation

**Files:**
- Create: `community/apps/hailo_drone_follow/drone_follow/pipeline_adapter/reid_worker.py`

- [ ] **Step 1: Write the implementation**

```python
# community/apps/hailo_drone_follow/drone_follow/pipeline_adapter/reid_worker.py
"""Background worker that runs ReIDManager.update_gallery off the GStreamer streaming thread.

The ReID gallery update involves a frame-buffer copy + an NPU embedding extraction.
Running it inline in app_callback adds per-frame latency to the streaming thread
and can cause back-pressure into the GStreamer pipeline. This worker decouples
the gallery update from the streaming thread by buffering submissions in a bounded
queue and processing them in a daemon thread.

Only update_gallery is async. try_reidentify stays synchronous in the callback —
its return value (a track_id from the current frame's person_by_id) must be applied
to the same frame, which would require frame-delay handling. Out of scope here.

Bounded queue + drop-oldest semantics: under sustained backpressure we keep the
freshest frame and drop the oldest pending one. A stale gallery embedding is
worse than no update — the gallery is supposed to track the target's *current*
appearance.
"""

import logging
import queue
import threading
from typing import Any, Optional

LOGGER = logging.getLogger(__name__)


class ReIDWorker:
    """Daemon-thread wrapper that calls ReIDManager.update_gallery asynchronously."""

    # Sentinel pushed onto the queue to signal shutdown.
    _STOP = object()

    def __init__(self, reid_manager: Any, max_queue: int = 2):
        """
        Args:
            reid_manager: object with `.update_gallery(frame_bgr, bbox, w, h)`.
            max_queue: maximum pending submissions. Beyond this, the OLDEST queued
                submission is dropped to make room for the new one.
        """
        self._reid_manager = reid_manager
        self._queue: queue.Queue = queue.Queue(maxsize=max_queue)
        self._thread: Optional[threading.Thread] = None
        self._stopped = threading.Event()
        self._dropped_count = 0
        self._dropped_lock = threading.Lock()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stopped.clear()
        self._thread = threading.Thread(
            target=self._run, name="reid-worker", daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        if self._thread is None:
            return
        self._stopped.set()
        try:
            self._queue.put_nowait(self._STOP)
        except queue.Full:
            # Make room for the sentinel.
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(self._STOP)
            except queue.Full:
                pass
        self._thread.join(timeout=timeout)
        self._thread = None

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def submit_gallery_update(self, frame_bgr, hailo_bbox, video_width: int,
                              video_height: int) -> None:
        """Enqueue a gallery-update job. Returns immediately.

        If the queue is full, the OLDEST pending submission is discarded.
        Submissions made after stop() are silently dropped.
        """
        if self._stopped.is_set() or self._thread is None:
            return
        item = (frame_bgr, hailo_bbox, video_width, video_height)
        try:
            self._queue.put_nowait(item)
            return
        except queue.Full:
            pass
        # Drop oldest, retry once.
        try:
            self._queue.get_nowait()
            with self._dropped_lock:
                self._dropped_count += 1
        except queue.Empty:
            pass
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            with self._dropped_lock:
                self._dropped_count += 1

    def dropped_count(self) -> int:
        with self._dropped_lock:
            return self._dropped_count

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is self._STOP:
                break
            frame_bgr, hailo_bbox, w, h = item
            try:
                self._reid_manager.update_gallery(frame_bgr, hailo_bbox, w, h)
            except Exception:
                LOGGER.exception("[reid-worker] update_gallery raised — continuing")
```

- [ ] **Step 2: Run tests to verify they pass**

```bash
pytest community/apps/hailo_drone_follow/drone_follow/tests/test_reid_worker.py -v
```

Expected: 5 passes.

- [ ] **Step 3: Commit**

```bash
git add community/apps/hailo_drone_follow/drone_follow/pipeline_adapter/reid_worker.py
git commit -m "feat: ReIDWorker — daemon thread for async gallery updates"
```

---

## Task 3: CLI flag `--reid-sync` (escape hatch)

**Files:**
- Modify: `community/apps/hailo_drone_follow/drone_follow/drone_api/mavsdk_drone.py:84-94` (the ReID arg group)

- [ ] **Step 1: Add a failing test for the flag**

Append to `community/apps/hailo_drone_follow/drone_follow/tests/test_reid_worker.py`:

```python
def test_cli_parser_has_reid_sync_flag_default_false():
    """--reid-sync exists and defaults to False (async is the default behavior)."""
    from drone_follow.drone_api.mavsdk_drone import build_parser
    parser = build_parser()
    args = parser.parse_args([])
    assert hasattr(args, "reid_sync")
    assert args.reid_sync is False

    args2 = parser.parse_args(["--reid-sync"])
    assert args2.reid_sync is True
```

- [ ] **Step 2: Verify it fails**

```bash
pytest community/apps/hailo_drone_follow/drone_follow/tests/test_reid_worker.py::test_cli_parser_has_reid_sync_flag_default_false -v
```

Expected: `AttributeError: 'Namespace' object has no attribute 'reid_sync'` (or AssertionError on `hasattr`).

- [ ] **Step 3: Add the flag**

In `community/apps/hailo_drone_follow/drone_follow/drone_api/mavsdk_drone.py`, find the existing ReID arg group (the `--no-reid` flag is around line 87) and add the new flag immediately after it:

```python
    group.add_argument(
        "--reid-sync", action="store_true",
        help="Run ReID gallery updates synchronously in the streaming "
             "thread (legacy behavior). Default: async via background worker.",
    )
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest community/apps/hailo_drone_follow/drone_follow/tests/test_reid_worker.py::test_cli_parser_has_reid_sync_flag_default_false -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add community/apps/hailo_drone_follow/drone_follow/drone_api/mavsdk_drone.py \
        community/apps/hailo_drone_follow/drone_follow/tests/test_reid_worker.py
git commit -m "feat: add --reid-sync CLI flag (escape hatch for async ReID)"
```

---

## Task 4: Wire ReIDWorker into the user-data lifecycle

`DroneFollowUserData.__init__` (in `hailo_drone_detection_manager.py:641`) does not have access to argparse args. Args are available in `drone_follow_app.py main()` after `app = create_app(...)`. The same pattern is used for `controller_config` and `test_log` (lines 224 and 226-228 of `drone_follow_app.py`). Follow that pattern: declare `self.reid_worker = None` on the user-data class; construct and start the worker from `main()` after app creation; stop it on shutdown.

**Files:**
- Modify: `community/apps/hailo_drone_follow/drone_follow/pipeline_adapter/hailo_drone_detection_manager.py:641-662` (`DroneFollowUserData.__init__`)
- Modify: `community/apps/hailo_drone_follow/drone_follow/drone_follow_app.py:208-228` (right after `app = create_app(...)`) and the shutdown path

- [ ] **Step 1: Add a `reid_worker` slot on the user-data class**

In `hailo_drone_detection_manager.py`, find `DroneFollowUserData.__init__` at line 641. After the line `self.reid_manager = reid_manager` (line 649) add:

```python
            # Filled in by drone_follow_app.main() after app creation. None when
            # ReID is disabled, the user passed --reid-sync, or there is no manager.
            self.reid_worker = None
```

- [ ] **Step 2: Construct/start the worker in `main()`**

In `drone_follow_app.py`, between line 224 (`app.user_data.controller_config = controller_config`) and line 226 (`test_log_path = ...`), add:

```python
    # Async ReID gallery worker. None when --no-reid (no manager) or --reid-sync.
    if reid_manager is not None and not getattr(args, "reid_sync", False):
        from drone_follow.pipeline_adapter.reid_worker import ReIDWorker
        app.user_data.reid_worker = ReIDWorker(reid_manager, max_queue=2)
        app.user_data.reid_worker.start()
```

- [ ] **Step 3: Stop the worker on shutdown**

In `drone_follow_app.py`, find the cleanup path after the GStreamer loop exits. The pattern parallel to `app.user_data.close_test_log()` (defined at `hailo_drone_detection_manager.py:669`). Look for where `close_test_log` is called in `drone_follow_app.py` (search for `close_test_log`). Add the worker stop **immediately before** or **next to** the existing `close_test_log()` call:

```python
    if app.user_data.reid_worker is not None:
        app.user_data.reid_worker.stop(timeout=2.0)
        app.user_data.reid_worker = None
```

If `close_test_log()` is not called from `drone_follow_app.py` (only from inside the user-data class via `--test-log` lifecycle), put the worker-stop right after the `app.run()` / GLib loop exit instead. Use `grep -n 'app\\.user_data\\|app\\.run\\|loop\\.run' community/apps/hailo_drone_follow/drone_follow/drone_follow_app.py` to locate the loop exit point.

- [ ] **Step 4: Smoke-import test**

```bash
source /home/giladn/tappas_apps/repos/hailo-apps-infra/setup_env.sh
python -c "from drone_follow.pipeline_adapter.hailo_drone_detection_manager import app_callback; print('ok')"
python -c "from drone_follow.pipeline_adapter.reid_worker import ReIDWorker; print('ok')"
```

Expected: `ok` printed twice.

- [ ] **Step 5: Run existing tests to confirm nothing regressed**

```bash
pytest community/apps/hailo_drone_follow/drone_follow/tests/ -v
```

Expected: all tests pass (existing + new `test_reid_worker.py`).

- [ ] **Step 6: Commit**

```bash
git add community/apps/hailo_drone_follow/drone_follow/pipeline_adapter/hailo_drone_detection_manager.py \
        community/apps/hailo_drone_follow/drone_follow/drone_follow_app.py
git commit -m "feat: own ReIDWorker lifecycle in DroneFollowUserData"
```

---

## Task 5: Swap call sites in `_app_callback_inner`

**Files:**
- Modify: `community/apps/hailo_drone_follow/drone_follow/pipeline_adapter/hailo_drone_detection_manager.py:315-322` (the `update_gallery` call inside the "successfully tracking target" branch)

There is exactly one `update_gallery` call site. The other ReID call (`try_reidentify` at line 340) stays synchronous — see plan goals.

- [ ] **Step 1: Replace the synchronous gallery update call**

Current code at lines 315-322:

```python
            # ReID: build/update gallery while following (auto or locked)
            if reid_manager is not None:
                reid_manager.on_target_selected(target_id)
                if reid_manager.should_update():
                    frame_bgr = get_frame_bgr(buffer, user_data.video_width, user_data.video_height)
                    if frame_bgr is not None:
                        reid_manager.update_gallery(
                            frame_bgr, best.get_bbox(),
                            user_data.video_width, user_data.video_height)
```

Replace with:

```python
            # ReID: build/update gallery while following (auto or locked).
            # Gallery update is offloaded to ReIDWorker when --reid-sync is not set.
            if reid_manager is not None:
                reid_manager.on_target_selected(target_id)
                if reid_manager.should_update():
                    frame_bgr = get_frame_bgr(buffer, user_data.video_width, user_data.video_height)
                    if frame_bgr is not None:
                        if user_data.reid_worker is not None:
                            user_data.reid_worker.submit_gallery_update(
                                frame_bgr, best.get_bbox(),
                                user_data.video_width, user_data.video_height)
                        else:
                            reid_manager.update_gallery(
                                frame_bgr, best.get_bbox(),
                                user_data.video_width, user_data.video_height)
```

- [ ] **Step 2: Run the existing test suite**

```bash
pytest community/apps/hailo_drone_follow/drone_follow/tests/ -v
```

Expected: all existing tests still pass + the 6 new `reid_worker` tests pass.

- [ ] **Step 3: Smoke-run the app for ~10s with the file profile we already used**

```bash
source /home/giladn/tappas_apps/repos/hailo-apps-infra/setup_env.sh
drone-follow --ui --no-display \
    --input /usr/local/hailo/resources/videos/tiling_visdrone_720p.mp4 \
    --mission-duration 10
```

Expected: app starts, runs, exits 0. Check logs for any `[reid-worker]` exceptions; there should be none.

- [ ] **Step 4: Commit**

```bash
git add community/apps/hailo_drone_follow/drone_follow/pipeline_adapter/hailo_drone_detection_manager.py
git commit -m "feat: route ReID gallery updates through ReIDWorker by default"
```

---

## Task 6: Profile-validate the change

**Files:** none (measurement only — generates trace dirs that are git-ignored locally).

- [ ] **Step 1: Capture a baseline run on the SAME conditions we used pre-change**

If the previous baseline trace (from `2026-04-30_15:24:06`) is still on disk, you can reuse it. Otherwise:

```bash
git stash  # only if there are uncommitted changes
git checkout main -- community/apps/hailo_drone_follow/drone_follow/pipeline_adapter/hailo_drone_detection_manager.py
source /home/giladn/tappas_apps/repos/hailo-apps-infra/setup_env.sh
python /home/giladn/tappas_apps/repos/hailo-apps-infra/.claude/skills/profile-pipeline/scripts/profile_pipeline.py \
    community/apps/hailo_drone_follow/drone_follow/drone_follow_app.py \
    --duration 15 \
    -- --ui --no-display \
       --input /usr/local/hailo/resources/videos/tiling_visdrone_720p.mp4 \
       --mission-duration 15
git checkout HEAD -- community/apps/hailo_drone_follow/drone_follow/pipeline_adapter/hailo_drone_detection_manager.py
git stash pop  # if you stashed
```

Note the trace dir printed at the end (call it `BASELINE_TRACE`).

- [ ] **Step 2: Capture a post-change run on the same conditions**

```bash
python /home/giladn/tappas_apps/repos/hailo-apps-infra/.claude/skills/profile-pipeline/scripts/profile_pipeline.py \
    community/apps/hailo_drone_follow/drone_follow/drone_follow_app.py \
    --duration 15 \
    -- --ui --no-display \
       --input /usr/local/hailo/resources/videos/tiling_visdrone_720p.mp4 \
       --mission-duration 15
```

Note the trace dir (call it `EXPERIMENT_TRACE`).

- [ ] **Step 3: Compare**

```bash
python /home/giladn/tappas_apps/repos/hailo-apps-infra/.claude/skills/profile-pipeline/scripts/compare_traces.py \
    "$BASELINE_TRACE" "$EXPERIMENT_TRACE" --format text | tee compare_reid_async.txt
```

Look for:
- `identity_callback` proctime — should drop (the gallery copy + extract is gone from the streaming thread).
- Source/cropper/inference pad event counts — should be **higher** if the callback was a real throttle.
- CPU usage — likely similar overall (work is the same, just on a different thread); if much higher, the worker thread is busy-looping (regression — investigate before merging).
- Queue fills on `source_*_q` and `tile_cropper_wrapper_input_q` — should drop if the callback was the choke.

- [ ] **Step 4: Decision point**

If `identity_callback` proctime drops materially **but** event counts (throughput) don't increase: the callback was not the throughput throttle. Open a follow-up plan to investigate. Still merge this — the architecture change is correct on its own (lower jitter, smaller jitter tail).

If throughput increases significantly: ship it.

If throughput decreases or `[reid-worker]` exceptions appear in logs: revert (`git revert HEAD~5..HEAD`) and revisit. Possible cause: NPU contention — the ReID extractor and the detection hailonet share the VDevice and the worker's NPU calls may be racing. Check `hailortcli` and `vdevice_group_id` settings.

- [ ] **Step 5: Commit the comparison artifact (only if it shipped)**

```bash
git add compare_reid_async.txt
git commit -m "docs: record before/after profile for async ReID gallery"
```

(If you'd rather not commit raw profile output, skip this step. The plan's measurement story is self-contained.)

---

## Self-Review Checklist (before claiming the plan is done)

- [ ] All 6 tasks have concrete code/commands — no "TBD" or placeholders.
- [ ] Each task starts and ends with a commit.
- [ ] Tests are written before implementation (Task 1 → 2, Task 3.1 → 3.3).
- [ ] The CLI flag `--reid-sync` provides a runtime escape hatch.
- [ ] Error path: worker exceptions are logged, not propagated (see `_run` in Task 2).
- [ ] Shutdown is idempotent (`stop()` can be called twice safely).
- [ ] The synchronous-fallback path remains identical to the pre-change behavior.
- [ ] No change to `try_reidentify` — explicitly out of scope and noted in the docstring.
- [ ] Profile validation is part of the plan, not optional.
