# Hotdog Not Hotdog

A real-time "hotdog or not hotdog" classifier using CLIP zero-shot classification on Hailo-8. Point your camera at anything and get an instant verdict: **HOTDOG!** or **NOT HOTDOG!**

Inspired by the [Silicon Valley TV show](https://www.hbo.com/silicon-valley) — but running entirely on edge hardware.

## How It Works

The app uses CLIP (Contrastive Language-Image Pre-training) to compare each video frame against text embeddings for "hotdog" and several background classes ("food", "person", "animal", "object", "room"). CLIP's image encoder runs on the Hailo-8 accelerator, producing an embedding that's compared against the text embeddings via softmax similarity. If "hotdog" wins, it's a hotdog. If any background class wins, it's not.

Background classes are used instead of a "not hotdog" prompt because CLIP doesn't handle negation well — "not hotdog" still encodes hotdog visual features, making discrimination unreliable.

**Text embeddings are cached**: On first run, the text encoder runs once on the Hailo device to compute embeddings for all prompts and saves them to `embeddings.json`. Subsequent runs load instantly from cache. Use `--regenerate-embeddings` to re-encode if you change the prompts.

## Prerequisites

- Hailo-8 or Hailo-8L accelerator
- USB camera (or video file)
- CLIP model resources downloaded (`hailo-download-resources`)

## Usage

```bash
# Activate environment
source setup_env.sh

# Run with USB camera (GStreamer overlay — no OpenCV drawing)
python community/apps/pipeline_apps/hotdog_not_hotdog/hotdog_not_hotdog.py --input usb

# Run with USB camera + OpenCV verdict overlay
python community/apps/pipeline_apps/hotdog_not_hotdog/hotdog_not_hotdog.py --input usb --use-frame

# Run with a video file
python community/apps/pipeline_apps/hotdog_not_hotdog/hotdog_not_hotdog.py --input path/to/video.mp4 --use-frame

# Adjust classification threshold (default: 0.5)
python community/apps/pipeline_apps/hotdog_not_hotdog/hotdog_not_hotdog.py --input usb --use-frame --threshold 0.6

# Force re-encode text embeddings (after changing prompts)
python community/apps/pipeline_apps/hotdog_not_hotdog/hotdog_not_hotdog.py --input usb --regenerate-embeddings
```

## Architecture

```
USB Camera → [Source] → tee ──→ [Bypass Queue] ──────────────────→ hailomuxer → [Matching Callback] → [User Callback] → Display
                          └──→ [videoscale] → [CLIP Image Encoder] ──→┘
                                                (Hailo-8)
```

- **CLIP Image Encoder** — Runs on Hailo-8, produces 512-dim image embeddings per frame
- **Matching Callback** — Compares image embedding against cached text embeddings (hotdog + 5 background classes), adds `HAILO_CLASSIFICATION` metadata with the winning class
- **User Callback** — Reads classification: "hotdog" → HOTDOG!, anything else → NOT HOTDOG!. Draws verdict overlay when `--use-frame` is used

## Models

| Model | Architecture | Purpose |
|-------|-------------|---------|
| `clip_vit_b_32_image_encoder` | hailo8, hailo8l, hailo10h | Encode video frames to CLIP embeddings (runs every frame) |
| `clip_vit_b_32_text_encoder` | hailo8, hailo8l, hailo10h | Encode text prompts to embeddings (runs once, cached to `embeddings.json`) |

## Customization

- **Change threshold**: Use `--threshold` to adjust how confident the classifier needs to be
- **Change prompts**: Edit the `prompts` list in `_load_or_generate_embeddings()` in `hotdog_not_hotdog_pipeline.py`, then run with `--regenerate-embeddings`
- **Different target object**: Replace "hotdog" with any visual concept CLIP understands. Keep diverse background classes for reliable discrimination
