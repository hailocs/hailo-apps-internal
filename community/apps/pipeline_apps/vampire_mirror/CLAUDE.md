# Vampire Mirror

## What This App Does
A real-time "mirror" in which enrolled "vampires" are rendered invisible. YOLOv5 instance segmentation + ByteTrack produce pixel-accurate person masks; a C++ overlay element composites a dynamic EMA background over vampire pixels, and the display shows a portrait center-crop from a wider landscape capture.

## Architecture
- **Type:** Pipeline app (instance segmentation)
- **Pattern:** Camera (landscape) → YOLOv5-seg → ByteTrack → Python callback (mask union + VampireEngine) → C++ `hailovampire_overlay` (background composite via SHM) → portrait crop → display
- **Models:** YOLOv5m_seg (yolov5n_seg on hailo8l)
- **Hardware:** hailo8, hailo8l, hailo10h
- **Postprocess:** C++ `libyolov5seg_postprocess.so` + custom `hailovampire_overlay` element reading background from POSIX shared memory

## Key Files
| File | Purpose |
|------|---------|
| `vampire_mirror.py` | Entry point + callback: build person-mask union, submit background, run VampireEngine, tag vampires |
| `vampire_mirror_pipeline.py` | `GStreamerInstanceSegmentationApp` subclass; vampire CLI args (`--mirror-ratio`, `--bg-alpha`, etc.) |
| `vampire_engine.py` | Per-track state machine (HUMAN/VAMPIRE/UNKNOWN); face-recognition placeholder |
| `background_manager.py` | In-process background EMA (used with `--no-bg-process`) |
| `bg_service.py` | Subprocess background EMA + double-buffered SHM publisher (default) |
| `bg_shm.py` | POSIX shared-memory helpers (mmap, semaphores) |
| `frame_geometry.py` | Portrait-crop coordinate math, buffer zone, padding detection |

## How to Run
```bash
source setup_env.sh
python community/apps/pipeline_apps/vampire_mirror/vampire_mirror.py --input usb --width 1280 --height 720
```
Optional: `--mirror-ratio 9:16`, `--show-overlay` (debug), `--no-bg-process` (in-process mode), `--dilate-radius`.

## How to Extend
- Wire SCRFD+ArcFace face embeddings into `VampireEngine.decide()` to actually identify vampires (currently all persons stay visible).
- Tune `--dilate-radius` / `--dilate-iterations` to control the invisibility "halo" around vampire bodies.
