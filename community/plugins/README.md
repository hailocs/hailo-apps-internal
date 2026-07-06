# Community GStreamer Plugins

Community-contributed GStreamer postprocess plugins. Each is a **self-contained,
opt-in** meson project living in its own subdirectory here — they are **not** part
of the official `hailo_apps/postprocess` build and are only built when you want
them.

Each plugin installs its `.so` into the **system GStreamer plugin directory**
(`pkg-config --variable=pluginsdir gstreamer-1.0`, e.g.
`/usr/lib/x86_64-linux-gnu/gstreamer-1.0`), which is on GStreamer's default scan
path — so no `GST_PLUGIN_PATH` tweaking is needed. Installing there requires
`sudo` (the build scripts handle this).

## Build

Build (and install) **all** community plugins:

```bash
cd community/plugins
./build.sh                # build + install (uses sudo for the gst plugin dir)
./build.sh --no-install   # build only; libs left in each plugin's build/
```

Or build a single plugin:

```bash
cd community/plugins/<plugin>
./build.sh
```

Verify after install with `gst-inspect-1.0 <element-name>`.

## Plugins

| Plugin (gst element) | Source dir | Prerequisites | Purpose |
|---|---|---|---|
| `hailooverlay_community` | `overlay_community/` | `libyaml-cpp-dev` (`sudo apt install libyaml-cpp-dev`) | Community overlay element — draws detections, classifications, landmarks, IDs and other HailoObjects onto frames with configurable styling (yaml-cpp driven `style_config`). Drop-in alternative to the stock `hailooverlay`. |
| `hailotilecropper_dynamic` | `hailotilecropper_dynamic/` | none beyond TAPPAS + GStreamer | Dynamic tiling cropper — crops tiles defined dynamically by upstream pipeline elements and/or statically by properties. Bundles its own `GstHailoBaseCropperDyn` base class so it loads in pipelines that don't bring in the system-wide TAPPAS base cropper. |

### App-bundled elements (built with their app, not here)

| Plugin (gst element) | Source dir | Build | Purpose |
|---|---|---|---|
| `hailovampire_overlay` | `community/apps/pipeline_apps/vampire_mirror/postprocess/` | that dir's `build.sh` (or auto via the app's `run.sh`) | Paints "vampire" pixels with the corresponding region of a shared-memory background buffer. App-specific to `vampire_mirror`, so it ships with the app. |

## Usage examples

### hailooverlay_community
```
... ! hailooverlay_community ! videoconvert ! autovideosink
```
Used by community pipeline apps (gesture_detection, bubble_pop, …) as a drop-in
replacement for the stock `hailooverlay` with community styling. From Python
pipelines, `OVERLAY_PIPELINE(community=True, ...)` emits this element — build the
plugin first.

### hailotilecropper_dynamic
```
... ! hailotilecropper_dynamic ! <inference> ! hailotileaggregator ! ...
```
See `hailotilecropper_dynamic/examples/tiling_dynamic_demo.py` and the plugin's
own `README.md`. Unit tests build with the plugin (when `gstreamer-check-1.0` is
present) — run `meson test -C hailotilecropper_dynamic/build`; the e2e pytest
suite lives under `hailotilecropper_dynamic/tests/e2e/`.

## Provenance

These plugins were integrated for the community release from the `community_apps`
(2026-06-07) and `community_plugins` (2026-05-26) branches. The `community_apps`
versions are the newest and authoritative for the overlay element; the
`hailotilecropper_dynamic` was ported from `community_plugins` with a TAPPAS 5.3
build fix applied during integration. They were moved here (out of
`hailo_apps/postprocess/cpp/`) to make them fully opt-in and decoupled from the
official postprocess build.
