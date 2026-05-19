# Hailo LPR App

License Plate Recognition pipeline. Two orthogonal choices control behaviour:

| Flag         | Values                                  | Default    |
|--------------|-----------------------------------------|------------|
| `--backbone` | `yolov8n` / `yolov8n_tiled` / `cascade` | `yolov8n`  |
| `--ocr`      | `lprnet` / `paddle`                     | `lprnet`   |

Backbone picks the detector(s) that find license plates in the frame; OCR
picks the recognition network that reads characters off each plate crop.

## What's new in this release

This is a substantial rework of the LPR pipeline. The previous version
chained a vehicle detector, a license-plate detector, and a digits-only
LPRNet — fine for plate formats that are purely numeric (e.g. IL), but
unable to read plate formats with letters such as EU and US. The new
pipeline replaces both detector stages with a single 4-class yolov8n
and swaps the digits-only LPRNet for a locally retrained 37-class
LPRNet that reads Latin alphanumeric plates. Numeric formats still
work; alphanumeric formats now work too. The result is a pipeline
that reads the plates it sees, end-to-end, in real time on the
accelerator, across the regional formats we tested.

### Operational thresholds

| Component       | Threshold | Effect                                                                |
|-----------------|----------:|-----------------------------------------------------------------------|
| Detector score  | **0.25**  | Plates with detection score ≥ 0.25 are forwarded to OCR               |
| OCR (`lprnet`)  | **0.50**  | OCR reads with per-character softmax mean ≥ 0.50 are accepted         |
| OCR (`paddle`)  | 0.30      | Paddle softmax is spread over 18 k classes — lower gate by design     |

### Accuracy

Default configuration (`--backbone yolov8n_tiled --ocr lprnet`),
performance-compiled HEFs. Detector and OCR are reported separately
since they are exercised independently.

#### Detector — `yolov8n_384_640` (license_plate class, score ≥ 0.25, IoU ≥ 0.5)

| Device | GT plates | **Recall** | **Miss** | Precision | mean IoU | FPS (img/s) |
|--------|----------:|-----------:|---------:|----------:|---------:|------------:|
| **Hailo-8**  | 5,014 | **98.4 %** | **1.6 %** | 99.2 %    | 0.854    | **120**     |
| **Hailo-10H**| 5,014 | **98.9 %** | **1.1 %** | 99.3 %    | 0.855    | 80          |

#### OCR — 37-class `lprnet_intl.hef` on real labeled plate crops

| Region group                | N    | Hailo-8 EXACT | Hailo-10H EXACT | ≤d2 (H8) | char-acc (H8) |
|-----------------------------|-----:|--------------:|----------------:|---------:|--------------:|
| **US** *(real)*             |  148 | **97.3 %**    | 96.6 %          | 100.0 %  | 99.4 %        |
| **EU** *(real)*             |   22 | **95.5 %**    | 95.5 %          | 100.0 %  | 99.4 %        |
| Rest of world *(IL synth.)* |  996 | 78.2 %        | 78.2 %          | 96.3 %   | 95.0 %        |

Exact-match is character-for-character agreement with ground truth.
`≤d2` (within 2 edits) is the OCR-ceiling indicator — most misses are
1–2 character substitutions on visually-similar pairs (`I`↔`1`, `O`↔`0`,
`S`↔`5`, `B`↔`8`). For reference, the legacy cascade backbone scored
single-digit exact-match recall on a smaller earlier corpus; this
version is an order of magnitude better.

### Performance on the accelerator

End-to-end wall-clock FPS of the full GStreamer pipeline (OCR = `lprnet`),
performance-compiled HEFs:

| Backbone (OCR = lprnet)      | Hailo-8 | Hailo-8L\* | Hailo-10H | Notes                                              |
|------------------------------|--------:|-----------:|----------:|----------------------------------------------------|
| `yolov8n`                    | ~254    | ~117       | ~243      | Single inference per frame, real-time on FHD       |
| `yolov8n_tiled` *(default)*  | ~171    | ~77        | ~80       | 5-tile inference; best accuracy on FHD / 4K        |
| `cascade` *(legacy)*         | ~34     | TBD        | not supported† | Two detectors + cropper; kept for H8/H8L compat |

\* H8L FPS measured by running the H8L performance HEFs on a physical H8
device (H8 is a strict superset of H8L; HEFs compiled for H8L run on H8
unchanged). Faithful proxy for actual H8L throughput, within ±5 % of
the expected ~0.5× of H8.

† Cascade on H10H: HEFs exist in the Model Zoo (v5.2.0+) but the
cascade-specific postprocess shared objects don't currently produce
detections from the H10H build of `yolov5m_vehicles`. Use `yolov8n` or
`yolov8n_tiled` on H10H; both are first-class supported and faster than
cascade anyway.

### Honest limitations

This release is a meaningful step forward, **not a finished product**.
Things to expect:

- A small percentage of plates is still missed end-to-end. Detector
  miss rate is ~1 % on the real plate-detection corpus; OCR miss rate
  on real US/EU plates is ~3–5 %. Most remaining failures come from
  motion blur, severe perspective, or partially-occluded plates.
- **Israeli plates are a known weak spot.** Set expectations
  accordingly — the shipped LPRNet performs noticeably worse on real IL
  footage than on US / EU. Two reasons:
  1. **Format.** IL plates are 7–8 digits with no letters, but the
     shipped LPRNet is trained as a 37-class Latin-alphanumeric head;
     the model has no IL-specific format prior, so a digit-only plate
     can decode as e.g. `1L47471` or `B8870B` instead of `1147471`.
  2. **Data.** The IL training corpus we had access to is
     **synthetic** (not real-camera) — measured exact-match on synthetic
     IL is ~78 %, but on the real IL clips shipped under
     `clip1.mp4` / `clip2.mp4` accuracy is materially lower. We do not
     have a labeled real-IL eval corpus to quantify it precisely yet.
  If you need high accuracy on Israeli plates, the right move is a
  region-specific LPRNet fine-tune (see *Future improvements* below) on
  a few thousand labeled real IL crops — the loop is the same as for
  the shipped model, the dataset just needs to be IL-only.
- The 37-class LPRNet is trained on Latin alphanumerics only. Plates
  with non-Latin script (Arabic, Cyrillic, CJK) need `--ocr paddle`,
  which is multilingual but lower-accuracy on Latin plates.
- Character substitutions are concentrated in the usual visually-similar
  pairs (`O`↔`0`, `I`↔`1`, `S`↔`5`, `B`↔`8`) — the `≤d2` column in the
  accuracy table separates these "almost-right" reads from outright
  misses.

### Future improvements

**Fine-tune LPRNet for your regional plates.** The shipped 37-class
LPRNet is trained on a mixed Latin corpus, so a single-region deployment
(e.g. one country's plates, or one US state's plate format) inherits a
generality cost it doesn't need to pay. Retraining the OCR head on a
narrower corpus closes most of the remaining gap between near-match
and exact-match in that region.

This is intentionally easy to do: LPRNet is small, the architecture
ships unchanged, and a few thousand labeled plate crops from the
target region is enough to move the needle. The same training loop
that produced `lprnet_intl.hef` accepts a region-specific dataset
with no code changes — fine-tune from the checkpoint, recompile, and
drop the new HEF in at `/usr/local/hailo/resources/models/<arch>/lprnet_intl.hef`.
No pipeline changes needed.

## Backbones

| Backbone         | Detection chain                                                            | Typical use |
|------------------|----------------------------------------------------------------------------|-------------|
| `yolov8n` (default) | one `hailo_yolov8n_384_640` (4 classes: person/vehicle/face/license_plate) | most workloads |
| `yolov8n_tiled`  | same network, fed 5 tiles per frame (2×2 quadrants + 1 full-frame), aggregated | FHD / 4K input where small plates need higher per-plate pixel density |
| `cascade`        | yolov5m_vehicles → tracker → cropper(tiny_yolov4_license_plates) (legacy)  | lowest-memory; kept for compatibility, may be removed |

We default to `yolov8n` because it's a clear accuracy + speed win over the
cascade on every workload we've measured, and stays light-weight enough
to run on H8L. `yolov8n_tiled` trades ~30 % FPS for a meaningful accuracy
lift on HD-and-up source video; opt-in when needed.

## OCR engines

### `lprnet` — retrained 37-class Latin alphanumeric LPRNet  *(default)*

A new locally-retrained LPRNet HEF that **replaces the bundled 11-class
Chinese-plate LPRNet** for our use cases. The new HEF lives at a
*separate* filename so the bundled `lprnet.hef` from the Hailo Model Zoo
stays untouched on disk if `install.sh` placed it there.

| | Bundled `lprnet.hef`           | Retrained `lprnet_intl.hef`            |
|---|---|---|
| Filename at install root | `lprnet.hef`                   | **`lprnet_intl.hef`**                  |
| Classes                  | 11 (digits + CTC blank)        | **37** (digits + A–Z + CTC blank)      |
| Charset                  | `0-9 + blank`                  | `0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-`|
| Training corpus          | Chinese plates (CCPD-style)    | Mixed Latin (synthetic + OpenALPR + curated US/EU + IL augmentation) |

Headline accuracy numbers for the retrained HEF are in the
[Accuracy table above](#ocr--37-class-lprnet_intlhef-on-real-labeled-plate-crops).

### `paddle` — paddle_ocr_v5_mobile_recognition

The multilingual route, unchanged. Use when you need broader script
support (non-Latin) or richer formatting tolerance (hyphens, dots,
spaces). 18,385-class CTC head, so per-character confidence is
naturally diffuse — the confidence gate is 0.30 (vs 0.50 on lprnet).

Future direction: we may apply the same fine-tune treatment to paddle
that we just did to LPRNet — retraining on the plate-specific corpus.
For now, paddle is left as-is.

## Installation

A plain `sudo ./install.sh` (default `download_group`) fetches everything
the OOB LPR path needs for the detected architecture:

```
/usr/local/hailo/resources/models/<arch>/
├── hailo_yolov8n_384_640.hef    # default backbone
├── lprnet_intl.hef              # default OCR (retrained 37-class)
├── paddle_ocr_v5.hef            # paddle OCR v5 mobile recognition (LPR-app build)
├── ppocrv5_char_dict.npz        # paddle v5 character dictionary (sidecar)
├── ocr.hef                      # legacy paddle OCR v3/v4 (standalone paddle_ocr)
└── ocr_det.hef                  # paddle text detector
```

`lprnet_intl`, `hailo_yolov8n_384_640`, and `paddle_ocr_v5` are listed
under `lpr → default` in
[`resources_config.yaml`](../../../config/resources_config.yaml) and
fetched from the `LPR/` subdirectory on S3 (`hefs/<arch>/LPR/…`). The
PaddleOCR-v5 character dictionary rides along as a sidecar of the
`ocr` entry.

> **Side note — paddle OCR HEF naming.** The LPR app's `--ocr paddle`
> path uses **`paddle_ocr_v5.hef`** (PP-OCRv5 mobile recognition,
> distinguished from the legacy `ocr.hef` by filename). The standalone
> `paddle_ocr` apps continue to use the legacy `ocr.hef` (v3/v4 build)
> served at the original flat S3 path, so anyone consuming that file
> from `paddle_ocr → default` keeps receiving v3/v4 — no behaviour
> change for those users. If `paddle_ocr_v5.hef` isn't on disk (e.g.
> upgrade from a pre-rework install), the LPR app falls back to
> `ocr.hef` with a warning; the postprocess layer auto-detects v3/v4
> vs v5 by class count.

The legacy cascade backbone (`yolov5m_vehicles`, `tiny_yolov4_license_plates`,
bundled `lprnet`) sits under `lpr → extra` and is only fetched with:

```bash
sudo ./install.sh --all
```

If you've compiled a fresh `lprnet_intl.hef` locally and want to test it
before it's published to S3, drop it in place manually:

```bash
sudo cp /path/to/your/lprnet_intl.hef \
        /usr/local/hailo/resources/models/<arch>/lprnet_intl.hef
```

## Run examples

`sudo ./install.sh` lays down two demo clips at
`/usr/local/hailo/resources/videos/`:

- `clip1.mp4` — short EU / US traffic sample; the **default** when
  `--input` is omitted.
- `clip2.mp4` — longer mixed-traffic sample.

```bash
# Default — yolov8n backbone + retrained LPRNet, runs against clip1.mp4
hailo-lpr

# Same defaults, but explicit input (or any clip of your own)
hailo-lpr --input /usr/local/hailo/resources/videos/clip2.mp4

# Best accuracy on HD / 4K
hailo-lpr --backbone yolov8n_tiled --ocr lprnet --input <your-clip.mp4>

# Multilingual OCR
hailo-lpr --backbone yolov8n_tiled --ocr paddle --input <your-clip.mp4>

# Legacy cascade
hailo-lpr --backbone cascade --ocr lprnet --input <your-clip.mp4>
```

## Regression tests

Regression tests were run locally against open-source ground-truth
datasets (CCPD, OpenALPR) to produce the accuracy numbers above.
