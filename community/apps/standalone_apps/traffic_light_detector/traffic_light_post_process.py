"""
Traffic Light Post-Processing Module.

Decodes YOLOv8 detection output, filters for traffic light detections (COCO class 9),
classifies each detected light's state (red, yellow, green) using HSV color analysis
on the cropped region, and draws annotated results on the frame.
"""
import cv2
import numpy as np
from typing import Optional

try:
    from hailo_apps.python.core.common.hailo_logger import get_logger
except ImportError:
    from pathlib import Path
    import sys
    core_dir = Path(__file__).resolve().parents[2] / "core"
    sys.path.insert(0, str(core_dir))
    from common.hailo_logger import get_logger

logger = get_logger(__name__)

# COCO class ID for traffic light
TRAFFIC_LIGHT_CLASS_ID = 9

# HSV color ranges for traffic light state classification
# These ranges are tuned for typical traffic light colors
COLOR_RANGES = {
    "red": [
        # Red wraps around in HSV, so we need two ranges
        {"lower": np.array([0, 100, 100]), "upper": np.array([10, 255, 255])},
        {"lower": np.array([160, 100, 100]), "upper": np.array([180, 255, 255])},
    ],
    "yellow": [
        {"lower": np.array([15, 100, 100]), "upper": np.array([35, 255, 255])},
    ],
    "green": [
        {"lower": np.array([40, 50, 50]), "upper": np.array([90, 255, 255])},
    ],
}

# Colors for drawing (BGR format)
STATE_COLORS = {
    "red": (0, 0, 255),
    "yellow": (0, 255, 255),
    "green": (0, 255, 0),
    "unknown": (128, 128, 128),
}


def classify_traffic_light_state(crop: np.ndarray) -> str:
    """
    Classify the state of a traffic light from a cropped image region.

    Uses HSV color space analysis to determine whether the light is red, yellow,
    or green. The classification is based on the dominant color among the bright
    pixels in the cropped region.

    Args:
        crop: BGR image crop of the detected traffic light region.

    Returns:
        str: One of "red", "yellow", "green", or "unknown".
    """
    if crop.size == 0 or crop.shape[0] < 4 or crop.shape[1] < 4:
        return "unknown"

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)

    # Count pixels matching each color range
    color_scores = {}
    for color_name, ranges in COLOR_RANGES.items():
        mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
        for r in ranges:
            mask |= cv2.inRange(hsv, r["lower"], r["upper"])
        color_scores[color_name] = np.sum(mask > 0)

    total_pixels = crop.shape[0] * crop.shape[1]
    if total_pixels == 0:
        return "unknown"

    # Find the dominant color
    best_color = max(color_scores, key=color_scores.get)
    best_score = color_scores[best_color]

    # Require at least 3% of pixels to match to avoid noise
    min_pixel_fraction = 0.03
    if best_score < total_pixels * min_pixel_fraction:
        return "unknown"

    return best_color


def denormalize_and_rm_pad(box: list, size: int, padding_length: int,
                           input_height: int, input_width: int) -> list:
    """
    Denormalize bounding box coordinates and remove letterbox padding.

    Args:
        box: Normalized bounding box coordinates [x1, y1, x2, y2].
        size: Size used for scaling (max of height, width).
        padding_length: Length of padding to remove.
        input_height: Height of the original image.
        input_width: Width of the original image.

    Returns:
        list: Denormalized bounding box coordinates [ymin, xmin, ymax, xmax].
    """
    box = [int(x * size) for x in box]

    for i in range(4):
        if i % 2 == 0:  # x-coordinates
            if input_height != size:
                box[i] -= padding_length
        else:  # y-coordinates
            if input_width != size:
                box[i] -= padding_length

    # Swap to [ymin, xmin, ymax, xmax]
    return [box[1], box[0], box[3], box[2]]


def extract_detections(image: np.ndarray, detections: list, config_data: dict) -> dict:
    """
    Extract detections from model output, filtering for traffic lights only.

    Args:
        image: Original image frame.
        detections: Raw detections from the model (list of arrays per class).
        config_data: Configuration dict with visualization parameters.

    Returns:
        dict: Filtered detection results with keys:
            'detection_boxes', 'detection_classes', 'detection_scores', 'num_detections'.
    """
    visualization_params = config_data.get("visualization_params", {})
    score_threshold = visualization_params.get("score_thres", 0.3)
    max_boxes = visualization_params.get("max_boxes_to_draw", 100)
    target_class_id = visualization_params.get("traffic_light_class_id", TRAFFIC_LIGHT_CLASS_ID)

    img_height, img_width = image.shape[:2]
    size = max(img_height, img_width)
    padding_length = int(abs(img_height - img_width) / 2)

    all_detections = []

    for class_id, detection in enumerate(detections):
        # Only keep traffic light detections (COCO class 9)
        if class_id != target_class_id:
            continue
        for det in detection:
            bbox, score = det[:4], det[4]
            if score >= score_threshold:
                denorm_bbox = denormalize_and_rm_pad(
                    bbox, size, padding_length, img_height, img_width
                )
                all_detections.append((score, class_id, denorm_bbox))

    # Sort by score descending
    all_detections.sort(reverse=True, key=lambda x: x[0])
    top_detections = all_detections[:max_boxes]

    scores, class_ids, boxes = zip(*top_detections) if top_detections else ([], [], [])

    return {
        "detection_boxes": list(boxes),
        "detection_classes": list(class_ids),
        "detection_scores": list(scores),
        "num_detections": len(top_detections),
    }


def draw_traffic_light(image: np.ndarray, box: list, state: str,
                       score: float) -> None:
    """
    Draw a single traffic light detection with its classified state.

    Args:
        image: Image to draw on.
        box: Bounding box coordinates [xmin, ymin, xmax, ymax].
        state: Classified state ("red", "yellow", "green", "unknown").
        score: Detection confidence score.
    """
    xmin, ymin, xmax, ymax = map(int, box)
    color = STATE_COLORS.get(state, STATE_COLORS["unknown"])

    # Draw bounding box
    cv2.rectangle(image, (xmin, ymin), (xmax, ymax), color, 2)

    # Draw label with state and confidence
    label_text = f"{state.upper()}: {score * 100:.1f}%"
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.6
    thickness = 2

    # Background rectangle for text readability
    (text_w, text_h), baseline = cv2.getTextSize(label_text, font, font_scale, thickness)
    text_x = xmin
    text_y = ymin - 6
    if text_y - text_h < 0:
        text_y = ymax + text_h + 6

    cv2.rectangle(image, (text_x, text_y - text_h - baseline),
                  (text_x + text_w, text_y + baseline), color, -1)
    cv2.putText(image, label_text, (text_x, text_y), font, font_scale,
                (0, 0, 0), thickness, cv2.LINE_AA)


def inference_result_handler(
    original_frame: np.ndarray,
    infer_results,
    labels: list,
    config_data: dict,
    frame_summaries: Optional[list] = None,
    frame_counter: Optional[list] = None,
    **kwargs,
) -> np.ndarray:
    """
    Process inference results: detect traffic lights, classify state, draw results.

    This function is called by the visualize thread for each (frame, result) pair.

    Args:
        original_frame: Original input frame (BGR, uint8).
        infer_results: Raw model output from YOLOv8.
        labels: List of class label strings.
        config_data: Configuration dict with visualization parameters.
        frame_summaries: Optional list to append per-frame JSON summaries.
        frame_counter: Optional mutable list [counter] for frame numbering.

    Returns:
        np.ndarray: The frame with traffic light detections and state labels drawn.
    """
    detections = extract_detections(original_frame, infer_results, config_data)

    frame_height, frame_width = original_frame.shape[:2]
    frame_lights = []

    for idx in range(detections["num_detections"]):
        box = detections["detection_boxes"][idx]
        score = detections["detection_scores"][idx]

        # Extract crop for color classification
        # box is [ymin, xmin, ymax, xmax] after denormalization
        ymin, xmin, ymax, xmax = box
        # Clamp to frame bounds
        crop_ymin = max(0, int(ymin))
        crop_xmin = max(0, int(xmin))
        crop_ymax = min(frame_height, int(ymax))
        crop_xmax = min(frame_width, int(xmax))

        crop = original_frame[crop_ymin:crop_ymax, crop_xmin:crop_xmax]
        state = classify_traffic_light_state(crop)

        # Draw the detection with state
        draw_box = [xmin, ymin, xmax, ymax]  # Convert to [xmin, ymin, xmax, ymax] for drawing
        draw_traffic_light(original_frame, draw_box, state, score)

        # Collect for JSON summary
        if frame_summaries is not None:
            frame_lights.append({
                "state": state,
                "confidence": round(float(score), 4),
                "bbox": [int(xmin), int(ymin), int(xmax), int(ymax)],
            })

    # Append frame summary if requested
    if frame_summaries is not None and frame_counter is not None:
        frame_num = frame_counter[0]
        frame_counter[0] += 1
        if frame_lights:
            frame_summaries.append({
                "frame": frame_num,
                "traffic_lights": frame_lights,
            })

    # Draw summary count on frame
    count = detections["num_detections"]
    if count > 0:
        summary_text = f"Traffic Lights: {count}"
        cv2.putText(original_frame, summary_text, (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)

    return original_frame
