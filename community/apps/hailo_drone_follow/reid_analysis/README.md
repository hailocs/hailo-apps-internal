# ReID Analysis — Person Re-Identification Evaluation Framework

Evaluate and tune the YOLO + ReID person matching pipeline on the Hailo NPU.

## Architecture

```
Video Input                                         MOT17 Dataset
    |                                                    |
    v                                                    v
reid_analysis_app.py                             mot17_eval.py
(GStreamer tiling + Hailo NPU)                   (GT boxes, no detection noise)
    |                                                    |
    |-- Person detection (YOLO via hailotilecropper)     |-- Precompute embeddings from GT crops
    |-- Crop extraction (from normalized bboxes)         |-- FirstOnly vs MultiEmbedding sweep
    |-- ReID embedding (RepVGG / OSNet on Hailo)         |-- Precision / Recall / F1 + plots
    |-- Gallery matching (cosine similarity)              |
    |                                               P/R plot + table
    v
match_log.jsonl  (one entry per detected crop)
    |
    v
reid_eval.py  (offline metrics from log + ground truth)
    |
    v
Precision, Fragmentation, ID Switches
    |
    v
reid_sweep.py  (automated parameter grid search)

reid_benchmark.sh — Measure FPS & latency for ReID HEFs via hailortcli
```

## Files

| File | Purpose |
|------|---------|
| `reid_analysis_app.py` | Main pipeline: detect, embed, match, log |
| `reid_eval.py` | Compute metrics and sweep thresholds offline |
| `reid_embedding_extractor.py` | Hailo ReID embedding extraction (RepVGG / OSNet) |
| `gallery_strategies.py` | Pluggable gallery update strategies |
| `reid_sweep.py` | Parameter sweep runner (model x threshold x strategy) |
| `mot17_eval.py` | MOT17 ground-truth evaluation (no detection noise) |
| `reid_benchmark.sh` | Benchmark ReID HEF models (FPS & latency via hailortcli) |
| `ground_truth.json` | Manual mapping: predicted ID -> true person label (user-created) |
| `match_log.jsonl` | Auto-generated log of every match decision (pipeline output) |

## Module Dependencies

```
┌─────────────────────────────┐
│   reid_embedding_extractor  │  Hailo ReID inference
│   (RepVGG / OSNet)          │  (no internal deps)
└──────────┬──────────────────┘
           │ imports                    imports
           ├───────────────────────────────┐
           │                               │
           v                               v
┌─────────────────────┐         ┌─────────────────────┐
│ gallery_strategies   │         │ gallery_strategies   │
│ (create_strategy,    │         │ (FirstOnly,          │
│  STRATEGIES)         │         │  MultiEmbedding)     │
└──────────┬───────────┘         └──────────┬───────────┘
           │ imports                         │ imports
           v                                v
┌─────────────────────┐         ┌─────────────────────┐
│ reid_analysis_app    │         │ mot17_eval           │
│                      │         │                      │
│ Runs Hailo pipeline, │         │ Uses MOT17 GT boxes  │
│ produces             │         │ to evaluate ReID     │
│ match_log.jsonl      │         │ embedding quality    │
└──────────┬───────────┘         └─────────────────────┘
           │ launches as subprocess
           │
           v                        imports
┌─────────────────────┐  ◄──────────────────────────────┐
│ reid_eval            │  load_match_log, load_ground_   │
│                      │  truth, evaluate, append_csv    │
│ Reads match_log.jsonl│                                 │
│ + ground_truth.json  │         ┌─────────────────────┐ │
│ to compute metrics   │         │ reid_sweep           ├─┘
└──────────────────────┘         │                      │
                                 │ Grid search: runs    │
                                 │ reid_analysis_app    │
                                 │ with different params│
                                 │ then evaluates each  │
                                 └──────────────────────┘
```

## Quick Start

### 1. Run the pipeline

```bash
source setup_env.sh
python reid_analysis/reid_analysis_app.py \
    --input 12354541-hd_1280_720_25fps.mp4 \
    --tiles-x 2 --tiles-y 3 \
    --reid-model repvgg --reid-match-threshold 0.7 \
    --gallery-strategy first_only \
    --video-sink fakesink --disable-sync
```

**Outputs:**
- `orig_person_images/` — First-seen reference crop per predicted person
- `person_images/{person_id}/` — All matched crops, organized by ID
- `match_log.jsonl` — Every match decision (frame, similarity, predicted ID)

### 2. Create ground truth

Review the reference crops in `orig_person_images/` and edit `ground_truth.json`:

```json
{
  "id_mapping": {
    "person_0": "A",
    "person_1": "B",
    "person_2": "A",
    "person_3": "false_positive"
  }
}
```

- Use letters (A, B, C, ...) for true person identities
- Use `"false_positive"` for bad detections (partial crops, multi-person boxes, background)

### 3. Evaluate

```bash
# Single threshold evaluation
python reid_analysis/reid_eval.py \
    --match-log reid_analysis/match_log.jsonl \
    --ground-truth reid_analysis/ground_truth.json

# Sweep thresholds offline (no re-run needed)
python reid_analysis/reid_eval.py \
    --match-log reid_analysis/match_log.jsonl \
    --ground-truth reid_analysis/ground_truth.json \
    --sweep
```

### 4. Parameter sweep (optional)

```bash
python reid_analysis/reid_sweep.py \
    --input 12354541-hd_1280_720_25fps.mp4 \
    --ground-truth reid_analysis/ground_truth.json \
    --tiles-x 2 --tiles-y 3
```

Default sweep: 2 models x 5 thresholds x 3 strategies = 30 runs.

## Gallery Strategies

| Strategy | `--gallery-strategy` | Description |
|----------|---------------------|-------------|
| First Only | `first_only` | Keep first embedding forever. Simple baseline. |
| Running Average | `running_average` | Gallery embedding = running average of all matches. Adapts to appearance changes. |
| Update Every N | `update_every_n` | Replace embedding every N matches. Use with `--gallery-update-interval`. |
| Multi-Embedding | `multi_embedding` | Store up to K embeddings per person, match = max similarity. Use with `--gallery-max-size`. |

## Metrics

| Metric | Meaning | Ideal |
|--------|---------|-------|
| **Precision** | Correct assignments / total assignments | 1.0 |
| **Fragmentation** | Avg predicted IDs per true person | 1.0 |
| **ID Switches** | Frame-to-frame identity flips for same true person | 0 |
| **New IDs** | Total predicted person IDs created | = true person count |

## ReID Models

| Model | Embedding Dim | Speed (Hailo-8) | HEF |
|-------|--------------|-----------------|-----|
| RepVGG A0 | 512 | ~5200 FPS | `repvgg_a0_person_reid_512.hef` |
| OSNet x1_0 | 512 | ~180 FPS | `osnet_x1_0.hef` |

Both produce L2-normalized embeddings (cosine similarity = dot product). Input size is read from the HEF file at runtime (currently 256x128 for both models).

### Downloading HEF files

The pre-compiled HEF files are available from the Hailo Model Zoo:
https://github.com/hailo-ai/hailo_model_zoo/blob/master/docs/public_models/HAILO8/HAILO8_person_re_id.rst

Download the HEFs and place them in:

```
/usr/local/hailo/resources/models/hailo8/repvgg_a0_person_reid_512.hef
/usr/local/hailo/resources/models/hailo8/osnet_x1_0.hef
```

This is the default search path. To use a different location, set the `HAILO_MODELS_DIR` environment variable:

```bash
export HAILO_MODELS_DIR=/path/to/your/models
```

## Key CLI Arguments

### reid_analysis_app.py

| Argument | Default | Description |
|----------|---------|-------------|
| `--input` | — | Input video file or stream |
| `--tiles-x` / `--tiles-y` | 2 / 3 | Tiling grid for detection |
| `--reid-model` | `repvgg` | ReID model: `repvgg` or `osnet` |
| `--reid-match-threshold` | `0.7` | Cosine similarity threshold for ReID matching |
| `--gallery-strategy` | `first_only` | Gallery update strategy |
| `--gallery-update-interval` | `10` | Frames between updates (for `update_every_n`) |
| `--gallery-max-size` | `10` | Max embeddings per person (for `multi_embedding`) |
| `--output-dir` | `.` (script dir) | Base output directory |
| `--video-sink` | `autovideosink` | GStreamer video sink (`fakesink` for headless) |
| `--disable-sync` | off | Run as fast as possible (no real-time sync) |

### reid_eval.py

| Argument | Default | Description |
|----------|---------|-------------|
| `--match-log` | — | Path to match_log.jsonl |
| `--ground-truth` | — | Path to ground_truth.json |
| `--sweep` | off | Sweep thresholds 0.3-0.95 offline |
| `--run-label` | — | Label for CSV output |
| `--output-csv` | — | Append results to CSV |

---

## MOT17 Ground-Truth Evaluation (`mot17_eval.py`)

Standalone evaluation that uses MOT17 ground-truth bounding boxes to measure ReID embedding quality **without detection noise** (no YOLO, no GStreamer). Answers the question: "How well can our embeddings distinguish between N people?"

### Concept

```
MOT17 GT boxes (frame, person_id, bbox)
    |
    v
Precompute embeddings once (read frame -> crop GT box -> Hailo ReID)
    |
    v
Test 1: Gallery from frame 1 only (FirstOnly strategy)
Test 2: Gallery enriched every M frames with GT association (MultiEmbedding)
    |
    v
Precision / Recall / F1 per threshold  +  plot
```

**Key design:** Only the N selected gallery persons are evaluated. The task is purely N-way identification — "which of these N people is this crop?" No distractors. As N grows, the gallery must distinguish between more similar-looking people, increasing confusion.

### Metrics

| Metric | Definition |
|--------|-----------|
| **TP** | Gallery person's crop matched to the **correct** gallery entry |
| **FP** | Gallery person's crop matched to a **wrong** gallery entry |
| **FN** | Gallery person visible but similarity below threshold (no match) |
| **Precision** | TP / (TP + FP) — "of identifications made, how many correct?" |
| **Recall** | TP / (TP + FN) — "of gallery person appearances, how many identified?" |

### Quick Start

```bash
source setup_env.sh

# Step 1: Save candidate crops from frame 1 (interactive preview)
python reid_analysis/mot17_eval.py --dataset-dir /tmp/MOT17-04-SDP/
# -> Saves gallery_candidates/*.jpg + candidates_frame1.jpg (annotated frame with boxes & IDs)
# -> Review candidates_frame1.jpg to pick person IDs

# Step 2: Run evaluation with chosen persons
python reid_analysis/mot17_eval.py --dataset-dir /tmp/MOT17-04-SDP/ --person-ids 1,3,4,5

# Scale up to see confusion increase
python reid_analysis/mot17_eval.py --dataset-dir /tmp/MOT17-04-SDP/ --person-ids 1,3,4,5,86,92,88,60

# Use OSNet instead of RepVGG
python reid_analysis/mot17_eval.py --dataset-dir /tmp/MOT17-04-SDP/ --person-ids 1,3 --reid-model osnet

# Skip frames for faster iteration
python reid_analysis/mot17_eval.py --dataset-dir /tmp/MOT17-04-SDP/ --person-ids 1,3 --skip-frames 10
```

### Output

- **Threshold sweep table** — Precision, Recall, F1, TP, FP, FN at each threshold (0.30–0.95)
- **Precision-Recall plot** — `mot17_results/pr_plot_N{n}_{model}.png`
- **Summary** — Best F1 for each test + delta between Test 1 and Test 2

### CLI Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--dataset-dir` | (required) | Path to MOT17 sequence (e.g., `/tmp/MOT17-04-SDP/`) |
| `--reid-model` | `repvgg` | ReID model: `repvgg` or `osnet` |
| `--person-ids` | (none) | Comma-separated GT person IDs. If omitted, saves preview and exits. |
| `--vis-threshold` | `0.3` | Minimum GT visibility to include an annotation |
| `--update-interval` | `30` | Frames between gallery updates in Test 2 |
| `--max-k` | `20` | Max embeddings per person in MultiEmbedding |
| `--skip-frames` | `1` | Process every Nth frame (1 = all) |
| `--output-dir` | `reid_analysis/mot17_results/` | Output directory for plots and crops |

### Test 1 vs Test 2

| Test | Gallery Strategy | Gallery Updates | Measures |
|------|-----------------|-----------------|----------|
| **Test 1** | `FirstOnlyStrategy` | None — frame 1 embeddings only | Baseline: how well a single embedding represents a person over time |
| **Test 2** | `MultiEmbeddingStrategy` | Every M frames, add GT crop embedding (oracle) | Upper bound: how much gallery enrichment helps |

Comparing the two shows how much re-ID accuracy improves when the gallery is updated, and at what N the single-frame approach starts to break down.

---

## HEF Benchmark (`reid_benchmark.sh`)

Measures FPS (throughput) and latency for ReID HEF models using `hailortcli`. Auto-detects OSNet and RepVGG HEF files in the models directory. Outputs Confluence Wiki Markup tables.

```bash
cd reid_analysis
bash reid_benchmark.sh
```

**Metrics measured per model per batch size (1, 2, 4, 8, 16):**
- FPS (hw_only) — hardware-only throughput
- FPS (streaming) — full pipeline throughput
- HW Latency — hardware processing time per batch
- Overall Latency — end-to-end latency

Results are saved to `reid_benchmark_results_<timestamp>.txt`.

---

## Cross-Matching Utility

`reid_embedding_extractor.py` can also be run standalone to compute a cosine similarity matrix between person images (useful for debugging gallery thresholds):

```bash
source setup_env.sh
python -m reid_analysis.reid_embedding_extractor --images-dir path/to/person/crops/
```

Prints an N x N similarity matrix for both RepVGG and OSNet models.
