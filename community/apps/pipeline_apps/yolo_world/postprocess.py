import numpy as np

from hailo_apps.python.core.common.hailo_logger import get_logger

logger = get_logger(__name__)

STRIDES = [8, 16, 32]
IMAGE_SIZE = 640


def postprocess(output_tensors, score_threshold=0.3, iou_threshold=0.7, num_classes=80):
    """Post-process YOLO World output tensors into detections.

    Args:
        output_tensors: dict mapping layer name to numpy array.
            Expected: 3 cls tensors (HxWx80) + 3 reg tensors (HxWx4).
            Cls outputs have sigmoid already applied on-device.
            Reg outputs are decoded distances (DFL done on-device).
        score_threshold: minimum confidence for a detection.
        iou_threshold: NMS IoU threshold.
        num_classes: number of active classes (for slicing padded outputs).

    Returns:
        list of dicts: [{"bbox": [x1,y1,x2,y2], "class_id": int, "score": float}, ...]
        Bounding boxes are normalized to [0, 1].
    """
    # Separate cls and reg tensors by shape
    cls_tensors = []
    reg_tensors = []
    for name in sorted(output_tensors.keys()):
        tensor = output_tensors[name]
        if len(tensor.shape) == 3:
            h, w, c = tensor.shape
        elif len(tensor.shape) == 4:
            # batch dim
            tensor = tensor[0]
            h, w, c = tensor.shape
        else:
            logger.warning("Unexpected tensor shape %s for %s", tensor.shape, name)
            continue

        if c == 80:
            cls_tensors.append(tensor)
        elif c == 4:
            reg_tensors.append(tensor)
        else:
            logger.warning("Unexpected channel count %d for %s", c, name)

    if len(cls_tensors) != 3 or len(reg_tensors) != 3:
        logger.error("Expected 3 cls + 3 reg tensors, got %d + %d", len(cls_tensors), len(reg_tensors))
        return []

    # Sort by spatial size (largest first = stride 8, then 16, then 32)
    cls_tensors.sort(key=lambda t: t.shape[0] * t.shape[1], reverse=True)
    reg_tensors.sort(key=lambda t: t.shape[0] * t.shape[1], reverse=True)

    all_boxes = []
    all_scores = []
    all_class_ids = []

    for scale_idx, (cls_map, reg_map, stride) in enumerate(zip(cls_tensors, reg_tensors, STRIDES)):
        h, w, _ = cls_map.shape

        # Create grid of center coordinates
        grid_y, grid_x = np.meshgrid(np.arange(h), np.arange(w), indexing="ij")
        center_x = (grid_x.astype(np.float32) + 0.5) * stride
        center_y = (grid_y.astype(np.float32) + 0.5) * stride

        # Decode boxes: reg_map contains [dist_left, dist_top, dist_right, dist_bottom]
        dist_left = reg_map[:, :, 0] * stride
        dist_top = reg_map[:, :, 1] * stride
        dist_right = reg_map[:, :, 2] * stride
        dist_bottom = reg_map[:, :, 3] * stride

        x1 = (center_x - dist_left) / IMAGE_SIZE
        y1 = (center_y - dist_top) / IMAGE_SIZE
        x2 = (center_x + dist_right) / IMAGE_SIZE
        y2 = (center_y + dist_bottom) / IMAGE_SIZE

        # Clip to [0, 1]
        x1 = np.clip(x1, 0.0, 1.0)
        y1 = np.clip(y1, 0.0, 1.0)
        x2 = np.clip(x2, 0.0, 1.0)
        y2 = np.clip(y2, 0.0, 1.0)

        # Flatten spatial dims
        boxes = np.stack([x1, y1, x2, y2], axis=-1).reshape(-1, 4)  # (H*W, 4)
        scores = cls_map[:, :, :num_classes].reshape(-1, num_classes)  # (H*W, num_classes)

        # Sigmoid already applied on-device — scores are probabilities

        # Find detections above threshold
        max_scores = scores.max(axis=1)
        mask = max_scores > score_threshold
        if not mask.any():
            continue

        filtered_boxes = boxes[mask]
        filtered_scores = scores[mask]
        filtered_class_ids = filtered_scores.argmax(axis=1)
        filtered_max_scores = filtered_scores.max(axis=1)

        all_boxes.append(filtered_boxes)
        all_scores.append(filtered_max_scores)
        all_class_ids.append(filtered_class_ids)

    if not all_boxes:
        return []

    all_boxes = np.concatenate(all_boxes, axis=0)
    all_scores = np.concatenate(all_scores, axis=0)
    all_class_ids = np.concatenate(all_class_ids, axis=0)

    # Per-class NMS
    detections = []
    for cls_id in np.unique(all_class_ids):
        cls_mask = all_class_ids == cls_id
        cls_boxes = all_boxes[cls_mask]
        cls_scores = all_scores[cls_mask]

        keep = _nms(cls_boxes, cls_scores, iou_threshold)
        for idx in keep:
            detections.append({
                "bbox": cls_boxes[idx].tolist(),
                "class_id": int(cls_id),
                "score": float(cls_scores[idx]),
            })

    # Sort by score descending
    detections.sort(key=lambda d: d["score"], reverse=True)
    return detections


def _nms(boxes, scores, iou_threshold):
    """Standard greedy NMS. Returns indices to keep."""
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

        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])

        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-6)

        remaining = np.where(iou <= iou_threshold)[0]
        order = order[remaining + 1]

    return keep
