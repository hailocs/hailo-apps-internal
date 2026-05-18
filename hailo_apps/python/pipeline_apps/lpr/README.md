# Hailo LPR App

License Plate Recognition pipeline. Two orthogonal choices control behaviour:

| Flag         | Values                                  | Default    |
|--------------|-----------------------------------------|------------|
| `--backbone` | `yolov8n` / `yolov8n_tiled` / `cascade` | `yolov8n`  |
| `--ocr`      | `lprnet` / `paddle`                     | `lprnet`   |

Backbone picks the detector(s) that find license plates in the frame; OCR
picks the recognition network that reads characters off each plate crop.

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

| | Bundled `lprnet.hef`               | Retrained `lprnet_intl.hef`            |
|---|---|---|
| Filename at install root | `lprnet.hef`                       | **`lprnet_intl.hef`**                  |
| Classes                  | 11 (digits + CTC blank) or 37 international | **37** (digits + A–Z + CTC blank)     |
| Charset                  | `0-9 + blank` (Chinese-plate convention) | `0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-` |
| Chinese province chars   | yes (in some MZ builds)            | no                                     |
| `I` / `O` letters        | omitted (Chinese-plate convention) | **present**                            |
| Confidence threshold     | 0.78                               | **0.50** (37-class softmax spread thinner) |

#### Training details

| | |
|---|---|
| Base architecture        | Hailo's LPRNet (`hailo-ai/LPRNet_Pytorch` fork) |
| Training docker          | `license_plate_recognition:v0` from `hailo_models/license_plate_recognition/Dockerfile`; built by `setup_lprnet_retrain_env.sh` in the LPR regression workspace |
| Optional torch upgrade   | `license_plate_recognition:torch2` — torch 2.4.1+cu121 + onnx 1.17 + tensorboard 2.14, layered on top of `v0`, used to export ONNX at opset ≥ 20 |
| Model Zoo version        | **2.17.1** (paired with Dataflow Compiler 3.32.0) |
| Compile docker           | `lprnet_dfc:v4` — Ubuntu 22.04 / Py 3.10 / DFC 3.32.0 / MZ 2.17.1 / a one-line patch to `hailo_sdk_common/paths_manager/paths.py` so `dist-packages` installs are detected as "release" |
| Compile optimization     | level 0 (insufficient calibration data + no GPU on the DFC docker's nvidia path); revisit when full retrain runs |
| Calibration set          | 256 plate images at 75×300, sampled from val |
| Input dimensions         | `1×3×75×300` (NCHW), BGR, normalised `(x − 127.5) / 128` |
| Output dimensions        | `1×37×19` (CTC: 37 classes × 19 time-steps) |
| Dataset                  | 48,638 train + 2,355 val ≈ 51 k plates; synthetic + CCPD + OpenALPR endtoend & seg_and_ocr, plus 996 cropped Israeli plates (digit-only, 7–8 char) added before the full retrain (full provenance in `tests/lpr_regression/README.md`) |
| Status                   | **Full 30-epoch retrain complete (2026-05-17)**; HEFs for H8 / H8L compiled and installed |

#### Accuracy

| Phase                                    | val exact-match | Notes |
|---|---:|---|
| 3-epoch trial — torch 1.7 (peak / final) | 73.2 % / 79.95 % | proof-of-concept |
| 3-epoch trial — torch 2.4 (peak / final) | 77.6 % / 68.9 %  | same loop, newer torch; numbers are run-to-run noise at 3 epochs |
| **Full retrain — torch 2.4 (peak / final)** | **80.2 % / 79.4 %** | 30 epochs, batch 64, LR 1e-3, RMSprop; best checkpoint at iter 12,000 (Levenshtein-similarity criterion) |
| **End-to-end with `yolov8n_tiled`**      | **83.1 %**       | 358 / 444 exact matches across BR + EU + US ground-truth clips; F1 = 87.2, ≤d2 = 90 %, ~150 FPS |

### `paddle` — paddle_ocr_v5_mobile_recognition

The multilingual route, unchanged. Use when you need broader script
support (non-Latin) or richer formatting tolerance (hyphens, dots,
spaces). A 18,385-class CTC head, so per-character confidence is
naturally diffuse — the confidence gate is 0.30 (vs 0.50 on the new
lprnet, 0.78 on the bundled lprnet).

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
├── ocr.hef                      # paddle OCR v5 mobile recognition
├── ocr_det.hef                  # paddle text detector
└── ppocrv5_char_dict.npz        # paddle v5 character dictionary
```

`lprnet_intl` and `hailo_yolov8n_384_640` are listed under `lpr → default`
in [`resources_config.yaml`](../../../config/resources_config.yaml); the
paddle artifacts live under `paddle_ocr → default` and the character
dictionary rides along as a sidecar of the `ocr` entry.

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

```bash
# Default — yolov8n backbone + retrained LPRNet
hailo-lpr --input clip.mp4

# Best accuracy on HD / 4K
hailo-lpr --backbone yolov8n_tiled --ocr lprnet --input clip.mp4

# Multilingual OCR
hailo-lpr --backbone yolov8n_tiled --ocr paddle --input clip.mp4

# Legacy cascade
hailo-lpr --backbone cascade --ocr lprnet --input clip.mp4
```

## Regression tests

End-to-end and OCR-only test suites live under
[`tests/lpr_regression/`](../../../../tests/lpr_regression/). They are
ignored by `.gitignore` because the test fixtures are derived from
licence-restricted source datasets (CCPD, OpenALPR). The runners stay
checked in; the image fixtures and ground-truth crops are rebuilt
locally with `prepare_fixtures.py`.
