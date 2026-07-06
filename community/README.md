# Hailo Apps — Community Directory

This directory holds **community-contributed** applications and plugins, separate
from the core/official apps under `hailo_apps/python/`. Everything here is built on
the same core framework (GStreamerApp, HailoRT, the postprocess plugins).

## Entry points for discovery

| You want… | Look at |
|---|---|
| A browsable, demo-rich index of all community projects | [`HAILO_PROJECT_INDEX.md`](HAILO_PROJECT_INDEX.md) |
| Structured, machine-readable app catalog (all apps, archs, models) | [`../.claude/skills/app-builder/knowledge/app_catalog.yaml`](../.claude/skills/app-builder/knowledge/app_catalog.yaml) |
| The community GStreamer plugins (overlay, vampire, dynamic cropper) | [`plugins/README.md`](plugins/README.md) |
| Per-app architecture / how-to-run / how-to-extend | each app dir's `CLAUDE.md` |
| How to pick + build a new app (AI agent) | `../CLAUDE.md` routing table + `../.hailo/README.md` |

## Pipeline apps (`apps/pipeline_apps/`)

GStreamer pipeline apps (inference in a user callback, hailooverlay display):

`baby_sleep_monitor`, `bubble_pop`, `cat_food_monitor`, `crowd_counting`,
`depth_anything`, `depth_proximity_alert`, `easter_game`, `face_landmarks`,
`gesture_detection`, `gesture_mouse`, `hotdog_not_hotdog`, `license_plate_reader`,
`line_crossing_counter`, `multi_camera_store_monitor`, `multi_entrance_tracker`,
`parking_lot_occupancy`, `ppe_safety_checker`, `retail_shelf_analyzer`,
`rhythm_royale`, `room_security_monitor`, `semaphore_translator`,
`vampire_mirror`, `workout_rep_counter`.

> `yolo_world` is now an **official** app — see
> `hailo_apps/python/pipeline_apps/yolo_world/`. `gesture_detection` now lives
> entirely here in the community tree.

## Standalone apps (`apps/standalone_apps/`)

Direct HailoRT (Python or C++) inference, no GStreamer:

`aerial_object_counter`, `depth_anything_cpp`, `depth_anything_python`,
`document_text_extractor`, `lane_departure_warning`, `photo_enhancer`,
`traffic_light_detector`.

## Gen-AI apps (`apps/gen_ai_apps/`)

VLM / LLM / voice agent apps (Hailo-10H):

`visual_quality_inspector`, `voice_controlled_camera`, `voice_mouse_agent`.

## Plugins (`plugins/`)

Opt-in community GStreamer postprocess elements, each a self-contained meson
project under `plugins/`, built separately via `plugins/build.sh` (not part of
the official postprocess build): `hailooverlay_community`,
`hailotilecropper_dynamic` (plus the app-bundled `hailovampire_overlay`, built
with the `vampire_mirror` app). See [`plugins/README.md`](plugins/README.md).

## Contributions (`contributions/`)

Knowledge contributions: `bottleneck-patterns`, `general`, `hardware-config`,
`pipeline-optimization`.

## Running any community app

```bash
source setup_env.sh
python community/apps/pipeline_apps/<app>/<app>.py --help   # see options
python community/apps/pipeline_apps/<app>/<app>.py --input usb   # USB camera (auto-detect)
```

Each app's `CLAUDE.md` documents its exact command, models, and supported Hailo
architectures.
