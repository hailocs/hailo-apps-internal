#!/usr/bin/env python3
"""
Standalone reproducer for a HailoRT 5.3.0 bug in YOLOV8 NMS post-process
on the yolo_world_v2s HEF (Hailo-10H build).

  Source location flagged by symbols in libhailort.so.5.3.0:
    libhailort/src/net_flow/ops/yolov8_post_process.cpp
    YOLOV8PostProcessOp::fill_nms_by_class_format_buffer

Symptom
-------
When the model's classification fan-in is a `normalization` (matmul-fused +
sigmoid) layer rather than a plain `conv`, the BY_CLASS output writer only
populates class index 0's slot in the output buffer. Classes 1..79 stay
bit-for-bit zero even though the underlying NMS detection list is correct
(see below: the same model with BY_SCORE returns multi-class detections
correctly).

Repro
-----
* Feed the chip 80 text embeddings where slot 0 and slot 1 are byte-identical
  (so the per-class scores at every spatial cell are identical for classes 0
  and 1). If multi-class were working, the output should contain ~the same
  number of detections at class 0 and class 1.
* In practice: HAILO_NMS_BY_CLASS reports class 0 ≥ 1 detection, class 1 = 0.
* The same configuration with HAILO_NMS_BY_SCORE returns matched detections
  with both `class_id=0` and `class_id=1` records — confirming libhailort's
  internal NMS detection list is correct (multi-class); the bug is isolated
  to the BY_CLASS output-formatting step that ships that list to the caller.

Run
---
    python3 repro_hrt_by_class_bug.py /path/to/yolo_world_v2s.hef

No external dependencies beyond hailo_platform + numpy.

Tested with: HailoRT 5.3.0, hailo_platform 5.3.0, hailo10h hw_arch, on a
yolo_world_v2s HEF compiled with DFC 5.4.0.dev0 (engine=cpu CPU NMS).
"""
from __future__ import annotations

import sys
from collections import Counter

import numpy as np
import hailo_platform
from hailo_platform import HEF, FormatOrder, FormatType, VDevice


N_CLASSES = 80                       # HEF nms config: 80 classes
EMB_DIM = 512                        # HEF text input channel dim
IMG_H, IMG_W = 640, 640
BY_CLASS_BUFFER_SIZE = 120080        # 80 * (1 + 300*5)  per HEF NMS config
BY_SCORE_HEADER = 2                  # uint16 n_dets at offset 0
BY_SCORE_REC_BYTES = 22              # 5x float32 + uint16 class_id


def make_inputs(seed: int = 0):
    """
    Image: zeros (content doesn't matter — the bug is positional in the cls
    output buffer, not data-dependent). A real frame works identically.

    Text: a single random unit vector, placed in slot 0 AND slot 1, with zeros
    in slots 2..79. Because slots 0 and 1 are byte-identical, the chip's
    matmul produces identical cls scores at every spatial cell for class 0
    and class 1. A working BY_CLASS writer would yield the same count for
    both classes.
    """
    rng = np.random.default_rng(seed)
    vec = rng.standard_normal(EMB_DIM, dtype=np.float32)
    vec /= np.linalg.norm(vec)

    text = np.zeros((1, N_CLASSES, EMB_DIM), dtype=np.float32)
    text[0, 0] = vec
    text[0, 1] = vec

    image = np.zeros((IMG_H, IMG_W, 3), dtype=np.uint8)
    return image, text


def find_io_names(hef: HEF):
    """Locate the two HEF inputs and the single fused NMS output by shape."""
    image_in = text_in = None
    for vi in hef.get_input_vstream_infos():
        shape = tuple(vi.shape)
        if shape[-1] == 3:
            image_in = vi.name
        elif shape[-1] == EMB_DIM:
            text_in = vi.name
    out_infos = hef.get_output_vstream_infos()
    assert len(out_infos) == 1, (
        f"expected a single fused NMS output, got {len(out_infos)}: "
        f"{[v.name for v in out_infos]}"
    )
    assert image_in and text_in, "couldn't identify image / text inputs"
    return image_in, text_in, out_infos[0].name


def run_with_format(hef_path: str, order: FormatOrder, type_: FormatType,
                    buffer_dtype, buffer_shape):
    hef = HEF(hef_path)
    image_in, text_in, nms_out = find_io_names(hef)
    image, text = make_inputs()

    vd = VDevice()
    im = vd.create_infer_model(hef_path)
    im.input(image_in).set_format_type(FormatType.UINT8)
    im.input(text_in).set_format_type(FormatType.FLOAT32)
    im.output(nms_out).set_format_order(order)
    im.output(nms_out).set_format_type(type_)

    with im.configure() as cm:
        b = cm.create_bindings()
        out_buf = np.empty(buffer_shape, dtype=buffer_dtype)
        b.input(image_in).set_buffer(image)
        b.input(text_in).set_buffer(text)
        b.output(nms_out).set_buffer(out_buf)
        cm.run([b], timeout=5000)
    vd.release()
    return out_buf


def decode_by_class(buf: np.ndarray):
    """Layout: per class [count_f32, det1, ..., det300], each det = 5 floats."""
    per_class = 1 + 300 * 5
    rows = buf.reshape(N_CLASSES, per_class)
    counts = rows[:, 0].astype(int)
    return counts


def decode_by_score(buf: np.ndarray):
    """Layout: uint16 n_dets header + N × 22-byte records [y1,x1,y2,x2,score,cls]."""
    n_dets = int(buf[0]) | (int(buf[1]) << 8)
    if n_dets == 0:
        return n_dets, Counter()
    rec_dt = np.dtype(
        [("y1", "<f4"), ("x1", "<f4"), ("y2", "<f4"), ("x2", "<f4"),
         ("score", "<f4"), ("cls", "<u2")],
    )
    end = BY_SCORE_HEADER + n_dets * BY_SCORE_REC_BYTES
    recs = np.frombuffer(buf[BY_SCORE_HEADER:end].tobytes(), dtype=rec_dt)
    cls_counts = Counter(int(r["cls"]) for r in recs)
    return n_dets, cls_counts


def main(hef_path: str) -> int:
    print(f"HailoRT version : {hailo_platform.__version__}")
    print(f"HEF             : {hef_path}")
    print(f"Probe           : slot 0 and slot 1 carry an IDENTICAL random "
          f"unit vector; slots 2..79 zero.")
    print(f"Expectation     : count(class 0) == count(class 1)\n")

    # 1) BY_CLASS (the buggy path)
    print("=== BY_CLASS / FLOAT32 readout ===")
    out_class = run_with_format(
        hef_path, FormatOrder.HAILO_NMS_BY_CLASS, FormatType.FLOAT32,
        np.float32, [BY_CLASS_BUFFER_SIZE],
    )
    counts = decode_by_class(out_class)
    nonzero_total = int(np.count_nonzero(out_class))
    print(f"  buffer non-zero floats: {nonzero_total} / {out_class.size}")
    print(f"  class 0 count: {counts[0]}")
    print(f"  class 1 count: {counts[1]}     <-- BUG: should equal class 0")
    print(f"  classes 2..79 total: {int(counts[2:].sum())}")
    bug_present = counts[0] > 0 and counts[1] == 0
    print(f"  bug reproduced: {bug_present}\n")

    # 2) BY_SCORE (the working path — same model, same chip, different writer)
    print("=== BY_SCORE / UINT8 readout (control) ===")
    # max records is bounded by 80*300 = 24000 (≤ 528002 bytes)
    out_score = run_with_format(
        hef_path, FormatOrder.HAILO_NMS_BY_SCORE, FormatType.UINT8,
        np.uint8, [528002],
    )
    n_dets, by_score_counts = decode_by_score(out_score)
    c0 = by_score_counts.get(0, 0)
    c1 = by_score_counts.get(1, 0)
    print(f"  n_dets header: {n_dets}")
    print(f"  detections per class id: {dict(by_score_counts)}")
    # Slot 0 and slot 1 carry identical embeddings, so the chip's per-class
    # scores at every cell are pairwise equal for classes 0 and 1. Top-K
    # selection inside NMS can introduce a small count delta; treat them as
    # equivalent if both classes fired and the counts are within 25%.
    bigger = max(c0, c1, 1)
    by_score_ok = c0 > 0 and c1 > 0 and abs(c0 - c1) / bigger <= 0.25
    print(f"  multi-class works via BY_SCORE: {by_score_ok}"
          f"  (class 0: {c0}, class 1: {c1})\n")

    print("=== summary ===")
    if bug_present and by_score_ok:
        print("  Confirmed: BY_CLASS writer drops class>0; BY_SCORE works.")
        print("  libhailort's internal NMS detection list is correct — only the")
        print("  BY_CLASS output-formatting step drops everything but class 0.")
        print("  Suspect: YOLOV8PostProcessOp::fill_nms_by_class_format_buffer")
        print("           in libhailort/src/net_flow/ops/yolov8_post_process.cpp")
        return 0
    print("  Did not reproduce the expected pattern; double-check HEF + HRT version.")
    return 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} /path/to/yolo_world_v2s.hef", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
