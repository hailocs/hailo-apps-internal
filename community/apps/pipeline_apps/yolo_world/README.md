# YOLO World — moved to the official pipeline app

The YOLO World zero-shot detection app now lives at:

```
hailo_apps/python/pipeline_apps/yolo_world/
```

The earlier community prototype that lived here has been **superseded** by the
official app from PR #202, which is the canonical, more complete implementation:

- Pure-NumPy CLIP ViT-B/32 text encoder (no torch/transformers runtime dep,
  numerically identical to HuggingFace).
- Dual-input `yolo_world_v2s` HEF driven directly via HailoRT from the GStreamer
  user callback (HailoRT 5.3 compatible; `hailonet` can't drive dual-input HEFs).
- Pure-NumPy DFL decode → grid decode → multi-label, containment-aware per-class
  NMS (~1 ms postprocess).
- Class-aware temporal stabilization (hysteresis, coasting, EMA box smoothing).
- Optional interactive prompt-tuning panel (`--interactive`) with a
  detection-aware probe.
- `hailooverlay` display path, ~20 FPS, inference-bound.

## Run it

```bash
source setup_env.sh
python hailo_apps/python/pipeline_apps/yolo_world/yolo_world.py --help
```

See `hailo_apps/python/pipeline_apps/yolo_world/README.md` for full usage,
prompt configuration, and the `--interactive` control panel.

Supported architecture: **Hailo-10H** (the dual-input `yolo_world_v2s` HEF is
H10-only).
