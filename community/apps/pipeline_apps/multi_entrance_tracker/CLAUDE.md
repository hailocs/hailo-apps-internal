# Multi-Entrance Face Re-Identification Tracker

## What This App Does
Cross-camera face tracking across multiple store entrances. Detects faces with SCRFD, computes ArcFace embeddings, and matches the same person across different entrance cameras via a LanceDB vector database, logging entry/exit events with timestamps.

## Architecture
- **Type:** Pipeline app (multi-stream face re-ID)
- **Pattern:** N sources → round-robin → SCRFD detection → tracker → cropper (align + ArcFace) → unified callback (LanceDB lookup) → stream router → per-entrance displays
- **Models:** SCRFD face detection (SCRFD_10G on hailo8/hailo10h, SCRFD_2.5G on hailo8l) + `arcface_mobilefacenet` embedding
- **Hardware:** hailo8, hailo8l, hailo10h
- **Postprocess:** C++ `.so`: detection, face recognition (ArcFace), align, crop; `libtappas_set_stream_id_tool.so` for stream IDs

## Key Files
| File | Purpose |
|------|---------|
| `multi_entrance_tracker.py` | Entry point + callback: cross-camera match tracking, per-entrance unique-face counts |
| `multi_entrance_tracker_pipeline.py` | `GStreamerApp` subclass: per-source re-ID callbacks query LanceDB, log entry/exit, manage the `database/` persistence |

## How to Run
```bash
source setup_env.sh
python community/apps/pipeline_apps/multi_entrance_tracker/multi_entrance_tracker.py \
  --sources cam1.mp4,cam2.mp4
```
Optional: `--match-threshold 0.1`.

## How to Extend
- Add dwell-time analytics per entrance, or build a visitor-journey graph of entrance sequences.
- Tune `--match-threshold` to trade re-ID precision vs recall.
