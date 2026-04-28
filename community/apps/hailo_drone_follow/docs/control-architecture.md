# Drone Control Architecture

How `drone-follow` turns a camera stream into drone motion — from a person detection to a MAVLink velocity setpoint — and the parameters that shape every step.

Audience: someone who wants to understand or tune the control loop, not someone onboarding to the codebase generally.

---

## 1. Control pipeline, end-to-end

```
 GStreamer pipeline (Hailo NPU)        Thread-safe bridge                 Async control loop                     MAVSDK                PX4
 ──────────────────────────────        ─────────────────                  ──────────────────                     ──────                ───
 camera / SHM / udp                                                                                                                       
      │                                                                                                                                   
      ▼                                                                                                                                   
 hailo-inference (YOLO) ─► ByteTracker ─► app_callback ─► SharedDetectionState.update(Detection)                                          
                                         (pipeline_adapter/                                                                                
                                          hailo_drone_detection_manager.py)                                                                
                                                                    │                                                                      
                                                                    ▼                                                                      
                                                           10 Hz loop                                                                      
                                                   shared_state.get_latest()                                                               
                                                                    │                                                                      
                                                                    ▼                                                                      
                                                   compute_velocity_command(...)  ◄── ControllerConfig                                     
                                                   (follow_api/controller.py)                                                              
                                                   center_x → yaw,                                                                       
                                                   bbox_height → forward (distance);                                                       
                                                   down=0 (PX4 alt-hold downstream)                                                        
                                                                    │                                                                      
                                                                    ▼                                                                      
                                            altitude floor/ceiling clamp    (min_altitude..max_altitude)                                   
                                                                    │                                                                      
                                                                    ▼                                                                      
                                               VelocityCommandAPI.send()  ──► drone.offboard.set_velocity_body()                           
                                               (clamp + per-axis EMA)       (mavsdk_drone.py)                                              
                                                                                                  │                                        
                                                                                                  ▼                                        
                                                                                    MAVLink SET_POSITION_TARGET_LOCAL_NED                  
                                                                                    (body frame, velocity-only mask, yawspeed)             
                                                                                                  │                                        
                                                                                                  ▼                                        
                                                                                    PX4 OFFBOARD → mc_pos_control                          
```

Key idea: the app does NOT command attitude, thrust, waypoints, or position. It emits **one 4-DOF velocity setpoint per tick in the drone body frame**, and PX4's position controller does the rest. This is the standard MAVLink/PX4 offboard pattern for companion computers.

---

## 2. The one primitive: body-frame velocity + yawrate

Every control output is a `VelocityCommand` (`follow_api/types.py`):

```python
@dataclass
class VelocityCommand:
    forward_m_s:     float   # +X body (nose direction)
    right_m_s:       float   # +Y body (starboard)
    down_m_s:        float   # +Z body (down is positive — NED convention)
    yawspeed_deg_s:  float   # +ve = clockwise viewed from above
```

Sent via `mavsdk.offboard.VelocityBodyYawspeed`, which maps to MAVLink's `SET_POSITION_TARGET_LOCAL_NED` with:
- coordinate frame = `MAV_FRAME_BODY_NED`
- type mask = position+acceleration ignored, velocity + yawrate only

This is the **standard** offboard primitive recommended by PX4 for vision-based follow applications. Reference: https://docs.px4.io/main/en/flight_modes/offboard.html

The app never touches:
- setpoint_raw_attitude
- position targets (waypoints)
- thrust / actuator controls
- flight-mode switches (except `takeoff` / `land` when `--takeoff-landing` is passed)

---

## 3. Tracking input → four axes of output

The detection arriving at the control loop (`Detection` in `follow_api/types.py`) has four normalized scalars:

| Field | Range | Meaning |
|---|---|---|
| `center_x` | 0..1 | bbox centre x (0 = left, 1 = right) |
| `center_y` | 0..1 | bbox centre y (0 = top, 1 = bottom) |
| `bbox_height` | 0..1 | bbox height as fraction of frame height |
| `confidence` | 0..1 | detector confidence |

The controller maps these to the four output axes:

### 3.1 Yaw (`yawspeed_deg_s`) ← `center_x`

```python
error_x_deg = (center_x - 0.5) * hfov        # signed angular offset
if |error_x_deg| < dead_zone_deg:
    yawspeed = 0
else:
    yawspeed = sign(error_x_deg) * kp_yaw * sqrt(|error_x_deg|)
yawspeed = clamp(yawspeed, ±max_yawspeed)
# then: EMA low-pass filter in VelocityCommandAPI (yaw_alpha)
```

- **P controller with a square-root response** — softer near zero error, still quick on large errors.  Standard practice in vision-servo yawing to avoid the step-step-step feeling of pure-P at low gain.
- **Dead zone** (`dead_zone_deg = 2°`) suppresses jitter from noisy detections.
- **EMA low-pass** (`yaw_alpha = 0.3`) in `VelocityCommandAPI.send()` — filters the commanded yawspeed before it hits MAVSDK. All four axes have per-axis EMA in `send()`: yaw (α=0.3), forward (α=0.15), right (α=0.3), down (α=0.2).

### 3.2 Forward / backward (`forward_m_s`) ← `bbox_height`

Distance-error P on `(target_bbox_height / bbox_height) - 1`. Since
`bbox ∝ 1/distance`, this factor *is* the relative distance error: a person
at 2× the target distance gives factor=1 regardless of absolute bbox size.
The response is therefore scale-invariant.

```python
# Safety: bbox too large → emergency reverse (and yaw still tracks)
if bbox_height > max_bbox_height_safety:     # default 0.8
    return -max_backward

factor = (target_bbox_height / bbox_height) - 1.0   # +ve = too far, -ve = too close
dead_zone = dead_zone_bbox_percent / 100             # default 0.10 → ±10% of target
if abs(factor) < dead_zone:
    return 0.0

raw = kp_distance * factor
forward = clamp(raw, -max_backward, max_forward)

# Per-axis EMA in VelocityCommandAPI: forward_alpha = 0.15
smoothed = alpha * forward + (1 - alpha) * prev_smoothed
```

Frame-edge safety (`top_margin_safety`, `bottom_margin_safety`) overrides the
natural command when the bbox top/bottom enters a margin band — see
`_apply_frame_edge_safety` in `controller.py`.

### 3.3 Altitude (`down_m_s`) — held by PX4

The controller emits `down_m_s = 0`. Altitude is held by an alt-hold P-loop
in `live_control_loop` (`mavsdk_drone.py`) on `(current_alt - target_altitude)`
with gain `kp_alt_hold` (default 0.5), clamped to
`[-max_climb_speed, max_down_speed]`. The down command is also clamped to
zero at `min_altitude` (no further descent) and `max_altitude` (no further
climb). `target_altitude` doubles as the takeoff height when
`--takeoff-landing` is set, and is adjustable mid-flight via the UI.

### 3.4 Lateral (`right_m_s`) ← orbit mode

Only non-zero when `follow_mode == "orbit"`:

```python
right = orbit_speed_m_s * orbit_direction   # direction = ±1
```

Constant lateral velocity while yaw keeps the person centred → drone orbits the subject. Standard cinematographic follow pattern.

In default `follow` mode, `right_m_s = 0`.

---

## 4. Modes (finite-state machine around the same controller)

The control loop itself has no explicit FSM — it computes a command based on (detection, last detection, time-since-detection). But externally it behaves as:

| Mode | Entered when | Behaviour |
|---|---|---|
| **TRACK** | valid detection <0.5s old | full 4-axis command as above |
| **SEARCH-WAIT** | no detection for <2s | hold last command (`hold_velocity = _prev_cmd`) |
| **SEARCH** | no detection for ≥2s | slow yaw spin toward last-seen side at `search_yawspeed_slow = 10°/s`, dampened forward |
| **IDLE** | operator pressed pause in UI | `shared_state.update(None)` + the loop treats it as "no detection, no search" → hovers |
| **ORBIT** | `follow_mode = "orbit"` | same as TRACK but with constant lateral velocity |
| **Landing** | search timeout (60s) exceeded | shutdown + `action.land()` |

TRACK ↔ SEARCH transitions are naturally hysteretic because `detection_timeout_s = 0.5` and `search_enter_delay_s = 2.0` — different thresholds for "lost" vs "start spinning".

---

## 5. How parameters map to behaviour

The following table gives a field-tuner's view of what to change when. Every value below is a field on `ControllerConfig` (`follow_api/config.py`), settable via CLI flag, JSON file (`--config`), or the web UI's POST `/config` endpoint.

### Framing & target size
| Param | Default | Tune if |
|---|---|---|
| `hfov` / `vfov` | 66 / 41 ° | Camera FOV changed |
| `target_bbox_height` | 0.3 | Want subject bigger/smaller in frame (drives forward/back distance) |

### Yaw
| Param | Default | Tune if |
|---|---|---|
| `kp_yaw` | 5.0 | Yaw too slow / too twitchy |
| `dead_zone_deg` | 2 ° | Twitching on a still target |
| `max_yawspeed` | 90 °/s | Too aggressive on fast cuts |
| `yaw_alpha` (EMA) | 0.3 | 0 = never responds, 1 = no smoothing |

### Forward / backward (bbox_height → forward_m_s)
| Param | Default | Tune if |
|---|---|---|
| `kp_distance` | 1.0 | Approach/retreat too slow; raise cautiously |
| `dead_zone_bbox_percent` | 10 % | Oscillating → widen; unresponsive → narrow |
| `max_forward` / `max_backward` | 2.0 / 3.0 m/s | Hard cap on speeds |
| `max_forward_accel` | 1.5 m/s² | Slew-rate cap (tilt-transient safety) |
| `forward_alpha` (EMA) | 0.15 | Lower = more pitch-oscillation attenuation, more phase lag |
| `max_bbox_height_safety` | 0.8 | Hard emergency reverse threshold |
| `top_margin_safety` / `bottom_margin_safety` | 0.10 / 0.10 | Frame-edge safety bands (0 disables) |

### Altitude (held by PX4 alt-hold)
| Param | Default | Tune if |
|---|---|---|
| `target_altitude` | 3.0 m | Takeoff height (with `--takeoff-landing`); also UI-adjustable mid-flight |
| `kp_alt_hold` | 0.5 | Alt-hold P gain in live_control_loop |
| `max_climb_speed` | 1.0 m/s | Max altitude change rate |
| `max_down_speed` | 1.5 m/s | Safety clamp on the down axis |
| `min_altitude` / `max_altitude` | 2 / 4 m | Hard floor/ceiling enforced by live_control_loop |
| `down_alpha` (EMA) | 0.2 | 0 = very smooth, 1 = no smoothing |

### Search behaviour
| Param | Default | Tune if |
|---|---|---|
| `search_enter_delay_s` | 2.0 | Too quick/slow to start spinning |
| `search_yawspeed_slow` | 10 °/s | Spin too fast/slow |
| `search_timeout_s` | 60 s | Give up and land |
| `search_vel_damp` | 0.3 | Dampen forward during search |

### Orbit
| Param | Default | Tune if |
|---|---|---|
| `orbit_speed_m_s` | 1.0 | Orbit radius / speed |
| `orbit_direction` | +1 | CW / CCW |

### Safety / flight envelope
| Param | Default | Notes |
|---|---|---|
| `yaw_only` | True | Safest default — no translation |
| `control_loop_hz` | 10 Hz | Rarely needs tuning |
| `detection_timeout_s` | 0.5 | Staleness cutoff for a detection |

### Runtime mutation
All of the above fields (those exposed in `_CONFIG_FIELDS` in `servers/web_server.py`) can be changed at runtime via the UI. The control loop reads `config.*` every tick, so a mid-flight edit takes effect within one control period.

---

## 6. OFFBOARD integration with PX4

Two flight-lifecycle modes, controlled by `--takeoff-landing`:

### Default: pilot-managed lifecycle (recommended)
- Drone is already airborne under RC or another autonomous mode.
- App connects, streams `VelocityBodyYawspeed(0,0,0,0)` at 20 Hz as a keep-alive setpoint.
- Pilot switches the flight mode to OFFBOARD via GCS/RC.
- On OFFBOARD detection (`telemetry.flight_mode() == OFFBOARD`), the control loop starts producing real commands.
- If the pilot switches out of OFFBOARD at any point, the control loop pauses and the app waits for re-entry.
- **The app never commands mode changes.** This is the safe handover pattern.

### With `--takeoff-landing`: app-managed lifecycle
- `drone.action.set_takeoff_altitude()` → `action.arm()` (retried 6×) → `action.takeoff()` → `_start_offboard()`.
- `_start_offboard` streams zero setpoints for 2 s (PX4 rejects `offboard.start()` if there's no setpoint history — `NO_SETPOINT_SET`) then calls `offboard.start()` with 3× retry.
- On Ctrl+C or mission-duration expiry → `_land_safely()` → `offboard.stop()` + `action.land()`, with SIGINT ignored during landing so a second Ctrl+C can't abort mid-flare.

### Required PX4 parameters (per project CLAUDE.md)
- `COM_RC_IN_MODE = 4` — allow flight without RC
- `COM_RCL_EXCEPT` bit 2 set — ignore RC loss in offboard
- `COM_OF_LOSS_T` — offboard signal loss timeout (~1 s)
- `COM_OBL_RC_ACT` — failsafe action on offboard signal loss

These are entirely standard for companion-computer offboard.

---

## 7. Target selection (who to follow)

Target-ID selection lives in the **pipeline callback**, not the controller. The controller only ever sees one `Detection` (or `None`).

1. `app_callback` in `hailo_drone_detection_manager.py` receives all detections + tracker IDs.
2. It picks the single target based on `FollowTargetState`:
   - If operator explicitly locked an ID via UI → follow only that ID. If lost, fall back to IDLE (hover).
   - If no explicit lock → automatically follow the largest visible person's bbox (`max(persons, key=bbox_area)`).
   - If no persons at all → `Detection = None`.
3. `shared_state.update(Detection(...))` — the control loop picks it up next tick.

Target ID persistence is provided by **ByteTracker** (standard MOT algorithm, `pipeline_adapter/byte_tracker.py`) running synchronously in the callback. `track_thresh=0.4, track_buffer=90, match_thresh=0.5` — reasonably persistent; a track survives ~3s of occlusion at 30fps.

---

## 8. What's standard, what's custom

| Piece | Standard? | Notes |
|---|---|---|
| Body-velocity + yawrate MAVLink setpoint | ✅ Canonical PX4 offboard | `SET_POSITION_TARGET_LOCAL_NED` body frame |
| Streaming zero-setpoint pre-offboard | ✅ Required by PX4 | Avoids `NO_SETPOINT_SET` |
| `drone.action.arm/takeoff/land` via MAVSDK | ✅ Standard MAVSDK | |
| Dual-path (app-managed vs pilot-managed) lifecycle | ✅ Common pattern | Safer for real flight |
| ByteTracker for ID persistence | ✅ Standard MOT | Widely used in vision + follow apps |
| P controllers per axis | ✅ Standard | Yaw (sqrt P), forward (distance P), alt-hold (plain P in live_control_loop) |
| Per-axis EMA low-pass in VelocityCommandAPI | ✅ Standard first-order filter | yaw α=0.3, forward α=0.15, right α=0.3, down α=0.2 — all applied in `send()` |
| Dead zones around zero error | ✅ Standard | Suppresses sensor noise |
| Clamps / max-speed saturation | ✅ Standard | |
| Image-based visual servoing (center_x → yaw, bbox_height → forward distance) | ✅ Textbook IBVS | Two image features drive separate axes; altitude is held by PX4 |
| **Signed square-root response** (yaw) | ⚠️ Common in robotics, not classical PID | Softens step near zero; widely used in ArduPilot / UAV loops |
| **Scale-invariant distance error** (`target/bbox - 1`) | ⚠️ Common in vision-servo | Saturates correctly at far distances |
| **Bbox-height safety → emergency reverse** | ❌ Custom | Vision-specific emergency response when person bbox > 0.8 |
| **IDLE ↔ auto-target fallback** on explicit-lock loss | ❌ Custom | UX choice, not a control-theory one |

Summary: the control architecture is textbook IBVS — offboard body-velocity commands, P per axis (signed-sqrt yaw, scale-invariant distance forward, alt-hold downstream), dead zones, saturation, EMA smoothing. The only non-standard elements are the vision-specific emergency safety bypass (bbox > 0.8 → reverse) and the signed-sqrt yaw response.

---

## 9. Suggested review / audit path

If you want to review end-to-end, read in this order:

1. **`follow_api/types.py`** — domain primitives (5 fields, 30 lines)
2. **`follow_api/config.py::ControllerConfig`** — every knob in one place
3. **`follow_api/controller.py::compute_velocity_command`** — the math
4. **`drone_api/mavsdk_drone.py::VelocityCommandAPI.send`** — clamp + per-axis EMA (yaw, forward, right, down)
5. **`drone_api/mavsdk_drone.py::live_control_loop`** — the 10 Hz loop + altitude floor/ceiling clamp
6. **`drone_api/mavsdk_drone.py::run_live_drone`** — lifecycle, takeoff-landing, offboard-handover
7. **`pipeline_adapter/hailo_drone_detection_manager.py::app_callback`** — target selection, IDLE fallback, ByteTracker
8. **`servers/web_server.py::_CONFIG_FIELDS`** — runtime-mutable subset of config

Each of those is short and single-purpose. The entire control surface fits in ~1000 lines.

---

## 10. Known risks / things I'd look at next

- **Forward EMA adds phase lag.** With α=0.15 the time constant is ~0.6 s. The drone reacts with some delay to vertical-position changes. center_y has stronger pitch coupling than bbox_height (transient only — during acceleration), but the EMA dampens it. If flight tests show too much oscillation, lower α; if too sluggish, raise it. A gimbal would eliminate pitch coupling at source.
- **Altitude from bbox_height couples with distance.** If the person is far away (small bbox), the drone descends; if close (large bbox), it climbs. This is intentional — it keeps the person at a consistent apparent size. But rapid distance changes cause altitude changes, which the `down_alpha = 0.2` EMA smooths.
- **No integral term anywhere.** Any steady-state error (e.g. wind pushing the drone sideways while trying to hold position) is not corrected by this controller — PX4's inner loops handle it, but if you notice persistent offsets under wind, consider adding I to the altitude or forward loops.
- **No gimbal.** The camera is rigidly mounted, so body pitch couples into `center_y` (the forward axis input). The coupling is transient (only during acceleration) and the EMA filter attenuates it — but a stabilised gimbal would eliminate the coupling at source and allow faster controller response.
