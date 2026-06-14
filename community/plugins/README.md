# Community GStreamer Plugins

This directory surfaces the **community-contributed GStreamer postprocess plugins**
so they are discoverable from the `community/` tree. The C++ sources live under
`hailo_apps/postprocess/cpp/` (they must stay there so the meson build that ships
the rest of the postprocess `.so` files can link them with the shared
`postprocess_dep` and TAPPAS deps). This README is the canonical index mapping each
community plugin to its source, gst element name, and usage.

Build all of them with:

```bash
cd hailo_apps/postprocess && bash compile_postprocess.sh
```

Each plugin installs as a `.so` into the system GStreamer plugin dir
(`gst_plugins_dir`, e.g. `/usr/lib/x86_64-linux-gnu/gstreamer-1.0`). Verify with
`gst-inspect-1.0 <element-name>` after building (`source setup_env.sh` first so the
plugin path is set).

| Plugin (gst element) | Source dir | Klass | Purpose |
|---|---|---|---|
| `hailooverlay_community` | `hailo_apps/postprocess/cpp/overlay_community/` | `Hailo/Tools` | Community overlay element — draws detections, classifications, landmarks, IDs and other HailoObjects onto frames with configurable styling (yaml-cpp driven `style_config`). |
| `hailotilecropper_dynamic` | `hailo_apps/postprocess/cpp/hailotilecropper_dynamic/` | `Hailo/Tools` | Dynamic tiling cropper — crops tiles defined dynamically by upstream pipeline elements and/or statically by properties. Bundles its own `GstHailoBaseCropperDyn` base class so it loads in pipelines that don't bring in the system-wide TAPPAS base cropper. Ported from `community_plugins` with a TAPPAS 5.3 fix. |

### App-bundled elements (built with their app, not the shared postprocess)

| Plugin (gst element) | Source dir | Build | Purpose |
|---|---|---|---|
| `hailovampire_overlay` | `community/apps/pipeline_apps/vampire_mirror/postprocess/` | that dir's `build.sh` (or auto via the app's `run.sh`) | Paints "vampire" pixels with the corresponding region of a shared-memory background buffer. App-specific to `vampire_mirror`, so it ships with the app rather than the shared postprocess. |

## Usage examples

### hailooverlay_community
```
... ! hailooverlay_community ! videoconvert ! autovideosink
```
Used throughout the community pipeline apps (gesture_detection, vampire_mirror,
bubble_pop, …) as a drop-in replacement for the stock `hailooverlay` with
community styling.

### hailovampire_overlay
```
... ! hailovampire_overlay background=/path/to/bg ! ...
```
See `community/apps/pipeline_apps/vampire_mirror/` for the full pipeline.

### hailotilecropper_dynamic
```
... ! hailotilecropper_dynamic ! <inference> ! hailotileaggregator ! ...
```
See `community/apps/pipeline_apps/` tiling-based apps and
`hailo_apps/postprocess/cpp/hailotilecropper_dynamic/examples/`.

## Provenance

These plugins were integrated for the community release from the `community_apps`
(2026-06-07) and `community_plugins` (2026-05-26) branches. The `community_apps`
versions are the newest and authoritative for the overlay element; the
`hailotilecropper_dynamic` was ported from `community_plugins` with a TAPPAS 5.3
build fix applied during integration. The `community_plugins` branch's other
deltas (config.yaml, install.sh, generate_platforms.py, VLM-chat python files)
were fully subsumed by the newer `community_apps` versions and therefore carry no
unique content into this release.
