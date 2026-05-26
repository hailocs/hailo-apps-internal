# hailotilecropper_dynamic

A GStreamer plugin that crops video tiles whose locations come from upstream
pipeline elements (per-buffer, dynamic) and/or from element properties (static).
Drop-in compatible with TAPPAS `hailotileaggregator`.

## When to use this

The standard `hailotilecropper` only supports regular grids: `tiles-along-x-axis`,
`tiles-along-y-axis`, and uniform overlap. Use `hailotilecropper_dynamic` when
you need:

- A tile around a specific tracked object every frame.
- Variable tile count per frame based on application state.
- A small fixed set of "always-on" tiles combined with dynamic ones.
- To skip cropping entirely (bypass-only) when no tile is needed.

## Building & installing

The plugin builds as part of the standard repo postprocess build:

```bash
source setup_env.sh
hailo-compile-postprocess
```

This installs `libgsthailotilecropper_dynamic.so` to GStreamer's plugin dir
(`/usr/lib/x86_64-linux-gnu/gstreamer-1.0/` on a typical x86_64 system,
resolved via `pkg-config --variable=pluginsdir gstreamer-1.0`). Verify:

```bash
rm -f ~/.cache/gstreamer-1.0/registry.x86_64.bin
gst-inspect-1.0 hailotilecropper_dynamic
```

## Pad layout

Inherited from `GstHailoBaseCropperDyn` (our private rename of TAPPAS's
`GstHailoBaseCropper` — see Implementation notes below):

| Pad name  | Direction | Role                                                |
|-----------|-----------|-----------------------------------------------------|
| `sink`    | sink      | Incoming video buffer.                              |
| `src_0`   | source    | Bypass — original buffer with all tile sub-objects attached. Goes to `hailotileaggregator.sink_0`. |
| `src_1`   | source    | Cropped — one buffer per tile, in tile-local coords. Goes to `hailotileaggregator.sink_1`. |

## Properties

| Property        | Type    | Default | Description                                                                                  |
|-----------------|---------|---------|----------------------------------------------------------------------------------------------|
| `tiles-static`  | string  | `""`    | Semicolon-separated list of `x,y,w,h` rectangles, normalized 0..1. Appended to dynamic tiles each frame. Out-of-range or unparseable entries are dropped with `GST_WARNING`. |
| `allow-empty`   | boolean | `true`  | If `false`, log a warning when a buffer produces zero tiles.                                 |

Inherited from the base class: `internal-offset`, `cropping-period`,
`drop-uncropped-buffers`, `filter-streams`.

## Attaching dynamic tiles from Python

**Use `identity signal-handoffs=true` + `handoff` callback**, not pad probes.
Python pad probes receive a non-writable buffer reference (refcount > 1), so
`gst_buffer_add_hailo_meta()` silently fails. The `handoff` signal fires inside
the `identity` chain function while the buffer is still writable.

```python
import hailo
from gi.repository import Gst

# Pipeline: ... ! identity name=tile_setter signal-handoffs=true ! hailotilecropper_dynamic ! ...
def attach_tiles(_identity, buf):
    roi = hailo.get_roi_from_buffer(buf)
    # Add a tile around the tracked object's bbox (normalized 0..1):
    roi.add_object(hailo.HailoTileROI(
        hailo.HailoBBox(0.3, 0.4, 0.2, 0.2),
        index=0, overlap_x_axis=0.0, overlap_y_axis=0.0, layer=0,
        mode=hailo.SINGLE_SCALE,
    ))

pipeline.get_by_name("tile_setter").connect("handoff", attach_tiles)
```

The plugin reads all `HAILO_TILE` sub-objects from the parent ROI on each
buffer, prepends them to the static-tile list, and crops accordingly.

## Pipeline composition

Standard pattern (matches the existing TAPPAS tiling app):

```
... ! identity name=tile_setter signal-handoffs=true !
hailotilecropper_dynamic name=tc tiles-static="..." !
  tc.src_0 ! queue ! agg.sink_0
  tc.src_1 ! queue ! <inference> ! agg.sink_1
hailotileaggregator name=agg flatten-detections=true iou-threshold=0.3 !
agg.src ! hailooverlay ! videoconvert ! autovideosink
```

**Important:** put `hailooverlay` between `hailotileaggregator` and any
caps-querying sink (`videoconvert`, `autovideosink`, etc.). The existing
`hailotileaggregator` does not advertise caps on its `src` pad; pipelines
that go directly from aggregator to a caps-querying element will crash with
`gst_pad_query_accept_caps assertion`. `hailooverlay` mediates this and is
also where bbox/label drawing happens.

## Tests

Build and run C++ unit tests:

```bash
cd hailo_apps/postprocess && \
  meson setup --reconfigure build.release -Dbuild_tests=true && \
  ninja -C build.release && \
  meson test -C build.release --suite hailotilecropper_dynamic
```

Run Python E2E tests (the `conftest.py` preloads the freshest `.so` so tests
work even before `hailo-compile-postprocess install` runs):

```bash
pytest hailo_apps/postprocess/cpp/hailotilecropper_dynamic/tests/e2e -v
```

## Example

A runnable demo lives at `examples/tiling_dynamic_demo.py`:

```bash
DISPLAY=:0 python hailo_apps/postprocess/cpp/hailotilecropper_dynamic/examples/tiling_dynamic_demo.py
```

The demo walks a single dynamic tile across the frame using the identity-handoff
pattern.

## Implementation notes

- **Bundled `GstHailoBaseCropperDyn` base class.** The plugin extends a private
  copy of `GstHailoBaseCropper` from TAPPAS, renamed to `GstHailoBaseCropperDyn`
  to avoid a GLib `g_type_register_static` conflict with `libgsthailotools.so`
  (which registers the same type name internally). Without the rename, loading
  both .so files in the same process produced
  `cannot register existing type 'GstHailoBaseCropper'` warnings followed by
  element-registration assertion failures.
- **TAPPAS source vendored from v5.1.0** to match the installed runtime
  (`pkg-config --modversion hailo-tappas-core` → `5.1.0`). v5.3.0 introduced
  free functions `get_cv_matrices` / `crop_to_cv_matrices` that don't exist in
  the installed v5.1.0 headers.
- **Crop pad caps fallback.** Patched the bundled base cropper to fall back to
  the incoming sink caps when the downstream peer of `src_1` returns ANY caps
  (e.g. `fakesink`); upstream did not handle this case and triggered
  `gst_caps_fixate(ANY)` assertion crashes.

## License

LGPL-2.1 (derived from TAPPAS — bundled `gsthailobasecropper.{cpp,hpp}` retain
their original Hailo Technologies copyright headers).
