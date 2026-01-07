# LPR OCR Debug Review (No Code Changes Applied)

This note summarizes likely causes for low OCR confidence, fragmented text, and the segfault risk based on current code. It also lists the specific changes I would make (but did not make) and a focused debug checklist.

## What the code is doing today

- OCR results are normalized to **digits only** and must be **length 7 or 8** to be accepted.
  - `hailo_apps/postprocess/cpp/lpr_ocrsink.cpp` (`normalize_ocr_label_default` / `normalize_ocr_label_for_country`).
- OCR postprocess (`paddleocr_recognize`) expects **UINT8** logits and divides by **255**, then computes **mean confidence** of kept tokens.
  - `hailo_apps/postprocess/cpp/ocr_postprocess.cpp`.
- OCR crops are produced by the LPR cropper function **license_plate_with_quality**.
  - `hailo_apps/python/core/common/defines.py` and `license_plate_recognition_pipeline.py`.
- OCR batch size is **8** and `scheduler-timeout-ms` is **200** in the `vlpoc_ocrsink` pipeline.
  - `hailo_apps/python/pipeline_apps/license_plate_recognition/license_plate_recognition_pipeline.py`.
- `lpr_ocrsink` removes LP detections if the OCR classification count is not exactly **1**.
  - `hailo_apps/postprocess/cpp/lpr_ocrsink.cpp`.

## Most likely causes of your current symptoms

1. **Digits-only normalization rejects valid plates**
   - Your log shows short strings like "37", "E", "T", etc. These get normalized to digits only and then rejected unless the result is 7–8 digits. This silently drops many plausible results, especially alphanumeric plates.

2. **OCR confidence looks artificially low**
   - `paddleocr_recognize` assumes UINT8 output and divides by 255. If the model output is already float or already softmaxed, this will shrink confidences toward ~0.01–0.03.
   - The postprocess uses `rec_output_name`, `blank_index`, and `time_major` from the OCR JSON. If these are mismatched to the HEF, the decoded text and confidence will be poor.

3. **Cropper quality filter may discard most plates**
   - `license_plate_with_quality` could be filtering aggressively, leaving only weak/partial crops for OCR. There’s no in-repo config to confirm its thresholds.

4. **Batch size and timeout are mismatched to crop availability**
   - `batch_size=8` for OCR, but plate crops often arrive in small numbers. This can increase latency and trigger timeouts with partial batches.

5. **Segfault risk due to unsynchronized globals**
   - `seen_ocr_track_ids` and `singleton_map_key` are global and not protected; the filter can be executed concurrently for multiple streams or threads. This is a realistic crash vector under load.

## Changes I would make (not applied)

### 1) Relax or replace digits-only normalization
- **File:** `hailo_apps/postprocess/cpp/lpr_ocrsink.cpp`
- **Change:** Replace `normalize_ocr_label_default()` with a configurable per-country regex or a simple alnum filter that allows letters and variable lengths.
- **Why:** Current digits-only logic drops valid alphanumeric plates and explains fragmented results.

### 2) Align OCR postprocess with tensor format
- **File:** `hailo_apps/postprocess/cpp/ocr_postprocess.cpp`
- **Change options:**
  - If output is float: read `float` tensor and remove `/255.0f` scaling.
  - If output is UINT8: set `output-format-type=HAILO_FORMAT_TYPE_UINT8` explicitly for OCR in the pipeline to guarantee consistency.
- **Why:** Confidence values around 0.01–0.03 suggest the decoder may be scaling down values incorrectly.

### 3) Make OCR batch size and timeout configurable per pipeline
- **File:** `hailo_apps/python/pipeline_apps/license_plate_recognition/license_plate_recognition_pipeline.py`
- **Change:** Allow CLI overrides or environment variables for `batch_size` and `scheduler_timeout_ms` in OCR. Default to a smaller batch (1–2) for `vlpoc_ocrsink`.
- **Why:** OCR crops are sparse; batch 8 can create delays and degrade throughput.

### 4) Stop dropping LP detections on "classification count != 1"
- **File:** `hailo_apps/postprocess/cpp/lpr_ocrsink.cpp`
- **Change:** Accept the best OCR classification by confidence rather than requiring exactly one.
- **Why:** OCR postprocess or trackers may attach multiple classifications; hard rejection drops valid results.

### 5) Add optional retry or best-of-N per track
- **File:** `hailo_apps/postprocess/cpp/lpr_ocrsink.cpp`
- **Change:** Keep a per-track best OCR result across several frames before finalizing.
- **Why:** Single-frame OCR can be weak; you already have tracking to support temporal smoothing.

### 6) Add thread safety around shared state
- **File:** `hailo_apps/postprocess/cpp/lpr_ocrsink.cpp`
- **Change:** Protect `seen_ocr_track_ids` and `singleton_map_key` with a mutex or use atomics/lock-free structures.
- **Why:** Concurrent access is a credible cause of the segfault.

### 7) Expose LPR cropper choice at runtime
- **File:** `hailo_apps/python/core/common/defines.py` and `license_plate_recognition_pipeline.py`
- **Change:** Allow switching between `license_plate_with_quality` and `license_plate_no_quality` via CLI/env.
- **Why:** Quality filtering is a suspected bottleneck; enabling a toggle lets you confirm quickly.

## Debug checklist (no code changes required)

1. **Enable existing ocrsink debug logs**
   - `HAILO_LPR_DEBUG=1 HAILO_LPR_DEBUG_EVERY_N=1` to log every frame.

2. **Dump LP crops before OCR**
   - Add a `multifilesink` after `lp_cropper_cropper` to confirm crop content and size.

3. **Log OCR tensor metadata**
   - Add a short log in `paddleocr_recognize` to print tensor type/shape and confirm UINT8 vs float.

4. **Verify OCR JSON is correct for the HEF**
   - Check `rec_output_name`, `blank_index`, `time_major`, and `charset_path` values.

5. **Compare pipelines**
   - Try `license_plate_no_quality` and a smaller OCR batch size (1–2) to validate crop quality vs latency.

## Files referenced

- `hailo_apps/postprocess/cpp/lpr_ocrsink.cpp`
- `hailo_apps/postprocess/cpp/ocr_postprocess.cpp`
- `hailo_apps/python/pipeline_apps/license_plate_recognition/license_plate_recognition_pipeline.py`
- `hailo_apps/python/core/common/defines.py`

