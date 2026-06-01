# YOLO World Application

![YOLO World Example](../../../../doc/images/yolo_world.gif)

Open-vocabulary, zero-shot object detection: detect **anything you describe in text** — no retraining, classes changeable at runtime. Supported on **Hailo-8** and **Hailo-10H**; the `yolo_world_v2s` HEF is dual-input either way (image + 80×512 text embeddings).

#### Run the YOLO World example:
```bash
hailo-yolo-world
```
To close the application, press `Ctrl+C`.

By default it detects the COCO-80 classes. Provide your own classes with `--prompts`:
```bash
hailo-yolo-world --prompts "person, water glass, houseplant"
```

#### Running with Raspberry Pi Camera input:
```bash
hailo-yolo-world --input rpi
```

#### Running with USB camera input (webcam):
There are 2 ways:

Specify the argument `--input` to `usb`:
```bash
hailo-yolo-world --input usb
```
This will automatically detect the available USB camera (if multiple are connected, it will use the first detected).

Second way — detect the available camera, then pass the device:
```bash
get-usb-camera
hailo-yolo-world --input /dev/video<X>
```

For additional options, execute:
```bash
hailo-yolo-world --help
```

#### Running as Python script

```bash
python yolo_world.py --input usb --prompts "person, dog, laptop"
```

#### App logic

You supply free-text class names; a CLIP text encoder turns them into embeddings that the `yolo_world_v2s` HEF uses to score every region. The "business logic" lives in Python's `app_callback`: it runs the dual-input HEF (image + text embeddings), reads the on-device CPU NMS output (a single `yolov8_nms_postprocess` tensor with `[y1, x1, y2, x2, score]` per box, already score-thresholded and NMS'd on chip), stabilizes detections across frames, and attaches them as `hailo.HailoDetection` metadata for `hailooverlay` to draw.

The `YoloWorldCallbackData` class shares state (inference engine, embedding manager, detection stabilizer) with the pipeline class `GStreamerYoloWorldApp`.

#### Prompts

- Pass `--prompts "a, b, c"` or `--prompts-file classes.json` (a JSON array of up to 80 class names).
- Embeddings are cached to `embeddings.json` and re-encoded automatically when the prompts file changes (`--watch-prompts`).

##### Deploying with frozen prompts (no CLIP encoder at runtime)

For products with a fixed class set, encode once on a dev machine and ship the
resulting embeddings JSON alongside the HEF. At runtime the app loads the cached
vectors directly — the CLIP text encoder is never built (weights aren't loaded,
no tokenizer initialized).

```bash
# Once, on a dev machine:
hailo-yolo-world --prompts-file classes.json --run-duration 1
# → writes embeddings.json (labels + (N, 512) float32 vectors) into the app dir

# On the deployment target — ship only the HEF + embeddings.json:
hailo-yolo-world --embeddings-file embeddings.json
# CLIP body weights, tokenizer, encoder = never loaded.
# ~30 MB less resident memory and faster startup.
```

Without `--prompts` / `--prompts-file` the app picks up `embeddings.json` from
the app directory automatically (or whatever path `--embeddings-file` points
at). The encoder is constructed lazily, so on a deploy that always uses the
cache, the CLIP body weights resource is never touched at runtime.

##### Prompt phrasing matters

Open-vocabulary detection is very sensitive to phrasing — small word changes can move detection quality from rock-solid to near-zero. Two rules of thumb:

- **Use concrete nouns the model was trained on.** Out-of-distribution phrasings ("fidget toy", "leafy plant", "flower pot") often score ~0 and the model can latch onto the nearest in-vocab class instead, producing confident *false* labels ("fire hydrant" on a colorful object). The default COCO-80 set works for canonical objects in normal scenes; for anything else, try the LVIS / Objects365 category space.
- **Iterate on synonyms when a class detects weakly.** "potted plant" peaked at 0.25 in one office scene while "houseplant" / "indoor plant" peaked at 0.95 in the same frames. Run `hailo-yolo-world --interactive` and use `?word` in the panel to rank near-synonyms by what *actually* detects on recent frames — that's the fastest path to a stable prompt.

#### Interactive mode

```bash
hailo-yolo-world --input usb --prompts "person" --interactive
```
A terminal panel lets you change classes live: type names to **replace**, `+name` to **add**, `-name` to **remove**, and `?name` to get a **"did you mean"** suggestion ranked by how strongly each phrasing actually detects.

#### Text encoder

Text embeddings are produced by a pure-NumPy CLIP ViT-B/32 encoder (numerically identical to HuggingFace `openai/clip-vit-base-patch32`), so the app needs **no `torch`/`transformers`** at runtime — only `numpy` + `tokenizers`. The encoder body weights (`clip_text_vitb32_body_fp16.npz`) are a downloaded resource; regenerate them offline with `extract_clip_text_weights.py`.

#### Resolution

The pipeline runs the detector at 640×640. Source resolution can be set via:
```bash
self.video_width
self.video_height
```

#### Running with different models

See our [hailo_model_zoo](https://github.com/hailo-ai/hailo_model_zoo) for additional supported models.

By default, the package contains a single model depending on the device architecture.
You can download additional models by running `hailo-download-resources --all`.
The models are downloaded to the `resources/models/` directory.

#### Performance

End-to-end pipeline FPS measured on the bundled HEFs (USB camera input, COCO-80 prompts, default 0.3 confidence threshold):

| Arch | Pipeline FPS | Per-frame callback (mean) | Inference (mean) | Postprocess (mean) |
|---|---:|---:|---:|---:|
| Hailo-8 | ~30 | ~33 ms | ~32 ms | < 0.5 ms |
| Hailo-10H | ~28 | ~36 ms | ~35 ms | < 0.5 ms |

On-device CPU NMS keeps the host-side postprocess at sub-millisecond cost — the model itself is the bottleneck on both archs. Reducing the active prompt count does **not** speed up inference at runtime (the text input is always padded to 80); for higher throughput, recompile the HEF with a smaller `classes` parameter in the NMS config.

#### HEF provenance

| Arch | DFC | Model Zoo | Notes |
|---|---|---|---|
| Hailo-8 / Hailo-8L | 3.33 | v2.18 | on-device CPU NMS, 6-output → 1 fused stream via HRT 4.x |
| Hailo-10H | 5.4 | v5.4 (dev) | on-device CPU NMS, single `yolov8_nms_postprocess` output exposed by HRT 5.x |

#### Retrained Networks Support
YOLO World is published for fine-tuning (normal / prompt-tuning / reparameterized). For reliable detection of a fixed class set, fine-tune in the [AILab-CVC/YOLO-World](https://github.com/AILab-CVC/YOLO-World) framework and recompile to a HEF. For more information, see [Using Retrained Models](../../../../doc/developer_guide/retraining_example.md).

## Command Line Arguments

### Application specific arguments:
```bash
--prompts <str>              # Comma-separated class names, e.g. "cat,dog,person"
--prompts-file <path>        # Path to a JSON array of class names (max 80)
--embeddings-file <path>     # Path to cached embeddings JSON
--confidence-threshold <f>   # Detection confidence threshold (default 0.3)
--watch-prompts              # Reload the prompts file on change
--interactive                # Live prompt control panel in the terminal
```

### All pipeline commands support these common arguments:

[Common arguments](../../../../doc/user_guide/running_applications.md#command-line-argument-reference)
