# Tracking + ReID algorithm

End-to-end diagram of how a frame is turned into a follow command and how the
ReID gallery, drift filter, and re-acquisition paths interact. Read this
alongside [control-architecture.md](control-architecture.md) for the broader
system view; this document focuses specifically on the locked-target follow
loop inside the detection callback.

The implementation lives in:

- [`drone_follow/pipeline_adapter/hailo_drone_detection_manager.py`](../drone_follow/pipeline_adapter/hailo_drone_detection_manager.py)
  — per-frame callback that branches into the sub-flows below.
- [`drone_follow/pipeline_adapter/reid_manager.py`](../drone_follow/pipeline_adapter/reid_manager.py)
  — `update_gallery`, `_reacquire`, `try_reidentify`, `score_visible_persons`.
- [`reid_analysis/gallery_strategies.py`](../reid_analysis/gallery_strategies.py)
  — `MultiEmbeddingStrategy` (per-person gallery storage + similarity probe).

## 1. Main per-frame flow

```
                     ┌────────────────────────────────┐
                     │  Hailo detection pipeline      │
                     │  → list of `persons` (bboxes,  │
                     │     scores) for current frame  │
                     └─────────────┬──────────────────┘
                                   │
                          ┌────────▼─────────┐
                          │  persons empty?  │
                          └────┬─────────┬───┘
                               │ yes     │ no
                               ▼         │
                  ┌─────────────────┐    │
                  │ has_gallery &   │    │
                  │ within timeout? │    │
                  │  → HOLD         │    │
                  │ else → AUTO     │    │
                  └─────────────────┘    │
                                         ▼
                     ┌────────────────────────────────┐
                     │  ByteTracker.update(persons)   │
                     │  → person_by_id (activated     │
                     │    tracks only)                │
                     └─────────────┬──────────────────┘
                                   │
                     ┌─────────────▼──────────────────┐
                     │ best = person_by_id[target_id] │
                     └─────────────┬──────────────────┘
                                   │
                     ┌─────────────┴───────────────┐
                     │                             │
                  best != None                 best == None
                  (tracker holds target)       (tracker lost target)
                     │                             │
                     ▼                             ▼
        ┌────────────────────────┐    ┌──────────────────────────┐
        │ if should_update():    │    │ Recovery sub-flow        │
        │   → GALLERY UPDATE     │    │ (diagram §3 below)       │
        │     sub-flow (§2 below)│    │                          │
        │                        │    │ may set best, may switch │
        │ may switch target_id   │    │ target_id, may HOLD,     │
        │ on suspected drift     │    │ may bail to AUTO         │
        └────────────┬───────────┘    └────────────┬─────────────┘
                     │                             │
                     └──────────────┬──────────────┘
                                    │
                                    ▼
                     ┌────────────────────────────────┐
                     │ Controller setpoint from       │
                     │ best.bbox (or Kalman tlwh)     │
                     │ → shared_state.update          │
                     │ UI: highlight uses original_id │
                     └────────────────────────────────┘
```

## 2. Gallery-update sub-flow (drift filter)

Runs every `update_interval` (default 30) frames while ByteTracker is
successfully holding the locked target. Bands are configurable via CLI:
`--reid-drift-threshold` (default 0.6), `--reid-duplicate-threshold` (0.9),
`--reid-refresh-every` (5).

```
        ┌────────────────────────────┐
        │ extract embedding `emb`    │
        │ from current target bbox   │
        └──────────────┬─────────────┘
                       │
                       ▼
        ┌────────────────────────────┐
        │ gallery.size == 0 ?        │
        └─────┬─────────────────┬────┘
              │ yes             │ no
              ▼                 ▼
       ┌─────────────┐   ┌──────────────────────────┐
       │ BOOTSTRAP   │   │ size < min_for_check (2)?│
       │ store as    │   └─────┬─────────────┬──────┘
       │ first vec   │         │ yes         │ no
       └─────────────┘         ▼             ▼
                          ┌─────────┐   ┌──────────────────────┐
                          │ ADD     │   │ sim = max_similarity │
                          │ (cold)  │   │   (emb vs gallery)   │
                          └─────────┘   └──────────┬───────────┘
                                                   │
                          ┌────────────────────────┼────────────────────────┐
                          │                        │                        │
                  sim < drift_threshold       drift ≤ sim ≤ duplicate    sim > duplicate_threshold
                       (0.6)                                              (0.9)
                          │                        │                        │
                          ▼                        ▼                        ▼
                ┌──────────────────┐         ┌──────────┐         ┌──────────────────────┐
                │ SKIPPED_DRIFT    │         │  ADDED   │         │ duplicate_streak += 1│
                │ run _reacquire   │         │ (FIFO if │         └─────────┬────────────┘
                │ over person_by_id│         │   full)  │                   │
                └─────────┬────────┘         └──────────┘            ┌──────┴───────┐
                          │                                       streak == 5     streak < 5
            ┌─────────────┼─────────────┐                              │              │
            │             │             │                              ▼              ▼
        new tid        new tid       no match                 ┌──────────────┐ ┌──────────────────┐
        ≠ target       == target                              │ REFRESHED    │ │ SKIPPED_DUPLICATE│
            │             │             │                     │ replace_oldest│ │ (no-op)          │
            ▼             ▼             ▼                     │ streak ← 0   │ └──────────────────┘
    ┌──────────────┐ ┌──────────┐ ┌──────────┐                └──────────────┘
    │ switch       │ │ false    │ │ HOLD     │
    │ target_id    │ │ drift —  │ │ position │
    │ on_reidenti- │ │ keep     │ │ (return  │
    │   fied()     │ │ tracking │ │  early)  │
    └──────────────┘ └──────────┘ └──────────┘
```

Key invariant: a candidate embedding that lands in the **drift band** is
**never** stored, even when re-acquisition confirms the same `target_id`
(a "false drift"). The next sample (one `update_interval` later) gets a
fresh chance.

## 3. Recovery sub-flow (target lost by tracker)

Fires when `person_by_id[target_id]` is missing. Two sub-paths depending on
whether ByteTracker activated *any* tracks this frame:

```
        ┌────────────────────────────────┐
        │ has_gallery == True ?          │
        │ (else → AUTO mode immediately) │
        └─────────────┬──────────────────┘
                      │ yes
                      ▼
        ┌────────────────────────────────┐
        │ now − last_seen > 20 s ?       │
        └─────┬───────────────────┬──────┘
              │ yes               │ no
              ▼                   ▼
       ┌──────────────┐   ┌──────────────────────┐
       │ REID TIMEOUT │   │ person_by_id empty ? │
       │ enter auto   │   └─────┬───────────┬────┘
       │ clear gallery│         │ no        │ yes
       └──────────────┘         ▼           ▼
                       ┌──────────────────┐ ┌─────────────────────────┐
                       │ try_reidentify   │ │ score_visible_persons   │
                       │ ── _reacquire    │ │ over RAW persons        │
                       │ over tracked     │ │ (no track ids)          │
                       │ person_by_id     │ └────────────┬────────────┘
                       └────────┬─────────┘              │
                                │                  ┌─────┴─────┐
                                │              best_sim ≥     best_sim <
                                │              match_thresh   match_thresh
                                │                  │              │
                       ┌────────┴────────┐         ▼              ▼
                       │                 │   ┌──────────────┐ ┌──────────┐
                   match found       no match │ best = raw   │ │ HOLD     │
                       │                 │    │ detection    │ │ position │
                       ▼                 ▼    │ update_last_ │ │ (return  │
                ┌──────────────┐ ┌──────────┐ │   seen       │ │  early)  │
                │ switch       │ │ HOLD     │ │ (no set_     │ └──────────┘
                │ target_id    │ │ position │ │  target — id │
                │ on_reidenti- │ │ (return) │ │  stale until │
                │   fied()     │ │          │ │  next track) │
                │ best = match │ │          │ └──────────────┘
                └──────────────┘ └──────────┘
```

The raw-detection match path is what catches the case where the detector's
confidence dipped below ByteTracker's `track_thresh` (0.4 here, with
`det_thresh = track_thresh + 0.1 = 0.5` actually controlling new-track spawn
in the first association pass). ReID doesn't care about detector confidence,
so as long as the bbox is good enough to crop and embed, the controller
keeps following even when ByteTracker has effectively given up.

## End-to-end story

The two diagrams join up like this:

1. **Operator locks a person** — `target_state.set_target(N)`,
   `reid_manager.on_target_selected(N)` resets the gallery,
   `original_id = N` (this is the ID the UI keeps showing for the rest of
   the follow, regardless of how many tracker-side IDs come and go).
2. **Frames flow normally** — ByteTracker produces `person_by_id[N]`, the
   controller follows. Every `update_interval` frames the gallery sub-flow
   runs and either *adds*, *skips-similar*, *refreshes*, or *flags drift*.
3. **Tracker drifts onto wrong person** — next gallery sample's similarity
   drops below `drift_threshold` → drift sub-flow runs `_reacquire`
   immediately (without waiting for a tracker loss) and switches `target_id`
   onto whichever visible track actually matches the gallery. The candidate
   embedding is *not* stored.
4. **Tracker loses target completely** (full occlusion, missed detection
   for several frames) — recovery sub-flow takes over for up to
   `reid_search_timeout` (default 20 s). Three exits: re-identified onto a
   new track / raw-detection bbox match / timeout → return to auto.
5. **ByteTracker rejects all detections this frame** (low detector
   confidence) — `person_by_id` is empty but raw detections exist; ReID
   scores them directly. If the best raw match crosses
   `reid_match_threshold` (default 0.7), the controller is driven from that
   bbox even though no tracker id exists for it — locked-follow survives a
   tracker dropout.
6. **No persons at all in frame** — early branch holds for the same
   timeout, then bails to auto.

`_reacquire` is shared between (3) and (4); `score_visible_persons` is the
diagnostic / fallback variant for (5). All three share the same primitive:
crop → embed → max-similarity probe against the gallery.

## Tunable knobs (CLI)

| Flag | Default | Effect |
|---|---|---|
| `--update-interval` | 30 | Frames between in-track gallery sampling. |
| `--reid-threshold` | 0.7 | Minimum similarity for a re-acquisition / raw-match to be accepted. |
| `--reid-drift-threshold` | 0.6 | Below this, an in-track sample is treated as drift; gallery is not updated and reacquire is triggered. |
| `--reid-duplicate-threshold` | 0.9 | Above this, an in-track sample is treated as redundant and skipped (with periodic refresh). |
| `--reid-refresh-every` | 5 | After this many consecutive duplicate-band decisions, replace the oldest gallery vector. |
| `--reid-timeout` | 20.0 | Seconds to keep searching with the gallery before giving up and returning to auto. |

Tracker-side knobs (currently constants in
[`hailo_drone_detection_manager.py`](../drone_follow/pipeline_adapter/hailo_drone_detection_manager.py),
no CLI flags yet): `track_thresh=0.4`, `track_buffer=90`, `match_thresh=0.5`.
