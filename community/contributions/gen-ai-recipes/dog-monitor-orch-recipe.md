---
title: "Dog Monitor — Continuous VLM Monitoring App"
author: "AI Agent (auto-generated)"
date: 2026-03-19
category: gen-ai-recipes
tags: [vlm, monitoring, camera, event-tracking, continuous]
---

# Dog Monitor Recipe

## What It Does

Continuous camera monitoring with VLM-based dog activity classification.
Watches a home camera, analyzes frames at configurable intervals using a Hailo-10H
VLM, classifies responses into 8 activity categories, and maintains a running
session summary with event counts.

## Key Patterns Used

- **Backend reuse** from `vlm_chat` — no code duplication, import `Backend` directly
- **EventTracker** with keyword-based VLM response classification (8 categories)
- **Timer-based capture loop** with configurable interval (default 10s)
- **Non-blocking inference** via `ThreadPoolExecutor.submit()` with pending flag
- **SIGINT handler** that sets running flag only — cleanup in `finally` block
- **Optional frame saving** on event detection (skips IDLE and NO_DOG)
- **Display overlay** with semi-transparent bar showing last event and activity counts
- **Headless mode** support via `--no-display` flag

## Files Created

| File | Lines | Purpose |
|---|---|---|
| `dog_monitor.py` | ~240 | Main app with camera + VLM loop, display overlay |
| `event_tracker.py` | ~120 | Event classification and statistics tracking |
| `README.md` | ~100 | Usage documentation with CLI reference |
| `__init__.py` | 0 | Package marker |

## Reusable For

To adapt this recipe for a different monitoring use case, change these 3 things:

1. **SYSTEM_PROMPT** — describe what the VLM should focus on
2. **MONITORING_PROMPT** — the per-frame question
3. **EventType enum + keyword map** — activity categories and detection keywords

### Example adaptations:

- **Security camera**: EventType = PERSON, VEHICLE, PACKAGE, SUSPICIOUS, EMPTY; keywords = person/human, car/truck, box/delivery, etc.
- **Baby monitor**: EventType = SLEEPING, CRYING, PLAYING, FEEDING, EMPTY; keywords = sleep/rest, cry/upset, play/toy, bottle/feed, etc.
- **Wildlife camera trap**: EventType = BIRD, DEER, BEAR, RACCOON, UNKNOWN; keywords by species
- **Retail shelf monitor**: EventType = STOCKED, LOW, EMPTY, CUSTOMER; keywords = full/stocked, low/few, empty/bare, person/reaching

## Architecture Diagram

```
USB/RPi Camera
      │
      ▼
┌─────────────────┐
│  Main Loop       │  ← cv2.VideoCapture + display overlay
│  (25fps display) │
└────────┬────────┘
         │ every N seconds
         ▼
┌─────────────────┐     ┌──────────────────┐
│ ThreadPoolExec.  │────▶│  Backend Process  │
│ submit(analyze)  │     │  VDevice + VLM    │
└────────┬────────┘     └──────────────────┘
         │
         ▼
┌─────────────────┐
│  EventTracker    │  ← classify_response() → add_event()
│  keyword match   │
└────────┬────────┘
         │
         ▼
   Console log + optional frame save
```

## Convention Compliance

- All absolute imports (no relative)
- `get_logger(__name__)` in both modules
- `resolve_hef_path()` for HEF resolution
- `get_standalone_parser()` for CLI
- `handle_list_models_flag()` before `parse_args()`
- `SHARED_VDEVICE_GROUP_ID` used by Backend (inherited)
- `QT_QPA_PLATFORM=xcb` set before cv2 import
- Signal handler only sets flag — cleanup in finally
