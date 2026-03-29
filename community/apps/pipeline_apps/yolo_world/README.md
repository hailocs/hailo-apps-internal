# YOLO World — Zero-Shot Object Detection

Detect **any object** by describing it in text. No retraining required.

This app uses [YOLO World v2s](https://github.com/AILab-CVC/YOLO-World) on Hailo-10H for real-time zero-shot object detection. You provide text class names (e.g., "cat", "dog", "coffee mug"), and the model detects them in the video stream using CLIP text-image similarity computed on-device.

## How It Works

1. **Text Encoding** (startup): CLIP text encoder (`openai/clip-vit-base-patch32`) converts your class names into 512-dim embeddings on CPU
2. **Detection** (real-time): YOLO World HEF on Hailo-10H takes the video frame + text embeddings and outputs bounding boxes with class scores
3. **Display**: OpenCV draws detections on each frame

The text-image contrastive matching runs entirely on the Hailo accelerator. Changing detected classes only requires swapping the text embeddings — no model recompilation needed.

## Prerequisites

- **Hardware**: Hailo-10H (Hailo-8 and Hailo-8L are not supported — the dual-input HEF architecture requires Hailo-10H)
- **Model**: `yolo_world_v2s` HEF (auto-downloaded on first run)
- **Python packages**: `transformers`, `torch` (for text encoding; not needed if using cached embeddings)

Install text encoder dependencies:
```bash
pip install transformers torch
```

## Usage

```bash
# Activate environment first
source setup_env.sh

# Default COCO-80 classes
python community/apps/pipeline_apps/yolo_world/yolo_world.py --input usb

# Custom classes via CLI
python community/apps/pipeline_apps/yolo_world/yolo_world.py --input usb \
    --prompts "cat,dog,person,car"

# Custom classes via file
python community/apps/pipeline_apps/yolo_world/yolo_world.py --input usb \
    --prompts-file my_classes.json

# Live prompt updates (edit the file while running)
python community/apps/pipeline_apps/yolo_world/yolo_world.py --input usb \
    --prompts-file my_classes.json --watch-prompts

# Pre-cached embeddings (no torch/transformers needed)
python community/apps/pipeline_apps/yolo_world/yolo_world.py --input usb \
    --embeddings-file embeddings.json
```

### Prompts File Format

A simple JSON array of class names:
```json
["cat", "dog", "person", "car", "bicycle"]
```

Maximum 80 classes. Use bare class names (not "a photo of a cat").

## CLI Arguments

| Argument | Type | Default | Description |
|---|---|---|---|
| `--input` | str | required | Video source: `usb`, file path, or RTSP URL |
| `--prompts` | str | None | Comma-separated class names |
| `--prompts-file` | str | None | Path to JSON prompts file |
| `--embeddings-file` | str | `embeddings.json` | Path to cached embeddings |
| `--confidence-threshold` | float | 0.3 | Detection confidence filter |
| `--watch-prompts` | flag | False | Watch prompts file for live updates |
| `--show-fps` | flag | False | Display FPS counter |

## Architecture

```
┌─────────────────────────────────────────────┐
│ GStreamer Pipeline                           │
│ USB Camera → videoscale(640x640) → callback  │
│                                    ↓         │
│              ┌─────────────────────┤         │
│              │ Python Callback     │         │
│              │  ┌────────────┐     │         │
│              │  │ HailoRT    │     │         │
│              │  │ VDevice    │     │         │
│              │  │            │     │         │
│              │  │ image ─────┤     │         │
│              │  │ text_emb ──┤→ HEF│         │
│              │  │            │     │         │
│              │  └──────┬─────┘     │         │
│              │         ↓           │         │
│              │  postprocess (NMS)  │         │
│              │         ↓           │         │
│              │  OpenCV overlay     │         │
│              └─────────────────────┤         │
│                                    ↓         │
│ fakesink ← ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘         │
│ OpenCV window ← frame display               │
└─────────────────────────────────────────────┘

Text Embedding Manager (background):
  CLIP encoder (CPU) → embeddings.json → HailoRT input_layer2
  File watcher → re-encode on prompts change
```

## Performance

| Metric | Value |
|---|---|
| Model | YOLO World v2s (640x640) |
| FPS | ~45 (batch=1) |
| mAP (COCO) | 31.6 (quantized) |
| Max classes | 80 |

## Customization

- **Different classes**: Use `--prompts` or `--prompts-file`
- **Sensitivity**: Adjust `--confidence-threshold` (lower = more detections)
- **Live updates**: Use `--watch-prompts` with a prompts file, edit while running
- **Offline mode**: Generate embeddings once, then use `--embeddings-file` without torch
