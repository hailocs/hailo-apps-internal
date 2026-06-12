"""
Post-processing for aerial object counter.

Reuses the OBB postprocessing from oriented_object_detection and adds
counting-specific visualization (count overlay, per-class color coding).
"""

import cv2
import numpy as np
from typing import List, Tuple

try:
    from hailo_apps.python.core.common.toolbox import id_to_color
except ImportError:
    from pathlib import Path
    import sys
    core_dir = Path(__file__).resolve().parents[2] / "core"
    sys.path.insert(0, str(core_dir))
    from common.toolbox import id_to_color


# Import the core OBB postprocessing from the template app
import sys
from pathlib import Path
_obb_dir = Path(__file__).resolve().parent.parent / "oriented_object_detection"
if str(_obb_dir) not in sys.path:
    sys.path.insert(0, str(_obb_dir))

from oriented_object_detection_post_process import (
    obb_postprocess,
    rotated_nms,
    extract_obb_detections,
    prepare_ort_inputs_from_hailo,
    native_obb_postprocess,
)


def inference_result_handler(original_frame: np.ndarray, infer_results, labels, config_data, tracker=None):
    """
    Run oriented post-processing, count detections, and draw results.
    This is the callback-compatible interface matching the standalone toolbox's visualize() signature.
    """
    kept_boxes, kept_classes, kept_scores = obb_postprocess(original_frame, infer_results, config_data)

    # Count per class
    class_counts = {}
    for cls_id in kept_classes:
        label = labels[cls_id] if cls_id < len(labels) else f"class_{cls_id}"
        class_counts[label] = class_counts.get(label, 0) + 1

    total_count = len(kept_boxes)

    return draw_counting_overlay(
        original_frame, kept_boxes, kept_classes, kept_scores,
        labels, class_counts, total_count
    )


def draw_counting_overlay(image, boxes, classes, scores, labels, class_counts, total_count):
    """
    Draw rotated bounding boxes with per-class colors and a counting summary overlay.

    Args:
        image: BGR image (numpy array)
        boxes: List of ((cx, cy), (w, h), angle_deg) tuples
        classes: List of class IDs
        scores: List of confidence scores
        labels: List of label strings
        class_counts: Dict of {label_name: count}
        total_count: Total number of detections
    Returns:
        Annotated image with rotated boxes and count overlay
    """
    # Draw each rotated bounding box
    for box, cls_id, score in zip(boxes, classes, scores):
        color = tuple(id_to_color(cls_id).tolist())
        pts = cv2.boxPoints(box)
        pts = pts.astype(np.int32)
        cv2.polylines(image, [pts], isClosed=True, color=color, thickness=2)

        # Label at top-left corner of the rotated box
        tl = tuple(pts.min(axis=0))
        if labels and cls_id < len(labels):
            label_text = f"{labels[cls_id]} {score:.2f}"
        else:
            label_text = f"C{cls_id} {score:.2f}"

        # Background rectangle for label text
        (tw, th), _ = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(
            image,
            (int(tl[0]), int(tl[1]) - th - 6),
            (int(tl[0]) + tw, int(tl[1])),
            color, -1
        )
        cv2.putText(
            image, label_text,
            (int(tl[0]), int(tl[1]) - 4),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1
        )

    # Draw count summary overlay in top-left corner
    _draw_count_summary(image, class_counts, total_count)

    return image


def _draw_count_summary(image, class_counts, total_count):
    """Draw a semi-transparent count summary box in the top-left corner."""
    if total_count == 0:
        lines = ["No objects detected"]
    else:
        lines = [f"Total: {total_count} objects"]
        for cls_name, count in sorted(class_counts.items(), key=lambda x: -x[1]):
            lines.append(f"  {cls_name}: {count}")

    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.6
    thickness = 1
    line_height = 25
    padding = 10

    # Calculate overlay box size
    max_width = 0
    for line in lines:
        (tw, _), _ = cv2.getTextSize(line, font, font_scale, thickness)
        max_width = max(max_width, tw)

    box_w = max_width + 2 * padding
    box_h = len(lines) * line_height + 2 * padding

    # Semi-transparent background
    overlay = image.copy()
    cv2.rectangle(overlay, (0, 0), (box_w, box_h), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.6, image, 0.4, 0, image)

    # Draw text
    y = padding + line_height - 5
    for line in lines:
        cv2.putText(image, line, (padding, y), font, font_scale, (255, 255, 255), thickness)
        y += line_height

    return image
