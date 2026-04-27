# Drone-Follow Calibration Flight Guide

A hands-on procedure to tune the follow-controller gains and speed limits on a
real flight in the minimum number of batteries. Every control name below
matches the label shown in the **OpenHD / web UI** sliders.

**In this guide, "P-gain" is the same thing as "kp_*" in the JSON/CLI.**
`kp_yaw` = *Yaw P-gain*, `kp_forward` = *Forward P-gain*, etc.

---

## What drives what — read this first

The controller has **three independent loops**, each driven by a different
property of the detected person's bounding box:

| Axis | Driven by | UI group | Sign convention |
|---|---|---|---|
| **Yaw** (rotate left/right) | bbox horizontal position (`center_x`) | YAW CONTROL | Person left of centre → yaw left |
| **Forward / Backward** | bbox **vertical** position (`center_y`) | FORWARD / BACKWARD | Person below centre → back up |
| **Altitude** (climb/descend) | bbox **size** (`bbox_height`) | ALTITUDE | Person too small → descend |

Key implication for the forward-axis oscillation symptom: **forward/back is
driven by vertical image position, not bbox size.** When the drone pitches
forward to accelerate, the camera's forward tilt shifts the subject vertically
in frame, which feeds back into the forward command — the classic coupling
that `Max forward accel (m/s²)` is designed to damp.

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

### FORWARD / BACKWARD (driven by vertical bbox position)

| Slider | Default | What it does | Raise ⬆ | Lower ⬇ |
|---|---|---|---|---|
| **Forward P-gain** | 1.5 | Gain when **approaching** (person is above the target Y — too far). | Faster catch-up when subject walks away. | Drone lags behind the subject. |
| **Backward P-gain** | 2.5 | Gain when **retreating** (person is below the target Y — too close). Higher than forward by design — backing off is a safety action. | More aggressive retreat; can also cause backward-axis oscillation if too high. | Drone holds closer; may not retreat fast enough if subject walks toward it. |
| **Max forward speed (m/s)** | 1.0 | Clamp on commanded approach speed. | Can catch a faster subject; burns more battery and reduces reaction headroom. | Safer / calmer; can't keep up if subject is too fast. |
| **Max backward speed (m/s)** | 1.5 | Clamp on commanded retreat speed. | Can retreat from a fast-closing subject. | More likely to be "run over" if subject moves toward drone aggressively. |
| **Forward smoothing (α)** | 0.15 | Low-pass on the forward command. | Snappier forward/back response; exposes pitch-coupled oscillation. | Smoother forward, at the cost of lag. |
| **Smooth forward** | ON | Master switch for the filter above. | — | Leave ON during calibration. |
| **Max forward accel (m/s²)** | 1.5 | Slew-rate cap on forward velocity (m/s²). **Damps the pitch transient** — the drone physically can't demand a faster pitch change than this. Independent of max-forward and of the α filter. | Punchier acceleration; can trigger the pitch → center_y → forward feedback loop. | Smoother acceleration profile; subject may pull away briefly during hard chases. This is the knob that usually kills forward-axis oscillation. |

### ALTITUDE (driven by bbox size)

| Slider | Default | What it does | Raise ⬆ | Lower ⬇ |
|---|---|---|---|---|
| **Altitude P-gain** | 3.0 | Plain P gain on (target_bbox_height − measured bbox_height). | Faster distance-holding (reacts faster when subject moves in/out). | Sluggish altitude hold; drone drifts away vertically as subject's apparent size changes. |
| **Target bbox height (0-1)** | 0.30 | Desired person size in frame — the "hold this distance" setpoint. Captured from the live bbox at lock time, so clicking the subject sets it automatically. | Drone flies **lower / closer** — larger apparent size. | Drone flies **higher / further** — smaller apparent size. |
| **Dead-zone bbox (%)** | 15 | Error window (as % of target bbox height) with no altitude command. | Less altitude hunting from bbox jitter; wider steady-state distance variation allowed. | Tighter distance hold; more prone to hunting on detection noise. |
| **Max climb speed (m/s)** | 1.0 | Clamp on altitude-change rate (both climb and descend). | Faster distance recovery; also faster emergency climb when safety triggers. | Gentler altitude changes; may saturate when subject rushes toward drone. |
| **Altitude smoothing (α)** | 0.20 | Low-pass on altitude command. | More responsive altitude changes; more jitter. | Smoother vertical motion; can lag when subject changes pace. |
| **Smooth altitude** | ON | Master switch. | — | Leave ON. |
| **Target center Y** | 0.5 | Vertical position in frame where the controller wants the person to sit (0 = top, 1 = bottom). Feeds the **forward** loop, not altitude. Useful if camera is tilted and the subject naturally sits high/low in frame. | Drone backs off to push subject lower in frame. | Drone approaches to push subject higher in frame. |
| **Dead-zone Y (deg)** | 2.0 | Vertical error window (in degrees of VFOV) with no **forward** command. (Despite being in the altitude UI group, this knob affects the forward axis — see topology table at top.) | Less forward/back hunting; larger steady-state distance error. | Tighter distance hold; more prone to forward axis hunting. |

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

## Flight 2 — Altitude / bbox (≈5 min)

**Setup:** `Yaw only (no forward)` = **OFF** (so altitude loop runs). To keep
forward decoupled for this flight, set **Forward P-gain = 0** and **Backward
P-gain = 0**. This cleanly disables forward/back while leaving altitude
active.

Subject walks a straight radial line: toward the drone for 10 m, then away for
10 m, steady pace.

**Suggested starting values:**

- Altitude P-gain = **2.0** (defaults to 3.0)
- Altitude smoothing (α) = **0.15** (defaults to 0.20)
- Dead-zone bbox = **18%** (defaults to 15)
- Max climb speed = **1.0 m/s**
- Target bbox height — **set by clicking yourself in the UI** once at the
  starting distance (auto-captures)

**Procedure:**

1. **Find the gain ceiling.** Walk your radial line. Raise *Altitude P-gain*
   +0.5 each pass until the drone starts pumping up and down while you're at
   constant distance. That's the limit.
2. **Back off 25%.**
3. **Smoothness.** If altitude jitters even at a good gain, lower *Altitude
   smoothing (α)* 0.15 → 0.10 (more smoothing).
4. **Dead-zone.** Stand still. If the drone still makes small climb/descend
   commands, raise *Dead-zone bbox (%)* 18 → 22 → 25. Stop when still-stand
   is quiet.
5. **Max climb speed.** Only raise if, during your radial run, the bbox
   clearly grows/shrinks faster than the drone can track. Otherwise leave at
   1.0.
6. **Restore Forward/Backward P-gains to defaults** (1.5 / 2.5) before
   landing — so the saved config isn't left with zeros.
7. **Save.**

**Commit criterion:** Walking toward / away holds bbox size stable within the
dead zone; standing still produces no altitude motion.

---

## Flight 3 — Forward / Backward (≈8 min, the problem child)

**Setup:** Full follow — all axes active. Yaw and altitude are now
pre-stabilised from flights 1 & 2, so any residual oscillation you see is
forward-specific (pitch coupling or forward-loop gain).

Subject walks a straight radial line: away from drone 10 m, back toward 10 m,
steady pace. Then a stop-start-stop sequence: walk 5 m, freeze 3 s, walk 5 m
more.

**Suggested starting values** (the key insight: **lower Max forward accel
first** to damp pitch coupling, THEN tune gain):

- Max forward accel = **1.0 m/s²** (defaults 1.5 — this is your primary
  anti-oscillation knob)
- Forward P-gain = **1.2** (defaults 1.5)
- Backward P-gain = **2.0** (defaults 2.5)
- Forward smoothing (α) = **0.12** (defaults 0.15)
- Max forward speed = **1.5 m/s**
- Max backward speed = **2.0 m/s**
- Dead-zone Y = **2.0 deg**

**Procedure — in this order (order matters):**

1. **Damp the pitch transient first.** Walk the radial line. If the forward
   axis oscillates, lower *Max forward accel* 1.0 → 0.75 → 0.5. This caps how
   fast the drone can demand pitch changes, breaking the pitch → center_y →
   forward feedback loop.
2. **Then look at smoothing.** If oscillation persists at reasonable accel
   limits, lower *Forward smoothing (α)* 0.12 → 0.08.
3. **Then lower gain.** Only if the two above didn't fix it: drop *Forward
   P-gain* in 0.3 steps (1.2 → 0.9 → 0.6). Drop *Backward P-gain* in 0.5
   steps only if the backward half specifically oscillates.
4. **Stop-start-stop test.** With oscillation gone, walk the radial line and
   freeze mid-pass. Drone should settle within ~1.5 s with no overshoot. If
   settling is slow, *raise* gains back up cautiously in half-steps.
5. **Push max speeds.** Subject walks a full radial run. If the drone
   saturates at 1.5 m/s forward, raise *Max forward speed* 1.5 → 2.0. Cap
   around 2.5 for a 2 m/s subject — headroom, not chase capacity.
6. **Dead-zone Y.** If there's residual forward hunting while subject stands
   at good distance, raise *Dead-zone Y* 2 → 3 → 4 deg.
7. **Save.**

**Commit criterion:** Radial walk produces no oscillation; stop produces
clean settle ≤1.5 s; no bounce-back when subject freezes.

---

## Suggested final configuration

If all three flights converged cleanly, you should land near values like these
(reality will vary ±20%):

| Slider | Default | Post-calibration target |
|---|---|---|
| Yaw P-gain | 5.0 | 4–6 |
| Yaw smoothing (α) | 0.30 | 0.15–0.25 |
| Max yaw rate | 90 | 90–120 |
| Dead-zone yaw | 2.0 | 2–4 |
| Forward P-gain | 1.5 | 0.9–1.5 |
| Backward P-gain | 2.5 | 2.0–2.5 |
| Max forward accel | 1.5 | **0.5–1.0** (key for damping osc) |
| Forward smoothing (α) | 0.15 | 0.08–0.15 |
| Max forward speed | 1.0 | 1.5–2.0 |
| Max backward speed | 1.5 | 1.5–2.0 |
| Altitude P-gain | 3.0 | 1.5–2.5 |
| Altitude smoothing (α) | 0.20 | 0.10–0.20 |
| Dead-zone bbox | 15 | 18–25 |
| Max climb speed | 1.0 | 1.0 |
| Dead-zone Y | 2.0 | 2–4 |

---

## Troubleshooting — symptom → knob

| Symptom | First knob | Then try |
|---|---|---|
| Yaw hunts left/right around a static target | Lower *Yaw P-gain* 25% | Raise *Dead-zone yaw* +1° |
| Yaw is slow to catch a moving target | Raise *Yaw P-gain* | Raise *Max yaw rate* |
| Yaw stutter / noisy rotation | Lower *Yaw smoothing (α)* (more filter) | — |
| Forward axis oscillates (in-out pumping) | **Lower *Max forward accel*** | Lower *Forward smoothing (α)*, then lower *Forward P-gain* |
| Drone lags behind fast-moving subject | Raise *Forward P-gain* | Raise *Max forward speed* |
| Drone retreats too aggressively when subject approaches | Lower *Backward P-gain* | Lower *Max backward speed* |
| Altitude hunts up/down | Lower *Altitude P-gain* 25% | Raise *Dead-zone bbox (%)* |
| Altitude drifts when subject changes pace | Raise *Altitude P-gain* | Raise *Altitude smoothing (α)* |
| Drone loses subject when subject stops | Raise *Dead-zone yaw* / *Dead-zone Y* | Check detection stability, not the controller |
| Subject leaves frame when drone pitches hard | Lower *Max forward accel* | — (this is exactly what that knob is for) |

---

## Post-flight review

1. Pull recordings off the drone (`drone_follow/recordings/rec_*.mp4`).
2. For each axis, eyeball the target bounding box position over time:
   - **Yaw:** `center_x` should sit near 0.5 with small excursions.
   - **Altitude:** `bbox_height` should sit near setpoint, minor pulses only.
   - **Forward:** `center_y` should sit near *Target center Y*, no sine-wave
     oscillation.
3. Any axis that still looks busy → return to that flight's procedure next
   session, don't re-run the others.
