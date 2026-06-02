"""YOLO World v2s postprocessing: DFL decode + grid decode + per-class NMS.

The detector HEF emits 6 raw tensors at strides 8, 16, 32:
  - 3 classification maps (HxWx80) with sigmoid applied on-device
  - 3 regression maps — either already-decoded distances (HxWx4) or raw DFL
    distributions (HxWx64) that we softmax-decode here.

Hot-path notes:
- DFL decoding is the most expensive step (~10 ms for a dense 80x80 stride-8
  reg map). We avoid it by thresholding the classification maps first and
  only decoding regression cells whose best class score clears the threshold.
- Grid centers are constant per scale and cached at module level — no
  per-frame allocation.
"""
import numpy as np

from hailo_apps.python.core.common.hailo_logger import get_logger

logger = get_logger(__name__)

STRIDES = [8, 16, 32]
IMAGE_SIZE = 640
DFL_BINS = 16  # 4 sides × 16-bin distribution
DFL_CHANNELS = 4 * DFL_BINS
# NMS knobs (single source of truth — change here, not at call sites).
# IoU: standard same-class overlap suppression (greedy, highest-score-first).
# Containment: drop a same-class box when this fraction of it sits inside a kept
# higher-scoring box — kills "parts of an object" nested in the whole-object box.
DEFAULT_NMS_IOU_THRESHOLD = 0.5
CONTAINMENT_THRESHOLD = 0.6

_DFL_BIN_VALUES = np.arange(DFL_BINS, dtype=np.float32)

# Cache grid coords per (h, w, stride). Built lazily on first call, then reused.
_GRID_CACHE: dict = {}


def _grid(h: int, w: int, stride: int):
    """Return flat (center_x, center_y) arrays of shape (H*W,) for this scale."""
    key = (h, w, stride)
    cached = _GRID_CACHE.get(key)
    if cached is not None:
        return cached
    gy, gx = np.meshgrid(np.arange(h, dtype=np.float32),
                         np.arange(w, dtype=np.float32),
                         indexing="ij")
    cx = ((gx + 0.5) * stride).reshape(-1)
    cy = ((gy + 0.5) * stride).reshape(-1)
    _GRID_CACHE[key] = (cx, cy)
    return cx, cy


def _decode_dfl_subset(reg_flat: np.ndarray, indices: np.ndarray) -> np.ndarray:
    """DFL softmax + expectation for a subset of spatial cells.

    Args:
        reg_flat: (N, 64) regression tensor flattened across spatial dims.
        indices: 1-D int array of cells to decode.

    Returns:
        (len(indices), 4) decoded distances [l, t, r, b].
    """
    if indices.size == 0:
        return np.zeros((0, 4), dtype=np.float32)
    sel = reg_flat[indices].reshape(-1, 4, DFL_BINS)
    sel = sel - sel.max(axis=-1, keepdims=True)
    exp = np.exp(sel)
    probs = exp / exp.sum(axis=-1, keepdims=True)
    return (probs * _DFL_BIN_VALUES).sum(axis=-1)


CROSS_CLASS_NMS_IOU = 0.5   # suppress overlapping boxes regardless of class


def _cross_class_nms(detections, iou_threshold=CROSS_CLASS_NMS_IOU):
    """Drop overlapping boxes regardless of class label, keeping the highest-
    scoring one. Compensates for libhailort's per-class-only NMS that lets
    "smartphone" and "mouse" both surface on the same object when their
    cosine similarities are close — which then makes hailotracker flicker
    the label every frame as the leader changes.

    Assumes input is already sorted descending by score.
    """
    if len(detections) <= 1:
        return detections
    keep = []
    for cand in detections:
        bx1, by1, bx2, by2 = cand["bbox"]
        b_area = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
        if b_area <= 0:
            continue
        suppressed = False
        for chosen in keep:
            cx1, cy1, cx2, cy2 = chosen["bbox"]
            ix1 = max(bx1, cx1); iy1 = max(by1, cy1)
            ix2 = min(bx2, cx2); iy2 = min(by2, cy2)
            iw = max(0.0, ix2 - ix1); ih = max(0.0, iy2 - iy1)
            inter = iw * ih
            if inter <= 0:
                continue
            c_area = max(0.0, cx2 - cx1) * max(0.0, cy2 - cy1)
            union = b_area + c_area - inter
            if union > 0 and (inter / union) >= iou_threshold:
                suppressed = True
                break
        if not suppressed:
            keep.append(cand)
    return keep


def postprocess(output_tensors, score_threshold=0.3,
                iou_threshold=DEFAULT_NMS_IOU_THRESHOLD, num_classes=80):
    """Post-process YOLO World output tensors into detections.

    Two HEF flavors are supported; dispatch is by tensor count:
      * **Raw-tensor HEF** (Hailo-10H): 3 cls maps (HxWx80) + 3 reg maps
        (HxWx4 or HxWx64) — DFL decode, grid decode, and per-class NMS happen
        here. Cls outputs have sigmoid applied on-device.
      * **On-device-NMS HEF** (Hailo-8): a single ``yolov8_nms_postprocess``
        tensor shaped ``(1, num_classes, max_dets, 5)`` with already-decoded
        ``[x1,y1,x2,y2,score]`` per box — we just filter by score and return.

    Both paths run an extra cross-class NMS at the end so two different
    prompts firing on the same object (common for visually-similar nouns
    like "smartphone" + "mouse") don't both surface as competing tracks.

    Both paths return the same detection-dict format with bboxes normalized
    to [0, 1].
    """
    # On-device-NMS HEF (Hailo-8): single output, already decoded.
    if len(output_tensors) == 1:
        dets = _decode_on_device_nms(
            next(iter(output_tensors.values())),
            score_threshold=score_threshold,
            num_classes=num_classes,
        )
        return _cross_class_nms(dets)

    cls_tensors = []
    reg_tensors = []  # tuples of (tensor, is_dfl)
    for name in sorted(output_tensors.keys()):
        tensor = output_tensors[name]
        if tensor.ndim == 4:
            tensor = tensor[0]
        if tensor.ndim != 3:
            logger.warning("Unexpected tensor shape %s for %s", tensor.shape, name)
            continue
        c = tensor.shape[-1]
        if c == 80:
            cls_tensors.append(tensor)
        elif c == 4:
            reg_tensors.append((tensor, False))
        elif c == DFL_CHANNELS:
            reg_tensors.append((tensor, True))
        else:
            logger.warning("Unexpected channel count %d for %s", c, name)

    if len(cls_tensors) != 3 or len(reg_tensors) != 3:
        logger.error("Expected 3 cls + 3 reg tensors, got %d + %d",
                     len(cls_tensors), len(reg_tensors))
        return []

    # Sort by spatial size: largest first (stride 8 → 16 → 32).
    cls_tensors.sort(key=lambda t: t.shape[0] * t.shape[1], reverse=True)
    reg_tensors.sort(key=lambda t: t[0].shape[0] * t[0].shape[1], reverse=True)

    all_boxes = []
    all_scores = []
    all_class_ids = []
    inv_image = 1.0 / IMAGE_SIZE

    for cls_map, (reg_map, is_dfl), stride in zip(cls_tensors, reg_tensors, STRIDES):
        h, w, _ = cls_map.shape
        scores_flat = cls_map[:, :, :num_classes].reshape(-1, num_classes)  # (HW, C)

        # Some HEF builds apply the cls sigmoid on-chip (output in [0,1]); others
        # emit raw logits and expect host-side sigmoid. Detect once per call by
        # range: if any value is outside [0,1], assume logits and apply sigmoid.
        if scores_flat.size and (scores_flat.max() > 1.0 or scores_flat.min() < 0.0):
            # Numerically stable sigmoid (avoid exp overflow for large negatives).
            scores_flat = np.where(
                scores_flat >= 0,
                1.0 / (1.0 + np.exp(-scores_flat)),
                np.exp(scores_flat) / (1.0 + np.exp(scores_flat)),
            )

        # Multi-label: every (cell, class) whose score clears the threshold is a
        # candidate. YOLO World's head is per-class sigmoid, so a single location
        # can legitimately fire for several overlapping classes (e.g. a "can" held
        # by a "person"). Taking argmax here would drop all but the top class and
        # lose the overlapping object entirely.
        cand_cells, cand_classes = np.nonzero(scores_flat > score_threshold)
        if cand_cells.size == 0:
            continue
        cand_scores = scores_flat[cand_cells, cand_classes]

        # Decode the box once per *unique* firing cell (boxes are class-agnostic),
        # then fan out to the (cell, class) candidates — keeps DFL decode cheap.
        uniq_cells, inv = np.unique(cand_cells, return_inverse=True)
        reg_flat = reg_map.reshape(-1, reg_map.shape[-1])
        dists = _decode_dfl_subset(reg_flat, uniq_cells) if is_dfl else reg_flat[uniq_cells]

        cx, cy = _grid(h, w, stride)
        sel_cx = cx[uniq_cells]
        sel_cy = cy[uniq_cells]
        x1 = np.clip((sel_cx - dists[:, 0] * stride) * inv_image, 0.0, 1.0)
        y1 = np.clip((sel_cy - dists[:, 1] * stride) * inv_image, 0.0, 1.0)
        x2 = np.clip((sel_cx + dists[:, 2] * stride) * inv_image, 0.0, 1.0)
        y2 = np.clip((sel_cy + dists[:, 3] * stride) * inv_image, 0.0, 1.0)
        cell_boxes = np.stack([x1, y1, x2, y2], axis=-1)   # (U, 4)

        all_boxes.append(cell_boxes[inv])                  # (num_cand, 4)
        all_scores.append(cand_scores)
        all_class_ids.append(cand_classes)

    if not all_boxes:
        return []

    boxes = np.concatenate(all_boxes, axis=0)
    scores = np.concatenate(all_scores, axis=0)
    class_ids = np.concatenate(all_class_ids, axis=0)

    detections = []
    for cls_id in np.unique(class_ids):
        cls_mask = class_ids == cls_id
        cls_boxes = boxes[cls_mask]
        cls_scores = scores[cls_mask]
        keep = _nms(cls_boxes, cls_scores, iou_threshold, CONTAINMENT_THRESHOLD)
        for idx in keep:
            detections.append({
                "bbox": cls_boxes[idx].tolist(),
                "class_id": int(cls_id),
                "score": float(cls_scores[idx]),
            })

    detections.sort(key=lambda d: d["score"], reverse=True)
    return _cross_class_nms(detections)


def _decode_on_device_nms(arr, score_threshold, num_classes):
    """Decode an on-device-NMS output buffer into detections.

    Two on-device-NMS layouts are accepted (different runtimes use different ones):

    * **Packed byte stream (``uint8`` 1-D)** — HailoRT 4.x with output format
      ``HAILO_NMS_BY_SCORE``. Layout: ``uint16 n_dets`` header followed by
      ``n_dets`` 22-byte records, each ``[y1, x1, y2, x2, score]`` (5×f32) +
      ``class_id`` (uint16). We pick this format on 4.x because the
      ``HAILO_NMS_BY_CLASS`` readout silently drops non-zero classes for this
      HEF — BY_SCORE encodes class id per detection and is correct.
    * **Parsed tensor ``(B, C, max_dets, 5)``** — HailoRT 5.x InferModel.
      Score-threshold and pack into dicts.

    Bounding boxes are already normalized to [0, 1] and NMS has run on-device.
    ``num_classes`` lets the caller slice further if a smaller prompt set is
    loaded; classes beyond ``num_classes`` are dropped.
    """
    # HAILO_NMS_BY_SCORE packed byte stream (HailoRT 4.x InferModel + override).
    if arr.dtype == np.uint8 and arr.ndim == 1:
        return _decode_nms_by_score_bytes(arr, score_threshold, num_classes)

    # HAILO_NMS_BY_CLASS flat float32 buffer (HailoRT 5.x InferModel default).
    # Layout: per class [count_f32, det_1, ..., det_max], each det = [y1, x1, y2, x2, score].
    if arr.dtype == np.float32 and arr.ndim == 1:
        return _decode_nms_by_class_flat(arr, score_threshold, num_classes)

    if arr.ndim == 4:
        arr = arr[0]
    if arr.ndim != 3 or arr.shape[-1] != 5:
        logger.error("Unexpected on-device-NMS output shape: %s", arr.shape)
        return []

    n_classes = min(num_classes, arr.shape[0])
    detections = []
    for cls_id in range(n_classes):
        cls_rows = arr[cls_id]                              # (max_dets, 5)
        scores = cls_rows[:, 4]
        keep = scores >= score_threshold
        if not keep.any():
            continue
        kept = cls_rows[keep]
        for row in kept:
            detections.append({
                "bbox": [float(row[0]), float(row[1]), float(row[2]), float(row[3])],
                "class_id": cls_id,
                "score": float(row[4]),
            })
    detections.sort(key=lambda d: d["score"], reverse=True)
    return detections


def _decode_nms_by_class_flat(arr, score_threshold, num_classes):
    """Decode HailoRT 5.x default ``HAILO_NMS_BY_CLASS`` float32 flat buffer.

    Layout (per class, contiguous):
      ``[count_f32, det_1, det_2, …, det_max_per_class]`` where each ``det`` is
      five float32 values ``[y_min, x_min, y_max, x_max, score]`` (Hailo / YOLO
      axis order). Only the first ``count`` records per class are valid.

    Total size is ``HEF_num_classes × (1 + max_per_class × 5)``. We
    reverse-derive ``max_per_class`` from the buffer size and the HEF's
    nominal class count (80 for yolo_world_v2s).

    The axis swap ``[y1, x1, y2, x2] → [x1, y1, x2, y2]`` happens at pack time
    so the rest of the app (stabilizer / hailooverlay) sees the
    repo-wide ``HailoBBox`` convention.
    """
    HEF_NUM_CLASSES = 80
    total = arr.size
    per_class = total // HEF_NUM_CLASSES
    if HEF_NUM_CLASSES * per_class != total or (per_class - 1) % 5 != 0:
        logger.error(
            "Unexpected NMS_BY_CLASS flat float32 buffer size: %d (per-class %d)",
            total, per_class,
        )
        return []
    max_per_class = (per_class - 1) // 5
    rows = arr.reshape(HEF_NUM_CLASSES, per_class)

    active = min(num_classes, HEF_NUM_CLASSES)
    detections = []
    for cls_id in range(active):
        n = int(rows[cls_id, 0])
        if n <= 0:
            continue
        if n > max_per_class:
            n = max_per_class
        dets = rows[cls_id, 1:1 + n * 5].reshape(n, 5)
        scores = dets[:, 4]
        keep = scores >= score_threshold
        if not keep.any():
            continue
        for row in dets[keep]:
            # Chip writes [y1, x1, y2, x2, score]; swap to [x1, y1, x2, y2] at pack time.
            # Clamp to [0, 1]: HRT's BY_CLASS layout can emit FP32-ULP overshoots
            # (e.g. score=1.0000305) and bbox coords beyond the frame, both of
            # which HailoDetection rejects with std::invalid_argument.
            x1 = max(0.0, min(1.0, float(row[1])))
            y1 = max(0.0, min(1.0, float(row[0])))
            x2 = max(0.0, min(1.0, float(row[3])))
            y2 = max(0.0, min(1.0, float(row[2])))
            score = max(0.0, min(1.0, float(row[4])))
            detections.append({
                "bbox": [x1, y1, x2, y2],
                "class_id": cls_id,
                "score": score,
            })
    detections.sort(key=lambda d: d["score"], reverse=True)
    return detections


_NMS_BY_SCORE_RECORD = np.dtype([
    ("y1",       np.float32),
    ("x1",       np.float32),
    ("y2",       np.float32),
    ("x2",       np.float32),
    ("score",    np.float32),
    ("class_id", np.uint16),
])
NMS_BY_SCORE_RECORD_BYTES = _NMS_BY_SCORE_RECORD.itemsize   # 22


def _decode_nms_by_score_bytes(buf, score_threshold, num_classes):
    """Decode HailoRT 4.x ``HAILO_NMS_BY_SCORE`` packed byte stream.

    Layout:
      ``uint16 n_dets`` header, then ``n_dets`` × 22-byte records:
        ``float32 y1, x1, y2, x2, score; uint16 class_id``

    Records are pre-sorted by descending score (Hailo's NMS does this).
    Boxes are normalized to [0, 1] in Hailo / YOLO ``[y_min, x_min,
    y_max, x_max]`` axis order — we swap to ``[x1, y1, x2, y2]`` to
    match the rest of the app.

    ``num_classes`` clamps the active prompt set: detections whose
    ``class_id`` is ≥ ``num_classes`` (i.e. land in the zero-padded
    embedding slots) are dropped.
    """
    if buf.size < 2:
        logger.error("on-device-NMS byte buffer too small: %d bytes", buf.size)
        return []
    n_dets = int(np.frombuffer(buf[:2], dtype=np.uint16)[0])
    if n_dets == 0:
        return []
    body_bytes = n_dets * NMS_BY_SCORE_RECORD_BYTES
    if 2 + body_bytes > buf.size:
        logger.error(
            "on-device-NMS byte buffer truncated: header=%d, need=%d, have=%d",
            n_dets, 2 + body_bytes, buf.size,
        )
        return []
    recs = np.frombuffer(buf[2:2 + body_bytes], dtype=_NMS_BY_SCORE_RECORD)

    detections = []
    for r in recs:
        score = float(r["score"])
        if score < score_threshold:
            # Records are sorted by score desc; we could break, but the
            # cost of finishing the loop on a tiny capped n_dets is trivial
            # and protects against unsorted edge cases.
            continue
        cls_id = int(r["class_id"])
        if cls_id >= num_classes:
            continue
        detections.append({
            "bbox": [float(r["x1"]), float(r["y1"]), float(r["x2"]), float(r["y2"])],
            "class_id": cls_id,
            "score": score,
        })
    # Already score-desc from the chip, but a final sort guards against
    # the (unusual) case where multiple records tie or the chip returns
    # an out-of-order tail.
    detections.sort(key=lambda d: d["score"], reverse=True)
    return detections


def _nms(boxes, scores, iou_threshold, containment_threshold=CONTAINMENT_THRESHOLD):
    """Greedy NMS with containment suppression. Returns indices to keep.

    A lower-scoring box is dropped against the kept (higher-scoring) box if EITHER:
      - IoU > iou_threshold                     (standard overlap), or
      - intersection / area(box) > containment_threshold  (box is mostly nested
        inside the kept one — e.g. a leaf inside the whole-plant box).

    Greedy order means the highest-scoring box in any nested cluster is the one
    kept; its contained parts are removed. Per-class, so cross-class nesting
    (a can inside a person) is untouched.
    """
    if len(boxes) == 0:
        return []

    order = scores.argsort()[::-1]
    keep = []

    x1 = boxes[:, 0]
    y1 = boxes[:, 1]
    x2 = boxes[:, 2]
    y2 = boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)

    while len(order) > 0:
        i = order[0]
        keep.append(i)
        if len(order) == 1:
            break
        rest = order[1:]
        xx1 = np.maximum(x1[i], x1[rest])
        yy1 = np.maximum(y1[i], y1[rest])
        xx2 = np.minimum(x2[i], x2[rest])
        yy2 = np.minimum(y2[i], y2[rest])
        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        iou = inter / (areas[i] + areas[rest] - inter + 1e-6)
        contained = inter / (areas[rest] + 1e-6)   # fraction of each rest box inside i
        drop = (iou > iou_threshold) | (contained > containment_threshold)
        order = rest[~drop]

    return keep
