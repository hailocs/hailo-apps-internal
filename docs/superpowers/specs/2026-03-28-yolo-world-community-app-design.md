# YOLO World Community App — Design Spec

**Date:** 2026-03-28
**Location:** `community/apps/pipeline_apps/yolo_world/`
**Target Hardware:** Hailo-10H (structured for easy addition of other archs later)

## Overview

A GStreamer pipeline app for **zero-shot object detection** using YOLO World v2s on Hailo-10H. Users can detect arbitrary objects by providing text prompts — no retraining needed. The app generates CLIP text embeddings from prompts and feeds them as the second input to the YOLO World HEF, which performs text-image contrastive matching on-device.

## Architecture

### Two-Phase Design

1. **Text Encoder Phase** (CPU, on-demand): Generates CLIP text embeddings from user prompts using HuggingFace `CLIPTextModelWithProjection` (`openai/clip-vit-base-patch32`). Runs at startup and whenever prompts are updated at runtime.

2. **Detection Phase** (GStreamer + Hailo): Standard detection pipeline running YOLO World v2s HEF with cached embeddings injected as the second input tensor.

> **Note on text encoder:** The original plan was to use a CLIP text encoder HEF on Hailo. Research into the model zoo revealed that text embeddings are generated using HuggingFace's `CLIPTextModelWithProjection` on CPU. This is a one-time lightweight operation (~50ms per prompt set) and is what the model zoo itself uses. The 1x80x512 embedding tensor is then fed as `input_layer2` to the YOLO World HEF.

### Pipeline Structure

```
SOURCE → INFERENCE_PIPELINE(yolo_world_v2s, nms_config) → hailooverlay → DISPLAY
```

Standard detection pipeline. The YOLO World HEF is a dual-input model — the image comes from the pipeline, and the text embeddings are injected as a constant second input that updates when prompts change.

### On-the-fly Prompt Updates

When the user triggers a prompt change:
1. `TextEmbeddingManager.update_prompts(new_prompts)` runs the CLIP text encoder on CPU
2. New embeddings are assembled into a 1x80x512 tensor (zero-padded if <80 classes)
3. Labels list is updated to match new prompts
4. The embedding tensor reference is swapped atomically (thread-safe via Python GIL)
5. Detection pipeline picks up new embeddings on the next frame — no pipeline restart

**Prompt change trigger mechanism:** Watching a prompts file for changes (simple, works with any editor). The app watches `--prompts-file` for modifications and reloads automatically. This allows external tools or scripts to update detection classes while the pipeline runs.

**Prompts file format** (`my_classes.json`):
```json
["cat", "dog", "person", "car", "bicycle"]
```
A simple JSON array of bare class names (max 80). No prompt templates — YOLO World was trained on bare names.

## File Layout

```
community/apps/pipeline_apps/yolo_world/
├── yolo_world.py                  # Entry point + app_callback
├── yolo_world_pipeline.py         # GStreamerApp subclass
├── text_embedding_manager.py      # CLIP text encoder + embedding cache + file watcher
├── default_prompts.json           # Default COCO-80 class names
├── embeddings.json                # Cached embeddings (generated on first run)
├── README.md                      # User documentation
└── CLAUDE.md                      # Developer notes
```

## Component Details

### 1. TextEmbeddingManager (`text_embedding_manager.py`)

Encapsulates all text encoder logic.

**Responsibilities:**
- Load `CLIPTextModelWithProjection` and `AutoTokenizer` from HuggingFace (`openai/clip-vit-base-patch32`)
- Tokenize bare class names (no prompt templates — YOLO World was trained on bare names)
- Run CLIP text encoder to produce per-prompt 512-dim embeddings
- L2-normalize embeddings
- Assemble into 1x80x512 tensor (zero-padded if fewer than 80 prompts, max 80)
- Cache embeddings to JSON file for fast reload on next startup
- Thread-safe `update_prompts(new_prompts: list[str])` method
- Thread-safe `get_embeddings() -> np.ndarray` for pipeline to read
- Maintain `labels: list[str]` mapping index → class name
- Optional file watcher on `--prompts-file` for runtime updates

**Startup logic:**
1. If `--prompts` CLI arg provided → encode those prompts, cache
2. Else if `--prompts-file` provided → load prompts from file, encode, cache
3. Else if `embeddings.json` exists → load cached embeddings
4. Else → load `default_prompts.json` (COCO-80 class names), encode, cache

**Dependencies:** `transformers`, `torch` (CPU-only, for text encoder)

### 2. GStreamer Pipeline (`yolo_world_pipeline.py`)

Standard GStreamerApp subclass following the detection pattern.

**Pipeline:**
```
SOURCE_PIPELINE → INFERENCE_PIPELINE(hef=yolo_world_v2s, post_process_so=libyolo_hailortpp_postprocess.so, nms_config=yolo_world_v2s_nms_config.json) → hailooverlay → DISPLAY_PIPELINE
```

**Dual-input handling:** The key challenge is feeding the text embedding tensor as `input_layer2` alongside the image. This needs investigation during implementation — possible approaches:
- Configure `hailonet` element to accept a second input via properties
- Use HailoRT multi-input vstream configuration
- Attach embeddings as buffer metadata before `hailonet`

This is the highest-risk item and should be prototyped first during implementation.

**CLI arguments:**

| Argument | Type | Default | Description |
|---|---|---|---|
| `--prompts` | str | None | Comma-separated class names: `"cat,dog,bottle"` |
| `--prompts-file` | str | None | Path to JSON file with class name list |
| `--embeddings-file` | str | `embeddings.json` | Path to cached embeddings |
| `--confidence-threshold` | float | 0.3 | Detection confidence filter |
| `--watch-prompts` | flag | False | Watch prompts-file for changes and reload |

### 3. App Callback (`yolo_world.py`)

Minimal callback — the standard `hailooverlay` element handles bounding box rendering.

**Callback responsibilities:**
- Extract detections from ROI (standard pattern)
- Apply confidence threshold filtering
- Log detection results (label, confidence, bbox) at debug level
- Dynamically update labels on the overlay element when prompts change

**Entry point:** Standard `main()` pattern — create callback data, create pipeline app, run.

### 4. Postprocessing

Uses the **standard YOLO NMS postprocess** (`libyolo_hailortpp_postprocess.so`) with YOLO World's NMS config JSON.

**What the HEF does on-device:**
- Image normalization (pixel/255.0)
- Full backbone, neck, and text-image contrastive head
- DFL regression decoding (16-bin distribution → 4 distance values)
- Sigmoid on classification scores

**What the postprocess .so does in software:**
- Reshape 6 output tensors (3 cls + 3 reg at strides 8/16/32)
- Grid-based box decoding (distances → absolute coordinates)
- NMS with IoU=0.7, score_threshold=0.001

**Labels:** Dynamically generated from current prompt list. The postprocess maps class indices to the labels list maintained by `TextEmbeddingManager`.

### 5. NMS Config

Ship a copy of `yolo_world_v2s_nms_config.json` from the model zoo, or reference it from the installed model zoo package:

```json
{
    "nms_scores_th": 0.001,
    "nms_iou_th": 0.7,
    "image_dims": [640, 640],
    "max_proposals_per_class": 300,
    "classes": 80,
    "regression_length": 16,
    "background_removal": false,
    "bbox_decoders": [
        {"name": "bbox_decoder48", "stride": 8, "reg_layer": "", "cls_layer": ""},
        {"name": "bbox_decoder60", "stride": 16, "reg_layer": "", "cls_layer": ""},
        {"name": "bbox_decoder71", "stride": 32, "reg_layer": "", "cls_layer": ""}
    ]
}
```

## Hardware Support

| Architecture | Model | Status |
|---|---|---|
| hailo10h | yolo_world_v2s | Supported (primary target) |
| hailo15h | yolo_world_v2s | Should work (same HEF family) |
| hailo8 | — | Not available (no HEF) |
| hailo8l | — | Not available (no HEF) |

Code is structured so adding new arch support is just a config change (model name mapping).

## Risks and Open Questions

### High Risk: Dual-Input HEF in GStreamer Pipeline
The YOLO World HEF has two inputs (image + text embeddings). Standard GStreamer `hailonet` element typically handles single-input models. We need to verify:
- How does `hailonet` handle multi-input HEFs?
- Can we configure `input_layer2` as a constant tensor?
- If `hailonet` doesn't support this natively, we may need to use HailoRT directly (standalone-style inference within a GStreamer appsink/appsrc wrapper)

**Mitigation:** Prototype the dual-input mechanism first. If `hailonet` can't handle it, fall back to a hybrid approach: GStreamer for video capture/display, HailoRT standalone for inference.

### Medium Risk: Text Encoder Dependencies
Adding `transformers` and `torch` (CPU) as dependencies increases the install footprint. These are only needed for text encoding, not for detection.

**Mitigation:**
- Make text encoder optional — if dependencies aren't installed, app requires pre-cached `embeddings.json`
- Ship default COCO-80 embeddings so the app works out of the box without torch/transformers
- Document the optional dependency clearly

### Low Risk: NMS Config Compatibility
The NMS config JSON's `reg_layer`/`cls_layer` fields are empty strings. Need to verify the standard postprocess .so can auto-detect layer names from the HEF.

## Testing Plan

1. **Smoke test:** Run with default COCO-80 embeddings on USB camera — verify detections appear
2. **Custom prompts:** Run with `--prompts "cat,dog,person"` — verify only those classes detected
3. **Prompt update:** Run with `--watch-prompts`, modify prompts file — verify classes change without restart
4. **Cached embeddings:** Delete `embeddings.json`, run app — verify it regenerates and caches
5. **No torch fallback:** Uninstall transformers, run with pre-cached embeddings — verify it works

## Usage Examples

```bash
# Default COCO-80 classes
python yolo_world.py --input usb

# Custom classes
python yolo_world.py --input usb --prompts "cat,dog,person,car"

# From prompts file
python yolo_world.py --input usb --prompts-file my_classes.json

# With live prompt updates
python yolo_world.py --input usb --prompts-file my_classes.json --watch-prompts

# With pre-cached embeddings (no torch needed)
python yolo_world.py --input usb --embeddings-file my_embeddings.json
```
