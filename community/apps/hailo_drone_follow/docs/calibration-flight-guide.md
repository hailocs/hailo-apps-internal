# Drone-Follow Calibration Flight Guide

A hands-on procedure to tune the follow-controller gains and speed limits on a
real flight in the minimum number of batteries. Every control name below
matches the label shown in the **OpenHD / web UI** sliders.

**In this guide, "P-gain" is the same thing as "kp_*" in the JSON/CLI.**
`kp_yaw` = *Yaw P-gain*, `kp_distance` = *Distance P-gain*, etc.

---

## What drives what — read this first

The controller has **two image-driven loops** plus a PX4 alt-hold:

| Axis | Driven by | UI group | Sign convention |
|---|---|---|---|
| **Yaw** (rotate left/right) | bbox horizontal position (`center_x`) | YAW CONTROL | Person left of centre → yaw left |
| **Forward / Backward** | bbox **size** (`bbox_height`) — distance via apparent size | FORWARD / BACKWARD | Person too small → forward |
| **Altitude** (climb/descend) | held by PX4 around `target_altitude` | ALTITUDE | Operator-set, mid-flight adjustable |

Forward/back is **scale-invariant**: the controller acts on
`(target_bbox / bbox) - 1`, the relative distance error. A person at 2× the
target distance gives factor=1 regardless of absolute bbox size.

Pitch coupling on the forward axis is now *much* weaker than the legacy
center_y loop, but the pitch transient can still pump bbox apparent size
during hard accelerations — `Max forward accel (m/s²)` remains the primary
damping knob.

---

## Pre-flight checklist

Do these once before the calibration session. None of these values get touched
mid-flight.

1. **Load a clean baseline** — on the ground, `drone-follow --config
   df_config.example.json ...` (or set the JSON path in your boot config).
   Calibrate from a known starting point, not from yesterday's in-progress
   tweaks.
2. **Lock the safety cage** (set these in the UI before takeoff and leave
   them alone):
   - **Min altitude (m)** = `2.0` or higher — whatever clears local obstacles.
   - **Max altitude (m)** = `15–20` — local regulatory limit.
   - **Max forward accel (m/s²)** = `1.5` as a safety ceiling during flights
     1 & 2. You will lower this during flight 3.
3. **Enable air-side recording** — `--record` on launch, or toggle **Air-side
   recording** in the UI right after takeoff. You want footage to review
   offline when a pass felt ambiguous.
4. **Set `Yaw only (no forward)` = ON** for flight 1.
5. **Battery plan** — three flights of 5–8 min each. Carry at least four
   batteries so you have room to repeat one.
6. **Subject** — you (solo). Pace is ~2 m/s (brisk walk / slow jog). You'll
   need open space of ~30 m in each direction.
7. **Slider operator** — your phone connected to QOpenHD (or the drone-follow
   web UI). Sliders are **live** — values apply the moment you let go. Use
   the **Save config (air)** toggle after each flight to persist good values.

---

## Knob reference — what each slider does

All values are current defaults from `df_params.json`. "Raise" and "Lower" describe what happens to drone behaviour when you move the slider in that direction.

### YAW CONTROL

| Slider | Default | What it does | Raise ⬆ | Lower ⬇ |
|---|---|---|---|---|
| **Yaw P-gain** | 5.0 | How hard the drone rotates per degree of horizontal error (signed-sqrt response — big errors don't go linearly harder). | Snappier lock on the target; oscillation / hunting if pushed too high. | Slower to catch up with a moving subject; sluggish turns. |
| **Yaw smoothing (α)** | 0.30 | Low-pass filter on the yaw command. 1.0 = no filter, 0.01 = heavy smoothing. | More responsive, also more jitter from detection noise. | Smoother yaw, feels dragged / laggy. |
| **Smooth yaw** | ON | Master switch for the filter above. | — | Raw commands; expect jitter. Leave ON during calibration. |
| **Max yaw rate (deg/s)** | 90 | Hard clamp on commanded yaw speed (what MAVSDK actually gets). | Faster recovery from large angle errors (subject sprints across). | Rotation feels capped / frustrating on big errors. |
| **Dead-zone yaw (deg)** | 2.0 | Horizontal error window in which no yaw is commanded. | Less micro-hunting when target is near centre; target can drift off-centre before reacting. | More aggressive centring; can hunt on detection wiggle. |

### FORWARD / BACKWARD (driven by bbox size — distance control)

| Slider | Default | What it does | Raise ⬆ | Lower ⬇ |
|---|---|---|---|---|
| **Distance P-gain** | 1.0 | Gain on `(target_bbox / bbox) - 1`. factor=1 means "person is 2× too far"; default saturates max_forward at factor=1. | Faster approach/retreat when distance is off. | Drone lags converging back to the target distance. |
| **Target bbox height (0-1)** | 0.30 | Desired person size in frame — the "hold this distance" setpoint. Captured from the live bbox at lock time, so clicking the subject sets it automatically. | Drone moves **closer** — larger apparent size. | Drone moves **further** — smaller apparent size. |
| **Dead-zone bbox (%)** | 10 | `\|factor\|` window with no forward command (10 → ±10% relative bbox error). | Less forward hunting from bbox jitter; wider steady-state distance variation allowed. | Tighter distance hold; more prone to hunting on detection noise. |
| **Max forward speed (m/s)** | 2.0 | Clamp on commanded approach speed. | Can catch a faster subject; burns more battery and reduces reaction headroom. | Safer / calmer; can't keep up if subject is too fast. |
| **Max backward speed (m/s)** | 3.0 | Clamp on commanded retreat speed. | Can retreat from a fast-closing subject. | More likely to be "run over" if subject moves toward drone aggressively. |
| **Forward smoothing (α)** | 0.15 | Low-pass on the forward command. | Snappier forward/back response; exposes pitch-coupled oscillation. | Smoother forward, at the cost of lag. |
| **Smooth forward** | ON | Master switch for the filter above. | — | Leave ON during calibration. |
| **Max forward accel (m/s²)** | 1.5 | Slew-rate cap on forward velocity (m/s²). **Damps the pitch transient** — the drone physically can't demand a faster pitch change than this. Independent of max-forward and of the α filter. | Punchier acceleration; can trigger pitch → bbox-pump → forward oscillation. | Smoother acceleration profile; subject may pull away briefly during hard chases. This is the knob that usually kills forward-axis oscillation. |

### ALTITUDE (held by PX4 around `target_altitude`)

| Slider | Default | What it does | Raise ⬆ | Lower ⬇ |
|---|---|---|---|---|
| **Target altitude (m)** | 3.0 | Operator-set hover altitude. Used as takeoff height with `--takeoff-landing` and as the alt-hold reference in flight. Adjustable mid-flight via the UI. | Drone climbs to the new target. | Drone descends to the new target. |
| **Min altitude (m)** | 2.0 | Hard floor enforced in `live_control_loop`. Down command clamped to ≥0 once at floor. | More headroom above ground/obstacles. | Risk of low-altitude excursions. |
| **Max altitude (m)** | 4.0 | Hard ceiling. Down command clamped to ≤0 once at ceiling. | More vertical room for the alt-hold loop. | Safer; clipped early if alt-hold drifts. |
| **Max climb speed (m/s)** | 1.0 | Clamp on the alt-hold output (negative side). | Faster recovery from altitude error. | Gentler vertical motion. |
| **Altitude smoothing (α)** | 0.20 | Low-pass on the alt-hold command. | More responsive altitude changes; more jitter. | Smoother vertical motion; can lag during target changes. |
| **Smooth altitude** | ON | Master switch. | — | Leave ON. |

### Knobs to leave alone during calibration

- **Min altitude (m)** / **Max altitude (m)** — safety floor/ceiling. Set in
  pre-flight, never touched.
- **Max bbox height safety** (hidden / not in UI slider list by default) —
  emergency-retreat trigger. Do not touch.
- **Target altitude (m)** — takeoff height, not a tuning knob.
- **Orbit speed / Orbit direction** — orbit mode only. Not in scope here.
- **Lateral smoothing (α)** — only relevant in orbit mode.

---

## Flight 1 — Yaw (≈5 min)

**Setup:** `Yaw only (no forward)` = ON. Subject (you) walks in arcs around the
hover point at ~3 m radius, ~2 m/s. Start with slow sweeps, end with sharper
zigzags.

**Suggested starting values** (slightly detuned so you walk up toward
instability, never down from it):

- Yaw P-gain = **3.5** (defaults to 5.0)
- Yaw smoothing (α) = **0.25**
- Max yaw rate = **90 deg/s**
- Dead-zone yaw = **2.0 deg**

**Procedure:**

1. **Find the gain ceiling.** Walk a steady horizontal arc. Raise *Yaw P-gain*
   by +1 every pass until you see the drone nose wobble left-right after it
   catches you. That's the limit.
2. **Back off 25%.** Multiply the oscillation point by 0.75 — that's your
   committed *Yaw P-gain*.
3. **Smoothness.** If yaw feels jittery on a steady arc, drop *Yaw smoothing
   (α)* from 0.25 → 0.20 → 0.15 (lower α = more filtering). If it now feels
   laggy, you over-smoothed — go back up by 0.05.
4. **Max yaw rate.** Stand still, then sprint 90° around the drone. If the
   drone visibly saturates (target leaves the frame sideways and yaw can't
   catch up), raise *Max yaw rate* 90 → 120 → 150. Most setups are fine at 90.
5. **Dead-zone.** If the nose micro-twitches while you stand still near
   centre, raise *Dead-zone yaw* 2 → 3 → 4 deg. Stop as soon as twitching is
   gone — don't keep widening.
6. **Save.** Land, toggle **Save config (air)** ON. It auto-returns to OFF
   when saved.

**Commit criterion:** Steady arc produces smooth head-tracking with no visible
wobble; sharp direction change recovers in one motion, not two.

---

## Flight 2 — Forward / Backward (distance, ≈8 min, the problem child)

**Setup:** `Yaw only (no forward)` = **OFF** (so the distance loop runs).
Yaw is already stabilised from Flight 1. Altitude is held by PX4 around
*Target altitude* — leave it at the value you used for takeoff.

Subject walks a straight radial line: away from drone 10 m, back toward 10 m,
steady pace. Then a stop-start-stop sequence: walk 5 m, freeze 3 s, walk 5 m
more.

**Suggested starting values** (key insight: **lower Max forward accel first**
to damp pitch transients, THEN tune gain):

- Max forward accel = **1.0 m/s²** (defaults 1.5 — primary anti-oscillation knob)
- Distance P-gain = **0.7** (defaults 1.0)
- Forward smoothing (α) = **0.12** (defaults 0.15)
- Max forward speed = **1.5 m/s**
- Max backward speed = **2.0 m/s**
- Dead-zone bbox = **12 %**
- Target bbox height — **set by clicking yourself in the UI** once at the
  starting distance (auto-captures)

**Procedure — in this order (order matters):**

1. **Damp the pitch transient first.** Walk the radial line. If the forward
   axis oscillates, lower *Max forward accel* 1.0 → 0.75 → 0.5. This caps how
   fast the drone can demand pitch changes, breaking the pitch-pump feedback
   loop.
2. **Then look at smoothing.** If oscillation persists at reasonable accel
   limits, lower *Forward smoothing (α)* 0.12 → 0.08.
3. **Then lower gain.** Only if the two above didn't fix it: drop
   *Distance P-gain* in 0.2 steps (0.7 → 0.5 → 0.3).
4. **Stop-start-stop test.** With oscillation gone, walk the radial line and
   freeze mid-pass. Drone should settle within ~1.5 s with no overshoot. If
   settling is slow, *raise* the gain back up cautiously in 0.1 steps.
5. **Push max speeds.** Subject walks a full radial run. If the drone
   saturates at 1.5 m/s forward, raise *Max forward speed* 1.5 → 2.0. Cap
   around 2.5 for a 2 m/s subject — headroom, not chase capacity.
6. **Dead-zone bbox.** If there's residual hunting while subject stands at
   good distance, raise *Dead-zone bbox (%)* 12 → 15 → 20.
7. **Save.**

**Commit criterion:** Radial walk produces no oscillation; stop produces
clean settle ≤1.5 s; no bounce-back when subject freezes.

---

## Suggested final configuration

If both flights converged cleanly, you should land near values like these
(reality will vary ±20%):

| Slider | Default | Post-calibration target |
|---|---|---|
| Yaw P-gain | 5.0 | 4–6 |
| Yaw smoothing (α) | 0.30 | 0.15–0.25 |
| Max yaw rate | 90 | 90–120 |
| Dead-zone yaw | 2.0 | 2–4 |
| Distance P-gain | 1.0 | 0.5–1.2 |
| Max forward accel | 1.5 | **0.5–1.0** (key for damping osc) |
| Forward smoothing (α) | 0.15 | 0.08–0.15 |
| Max forward speed | 2.0 | 1.5–2.5 |
| Max backward speed | 3.0 | 2.0–3.0 |
| Dead-zone bbox | 10 | 10–20 |
| Target altitude | 3.0 | site-specific |

---

## Troubleshooting — symptom → knob

| Symptom | First knob | Then try |
|---|---|---|
| Yaw hunts left/right around a static target | Lower *Yaw P-gain* 25% | Raise *Dead-zone yaw* +1° |
| Yaw is slow to catch a moving target | Raise *Yaw P-gain* | Raise *Max yaw rate* |
| Yaw stutter / noisy rotation | Lower *Yaw smoothing (α)* (more filter) | — |
| Forward axis oscillates (in-out pumping) | **Lower *Max forward accel*** | Lower *Forward smoothing (α)*, then lower *Distance P-gain* |
| Drone lags converging back to target distance | Raise *Distance P-gain* | Raise *Max forward speed* |
| Drone retreats too aggressively when subject approaches | Lower *Distance P-gain* | Lower *Max backward speed* |
| Altitude drifts away from target | Re-set *Target altitude* mid-flight | — (PX4 alt-hold; not a controller knob) |
| Drone loses subject when subject stops | Raise *Dead-zone yaw* / *Dead-zone bbox* | Check detection stability, not the controller |
| Subject leaves frame when drone pitches hard | Lower *Max forward accel* | — (this is exactly what that knob is for) |

---

## Post-flight review

1. Pull recordings off the drone (`drone_follow/recordings/rec_*.mp4`).
2. For each axis, eyeball the target bounding box over time:
   - **Yaw:** `center_x` should sit near 0.5 with small excursions.
   - **Forward (distance):** `bbox_height` should sit near *Target bbox height*
     with no sine-wave oscillation.
   - **Altitude:** PX4 holds it; expect slow drift only if your alt-hold
     gain is detuned or if you nudged *Target altitude* in flight.
3. Any axis that still looks busy → return to that flight's procedure next
   session, don't re-run the others.
