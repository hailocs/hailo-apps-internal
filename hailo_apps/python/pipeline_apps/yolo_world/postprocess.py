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
# Drop a same-class box when this fraction of it sits inside a kept higher-scoring
# box (suppresses parts-of-an-object nested in the whole-object box). Tune here.
CONTAINMENT_THRESHOLD = 0.8

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


def postprocess(output_tensors, score_threshold=0.3, iou_threshold=0.7, num_classes=80):
    """Post-process YOLO World output tensors into detections.

    Args:
        output_tensors: dict mapping layer name to numpy array.
            Expected: 3 cls tensors (HxWx80) + 3 reg tensors (HxWx4 or HxWx64).
            Cls outputs have sigmoid applied on-device.
        score_threshold: minimum confidence for a detection.
        iou_threshold: NMS IoU threshold.
        num_classes: number of active classes (for slicing padded outputs).

    Returns:
        list of dicts: [{"bbox": [x1,y1,x2,y2], "class_id": int, "score": float}, ...]
        Bounding boxes are normalized to [0, 1].
    """
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
