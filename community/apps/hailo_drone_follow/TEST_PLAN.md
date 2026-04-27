# Test Plan — drone-follow

## Current State

**107 tests** across 6 files, focused heavily on the `follow_api` domain layer.

| File | Tests | Module Covered |
|------|-------|----------------|
| `test_controller.py` | 54 | `follow_api.controller` — yaw, forward, altitude, safety, orbit, search |
| `test_velocity_api_and_smoother.py` | 17 | `drone_api.VelocityCommandAPI` — clamping, EMA, slew-rate |
| `test_follow_target_state.py` | 14 | `follow_api.state.FollowTargetState` — set/get/clear, concurrency |
| `test_shared_state.py` | 13 | `follow_api.state.SharedDetectionState` — update, snapshot, concurrency |
| `test_follow_server.py` | 12 | `servers.FollowServer` — REST endpoints, CORS, error codes |
| `test_config_persistence.py` | 11 | `follow_api.config.ControllerConfig` — JSON roundtrip, validation |

### What's well covered

- **Controller logic** — comprehensive: dead zones, saturation, FOV scaling, emergency safety, orbit, search direction. This is the most safety-critical pure logic and it's solid.
- **State management** — thread safety verified with concurrent read/write tests.
- **Velocity smoothing** — EMA convergence, per-axis alpha, slew-rate limiting, filter reset.
- **Config persistence** — save/load roundtrip, rollback on invalid mutation, unknown-key tolerance.

### What's missing

The entire hardware-adapter layer and the integration between components have zero test coverage:

| Module | Lines (approx) | Tests |
|--------|----------------|-------|
| `pipeline_adapter/byte_tracker.py` | ~200 | 0 |
| `pipeline_adapter/hailo_drone_detection_manager.py` | ~400 | 0 |
| `pipeline_adapter/reid_manager.py` | ~150 | 0 |
| `servers/web_server.py` | ~300 | 0 |
| `servers/openhd_bridge.py` | ~200 | 0 |
| `drone_api/mavsdk_drone.py` (flight loop) | ~200 | 0 |
| `drone_follow_app.py` (composition root) | ~270 | 0 |
| `follow_api/perf_tracker.py` | ~150 | 0 |

---

## Test Plan

Tests are organized into tiers by dependency complexity. Each tier builds on the one before — start from Tier 1.

### Tier 1 — Pure Logic (no mocks needed)

These test modules with zero external dependencies. They exercise algorithms and data transformations using only standard-library types.

#### 1.1 ByteTracker Kalman Filter

**File:** `tests/test_byte_tracker.py`  
**Source:** `pipeline_adapter/byte_tracker.py`

| # | Test | Why it matters |
|---|------|----------------|
| 1 | `KalmanFilter.initiate()` returns correct state shape (10-d) and covariance | Catches dimension mismatches after refactors |
| 2 | `predict()` advances position by velocity (1-step, known state) | Core correctness of the motion model |
| 3 | `predict()` over N steps without measurement diverges predictably | Validates process noise tuning |
| 4 | `update()` with exact measurement snaps state to measurement | Proves measurement weighting works |
| 5 | `update()` with noisy measurement moves state partially toward measurement | Gain is between 0 and 1 |
| 6 | `gating_distance()` returns small value for nearby measurement | Association depends on this |
| 7 | `gating_distance()` returns large value for distant measurement | Rejection depends on this |
| 8 | `project()` output covariance is positive definite | Numerical stability guard |

#### 1.2 ByteTracker Association

| # | Test | Why it matters |
|---|------|----------------|
| 9 | Single detection, single track → matched | Happy path |
| 10 | Two detections, two tracks, non-overlapping → both matched correctly | IoU assignment correctness |
| 11 | Detection far from all tracks → unmatched detection | New-track creation trigger |
| 12 | Track with no nearby detection → unmatched track | Lost-track handling |
| 13 | Overlapping detections (high IoU) → correct 1:1 assignment | Hungarian algorithm correctness |
| 14 | Zero detections → all tracks become unmatched | Frame-drop resilience |
| 15 | 20+ detections → completes in < 50 ms | O(N³) Hungarian won't choke in crowds |

#### 1.3 Config Argument Parsing

**File:** `tests/test_config_args.py`  
**Source:** `follow_api/config.py`

| # | Test | Why it matters |
|---|------|----------------|
| 16 | `from_args()` with no flags → all defaults match dataclass | CLI doesn't silently override defaults |
| 17 | `from_args()` with `--kp-yaw 8.0` → kp_yaw == 8.0 | Flag wiring correctness |
| 18 | `from_args()` with `--config some.json` → values loaded from file | Config file precedence |
| 19 | CLI flag overrides value from config file | Precedence: CLI > file > default |
| 20 | Unknown CLI flag → argparse error (not silently ignored) | Catches typos in deployment scripts |
| 21 | `--yaw-only` and `--no-yaw-only` → correct bool values | Boolean flag pairs |
| 22 | FOV values outside [1, 179] → validation error | Prevents nonsensical geometry |

#### 1.4 Detection & VelocityCommand Data Types

**File:** `tests/test_types.py`  
**Source:** `follow_api/types.py`

| # | Test | Why it matters |
|---|------|----------------|
| 23 | Detection with all fields → attributes accessible | Dataclass wiring |
| 24 | VelocityCommand defaults to all zeros | Safety: uninitialized command = hold |
| 25 | FollowMode enum has AUTO, LOCKED, IDLE | Mode semantics relied on everywhere |

---

### Tier 2 — Component Tests (light mocking)

These test individual components by mocking only their direct hardware dependencies (Hailo, MAVSDK, GStreamer). The component's own logic runs for real.

#### 2.1 ReID Manager

**File:** `tests/test_reid_manager.py`  
**Source:** `pipeline_adapter/reid_manager.py`

Mock the Hailo inference call (`_extract_embeddings`) to return synthetic embedding vectors. Everything else (gallery, matching, timeout) runs for real.

| # | Test | Why it matters |
|---|------|----------------|
| 26 | Gallery starts empty | No stale state from previous runs |
| 27 | `update_gallery()` with one person → gallery has 1 embedding | Basic gallery population |
| 28 | `update_gallery()` called 15 times → gallery capped at 10 (FIFO eviction) | Memory bound respected |
| 29 | `identify()` with matching embedding → returns correct track ID | Happy-path re-identification |
| 30 | `identify()` with dissimilar embedding → returns None | False-positive rejection |
| 31 | `identify()` with similarity just below threshold → returns None | Threshold boundary |
| 32 | `identify()` with similarity just above threshold → returns match | Threshold boundary |
| 33 | `is_timed_out()` returns False within timeout window | Search continues |
| 34 | `is_timed_out()` returns True after timeout expires | Fallback to AUTO triggered |
| 35 | `clear_gallery()` → subsequent `identify()` returns None | Clean state on new target |
| 36 | Gallery update skipped when frame count < update_interval | Rate limiting works |
| 37 | Gallery update runs on first frame (immediate capture) | Lock-on gets embedding immediately |

#### 2.2 OpenHD Bridge

**File:** `tests/test_openhd_bridge.py`  
**Source:** `servers/openhd_bridge.py`

Mock the UDP socket. Test JSON serialization, parameter mapping, and config mutation.

| # | Test | Why it matters |
|---|------|----------------|
| 38 | Incoming `follow_id = -1` → FollowTargetState enters IDLE | OpenHD ground station control works |
| 39 | Incoming `follow_id = 0` → enters AUTO mode | Mode mapping |
| 40 | Incoming `follow_id = 5` → locks to person 5 | Lock-on from ground station |
| 41 | Incoming `bitrate = 5000` → encoder bitrate updated | Dynamic bitrate adaptation |
| 42 | Incoming `recording = 1` → recording starts | Remote recording control |
| 43 | Parameter readback includes all current values | QOpenHD UI stays in sync |
| 44 | Malformed JSON → logged, no crash | Resilience to corrupt UDP packets |
| 45 | Unknown parameter key → ignored, logged | Forward compatibility |
| 46 | Config mutation persisted to disk | Survives restart |

#### 2.3 Web Server (SharedUIState)

**File:** `tests/test_web_server.py`  
**Source:** `servers/web_server.py`

Test `SharedUIState` thread safety and the HTTP endpoints (using the server's test client if available, or direct function calls).

| # | Test | Why it matters |
|---|------|----------------|
| 47 | `SharedUIState` frame update is atomic with detection snapshot | UI never shows bbox from frame N on frame N+1 |
| 48 | `get_status()` returns mode, velocities, FPS | Status bar data correct |
| 49 | Click-to-follow POST with valid bbox → target set + bbox captured | Core UI interaction |
| 50 | Click-to-follow POST with invalid coordinates → 400 | Input validation |
| 51 | Concurrent frame updates (10 threads) → no corruption | Production threading model |
| 52 | MJPEG endpoint returns multipart content-type header | Browser compatibility |

#### 2.4 Perf Tracker

**File:** `tests/test_perf_tracker.py`  
**Source:** `follow_api/perf_tracker.py`

| # | Test | Why it matters |
|---|------|----------------|
| 53 | CPU/memory sampling returns plausible values | Metrics pipeline works |
| 54 | FPS calculation from frame timestamps is correct | Reported FPS matches reality |
| 55 | Hailo monitor file missing → graceful None, no crash | Runs on machines without Hailo |
| 56 | Hailo monitor file with unexpected format → graceful None | HailoRT version changes |
| 57 | Frame latency computed correctly from callback timestamps | Latency metric accuracy |

---

### Tier 3 — Integration Tests

These wire together multiple real components to verify end-to-end data flow. External hardware (Hailo, MAVSDK, GStreamer) is mocked at the boundary.

#### 3.1 Detection → Controller → Velocity Pipeline

**File:** `tests/test_detection_to_velocity.py`

Wire: `SharedDetectionState` → `compute_velocity_command()` → `VelocityCommandAPI`

| # | Test | Why it matters |
|---|------|----------------|
| 58 | Person centered in frame → near-zero velocity output | Stable hover when on-target |
| 59 | Person moves left → positive yaw, then returns to zero when recentered | Closed-loop yaw tracking |
| 60 | Person disappears for 5 frames → search yaw starts | Lost-target recovery |
| 61 | Person reappears after search → yaw snaps back, velocity resumes | Search → track transition |
| 62 | Large person (bbox > 0.8) → emergency climb + backward | Safety pipeline end-to-end |
| 63 | Sequence of 100 random detections → velocity always within limits | Invariant: no output exceeds max velocity after smoothing |
| 64 | Yaw-only mode → forward and altitude always zero regardless of detection | Mode enforcement end-to-end |

#### 3.2 ReID Recovery Path

**File:** `tests/test_reid_recovery.py`

Wire: detection callback logic → ReIDManager → FollowTargetState

| # | Test | Why it matters |
|---|------|----------------|
| 65 | Target lost, same person reappears with different track ID → re-identified, follow continues | Core ReID value proposition |
| 66 | Target lost, different person appears → not matched, search continues | False-positive rejection in context |
| 67 | Target lost, timeout expires → mode returns to AUTO, gallery cleared | Timeout recovery |
| 68 | Target lost then found, ID remap is transparent to UI | UI shows stable ID throughout |

#### 3.3 Follow Server + FollowTargetState + ReID

**File:** `tests/test_follow_server_integration.py`

Wire the real FollowServer to real state objects, with mock ReID.

| # | Test | Why it matters |
|---|------|----------------|
| 69 | POST /follow/3 → target set, ReID gallery cleared for new target | Lock-on cleans up previous target |
| 70 | POST /follow/clear → AUTO mode, gallery cleared | Explicit clear triggers cleanup |
| 71 | GET /status during ReID search → reports "searching" | Operator knows what's happening |
| 72 | POST /follow/3 while already following 3 → no-op, no gallery reset | Idempotent lock |

#### 3.4 CLI Argument → Runtime Wiring

**File:** `tests/test_app_wiring.py`

Test that CLI arguments result in correct component configuration, without starting GStreamer or MAVSDK.

| # | Test | Why it matters |
|---|------|----------------|
| 73 | `--yaw-only` → ControllerConfig.yaw_only == True, forward always 0 | Flag → behavior |
| 74 | `--target-altitude 5` → VelocityCommandAPI altitude target == 5 | Altitude flag wiring |
| 75 | `--serial` → connection string is `serial:///dev/ttyACM0:57600` | Serial connection construction |
| 76 | `--serial /dev/ttyUSB0 --serial-baud 115200` → correct string | Custom serial params |
| 77 | `--record` → recording branch enabled | Recording flag wiring |
| 78 | `--openhd-stream` → OpenHD pipeline elements present | OpenHD flag wiring |
| 79 | No `--serial`, no `--connection` → defaults to `udpin://0.0.0.0:14540` | Simulation default |

---

### Tier 4 — Simulation Tests (optional, slow)

Run against PX4 SITL + Gazebo. These are not part of the fast test suite — they're gated behind `@pytest.mark.sim` and require the simulation stack to be running.

| # | Test | Why it matters |
|---|------|----------------|
| 80 | Connect to SITL, send zero setpoints for 5s, no crash | MAVSDK connection lifecycle |
| 81 | Arm + takeoff to 3m, verify altitude within ±0.5m | Takeoff sequence |
| 82 | Send yaw command, verify heading changes | Offboard yaw control |
| 83 | Send forward command, verify position changes | Offboard velocity control |
| 84 | Kill offboard setpoints → PX4 failsafe triggers within COM_OF_LOSS_T | Failsafe verification |
| 85 | Full scenario: takeoff → detect person → follow → land | End-to-end flight |

---

## Infrastructure Improvements

### Fixtures & Helpers Needed

- **`conftest.py` fixtures:**
  - `default_config` — fresh `ControllerConfig()` with test-friendly defaults
  - `mock_hailo_inference` — patches Hailo inference to return synthetic embeddings
  - `follow_state` — pre-wired `FollowTargetState` + `SharedDetectionState`
  - `udp_echo_server` — for OpenHD bridge tests

- **Test data factory:**
  - `make_detection(center_x=0.5, center_y=0.5, bbox_height=0.3, track_id=1)` — builds `Detection` objects with sensible defaults

### Markers

```ini
# pytest.ini
[pytest]
markers =
    unit: Pure logic, no I/O (default, fast)
    component: Single component with mocked dependencies
    integration: Multiple components wired together
    sim: Requires PX4 SITL (slow, opt-in)
```

### CI Configuration

```yaml
# Run fast tests on every push
pytest -m "not sim" --timeout=10

# Run sim tests nightly or on-demand
pytest -m sim --timeout=120
```

---

## Priority Order

If implementing incrementally, this is the recommended order based on risk-reduction per effort:

1. **ByteTracker Kalman filter** (Tier 1.1) — pure math, easy to test, catches numerical regressions
2. **ReID Manager** (Tier 2.1) — core recovery feature, currently untestable regressions
3. **Detection → Controller → Velocity pipeline** (Tier 3.1) — end-to-end invariants are the highest-value integration tests
4. **OpenHD Bridge** (Tier 2.2) — field-deployment interface, hard to debug live
5. **Config argument parsing** (Tier 1.3) — prevents deployment misconfigurations
6. **ReID recovery path** (Tier 3.2) — validates the full lost-target → re-identification → resume flow
7. **Web server state** (Tier 2.3) — UI correctness, thread safety
8. **Perf tracker** (Tier 2.4) — low risk, but fragile protobuf parsing should be guarded
9. **CLI wiring** (Tier 3.4) — catches flag→behavior disconnects
10. **Simulation tests** (Tier 4) — highest value but highest setup cost
