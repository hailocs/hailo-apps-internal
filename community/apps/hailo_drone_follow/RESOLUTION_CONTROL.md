# Seamless Resolution Control — OpenHD + drone-follow

## Overview

OpenHD's camera pipeline and the drone-follow AI pipeline are connected via
shared memory (SHM).  When the user changes the camera resolution from the
QOpenHD ground station, both pipelines must tear down and rebuild with matching
caps — seamlessly, without manual intervention.

This document explains the problem, the changes made, and how the components
interact.

---

## The Problem

Changing resolution from QOpenHD's GUI caused the system to get stuck:

1. QOpenHD sends a `RESOLUTION_FPS` parameter change via MAVLink.
2. OpenHD air receives it, persists the new value, and restarts its camera
   pipeline.
3. The SHM socket (`/tmp/openhd_raw_video`) is destroyed and recreated with
   a new buffer layout.
4. drone-follow's `shmsrc` gets an error when the socket disappears.
5. drone-follow had **hardcoded caps** from CLI args (defaulting to 1280×720).
   After the resolution change, the caps no longer matched — pipeline failure.
6. OpenHD's pipeline teardown could **hang** if drone-follow still held the
   SHM region mapped.

The result: "Restarting camera…" displayed indefinitely in QOpenHD.

---

## The Solution

Changes were made to three components:

### 1. OpenHD — SHM Metadata File

**File:** `ohd_video/src/gstreamerstream.cpp` (in `setup()`)

On every pipeline start, OpenHD now writes a sideband metadata file alongside
the SHM socket:

```
/tmp/openhd_raw_video       ← Unix domain socket (shmsink)
/tmp/openhd_raw_video.meta  ← JSON metadata (new)
```

Contents (example):
```json
{"width":1280,"height":720,"fps":30}
```

This file is written **before** the pipeline enters PLAYING, so it is always
available when the socket appears.

**Constant:** `openhd::HAILO_RAW_SHM_META` in `openhd_global_constants.hpp`

### 2. OpenHD — Safe shmsink Teardown

**File:** `ohd_video/src/gstreamerstream.cpp` (in `cleanup_pipe()`)

Before setting the full pipeline to NULL, the `hailo_shmsink` element is
individually set to NULL and the socket file is removed:

```cpp
GstElement* shmsink = gst_bin_get_by_name(GST_BIN(m_gst_pipeline), "hailo_shmsink");
if (shmsink) {
    gst_element_set_state(shmsink, GST_STATE_NULL);
    gst_object_unref(shmsink);
    OHDFilesystemUtil::remove_if_existing(openhd::HAILO_RAW_SHM_SOCKET);
}
```

This prevents the full pipeline NULL from blocking when a consumer (drone-follow)
has the SHM region mapped.

### 3. drone-follow — Auto-detect Resolution from Metadata

**File:** `drone_follow/pipeline_adapter/hailo_drone_detection_manager.py`

Three changes:

- **`_read_shm_resolution()`** — reads `/tmp/openhd_raw_video.meta` and returns
  `(width, height, fps)`.

- **`_shm_source_pipeline()`** — auto-detects resolution from metadata instead
  of using hardcoded CLI args. Falls back to CLI values if metadata is absent.

- **`bus_call()` / `_shm_wait_for_socket()` / `_shm_rebuild()`** — on SHM
  pipeline error, polls every 500ms for the socket and metadata to reappear
  (up to 30s), then rebuilds the pipeline with the new resolution from the
  metadata file.

---

## Full-FOV Resolution Handling

### The Problem (60fps modes)

The IMX708 sensor has two relevant readout modes:

| Mode | Resolution | Max fps | FOV |
|------|-----------|---------|-----|
| Binned (Mode 0) | 2304×1296 | ~56 | Full sensor |
| Cropped (Mode 1) | 1536×864 | 120 | Center crop |

Originally, `getFullFovIspResolution()` returned `{2304, 1296}` for IMX708
and the pipeline always requested this resolution from the ISP, then
crop+scaled to the target.  At 60fps this **failed silently** — the sensor
cannot read out 2304×1296 at 60fps, so zero frames were produced, triggering
an infinite restart loop.

### The Fix

**File:** `ohd_video/inc/gst_helper.hpp`

`getFullFovIspResolution()` now returns a struct with `max_fps`:

```cpp
struct FullFovMode { int width; int height; int max_fps; };

// IMX708:
return {2304, 1296, 56};  // max ~56fps at full-FOV binned mode
```

The `createLibcamerasrcStream()` function checks:
```cpp
const bool use_full_fov = ... && target_fps <= fov.max_fps;
```

When the target fps exceeds the sensor's full-FOV maximum, the full-FOV
override is skipped. The ISP then picks a faster sensor mode (1536×864 for
IMX708), which supports up to 120fps but has a narrower FOV (center crop).

### FOV Behavior Summary (IMX708)

| Target | fps ≤ 56 | fps = 60 |
|--------|----------|----------|
| Any resolution | **Full FOV** — ISP reads 2304×1296, crop+scale to target | **Center crop** — ISP uses 1536×864 sensor mode |

---

## Available Resolutions (IMX708)

The resolution menu in QOpenHD now offers:

| Resolution | Aspect | 15fps | 30fps | 60fps |
|-----------|--------|-------|-------|-------|
| 640×480   | 4:3    | ✓ Full FOV | ✓ Full FOV | ✓ Center crop |
| 896×504   | 16:9   | ✓ Full FOV | ✓ Full FOV | ✓ Center crop |
| 1280×720  | 16:9   | ✓ Full FOV | ✓ Full FOV | ✓ Center crop |
| 1920×1080 | 16:9   | ✓ Full FOV | ✓ Full FOV | — (sensor limit) |

**Default:** 1280×720 @ 30fps (full FOV, set by RPi5 `create_default()`)

---

## Resolution Change Flow

```
User selects new resolution in QOpenHD
  → MAVLink PARAM_EXT_SET("RESOLUTION_FPS", "640x480@30")
    → OpenHD air: persist() → request_restart()
      → cleanup_pipe():
          - Set hailo_shmsink to NULL (unblocks consumer)
          - Remove /tmp/openhd_raw_video socket
          - Set full pipeline to NULL
      → setup():
          - Build new pipeline with new resolution
          - Write /tmp/openhd_raw_video.meta: {"width":640,"height":480,"fps":30}
          - Create new shmsink socket
      → start(): pipeline enters PLAYING, frames flow
    → drone-follow:
        - bus_call() receives SHM error (old socket gone)
        - _shm_wait_for_socket() polls every 500ms
        - Socket + metadata appear
        - _shm_rebuild() reads metadata → updates caps → rebuilds pipeline
    → QOpenHD: "Restarting Camera..." clears when frames arrive
```

---

## Files Modified

### OpenHD (C++ — air unit binary)

| File | Change |
|------|--------|
| `ohd_common/inc/openhd_global_constants.hpp` | Added `HAILO_RAW_SHM_META` constant |
| `ohd_video/inc/gst_helper.hpp` | `FullFovMode` struct with `max_fps`; framerate check in `createLibcamerasrcStream()`; named shmsink `hailo_shmsink` |
| `ohd_video/src/gstreamerstream.cpp` | Metadata file writing in `setup()`; safe shmsink detach in `cleanup_pipe()` |
| `ohd_video/inc/camera.hpp` | Expanded IMX708 resolution list (15/30/60fps for each size) |

### QOpenHD (C++ — ground unit binary)

| File | Change |
|------|--------|
| `app/telemetry/models/openhd_core/camera.hpp` | Same expanded IMX708 resolution list |

### drone-follow (Python — air unit)

| File | Change |
|------|--------|
| `drone_follow/pipeline_adapter/hailo_drone_detection_manager.py` | `_read_shm_resolution()`, auto-detect in `_shm_source_pipeline()`, socket polling in `_shm_wait_for_socket()`, rebuild in `_shm_rebuild()` |

---

## Rebuilding After Changes

**OpenHD** (air unit):
```bash
cd ~/hailo-drone-follow/OpenHD/OpenHD
sudo cmake --build build_release -j$(nproc)
sudo cp build_release/openhd /usr/local/bin/openhd
```

**QOpenHD** (ground unit):
```bash
cd ~/hailo-drone-follow/qopenHD/build/release
make -j$(nproc)
cp release/QOpenHD QOpenHD_hailo_dynamic
```

**drone-follow**: No build needed — Python changes take effect on restart.
