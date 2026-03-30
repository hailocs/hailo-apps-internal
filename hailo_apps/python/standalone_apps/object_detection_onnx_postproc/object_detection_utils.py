#!/usr/bin/env python3

import sys

if __name__ == "__main__":
    print(
        "This module is a post-processing helper and is not executable by itself.\n"
        "Run the app entrypoint instead:\n"
        "  python object_detection_onnx_postproc.py -n yolo26n -i bus.jpg"
    )
    sys.exit(1)

import cv2
import numpy as np
try:
    from hailo_apps.python.core.common.toolbox import id_to_color
    from hailo_apps.python.core.common.onnx_utils import map_hef_outputs_to_onnx_inputs
except ImportError:
    from pathlib import Path
    import sys

    core_dir = Path(__file__).resolve().parents[2] / "core"
    sys.path.insert(0, str(core_dir))
    from common.toolbox import id_to_color
    from common.onnx_utils import map_hef_outputs_to_onnx_inputs

import os
from collections import deque

# Dictionary to store a limited history of tracklet coordinates.
# The keys will be the track IDs.
tracklet_history = {}
# Maximum number of past frames to display
trail_length = 30 
# Only draw trail for certain classes (e.g., person=0, phone=67 in COCO)
TRACKLET_CLASSES = [0, 67]  # PERSON, SMARTPHONE

def inference_result_handler(original_frame, infer_results, labels, config_data, tracker=None, draw_trail=False, 
                            onnx_config=None, onnx_session=None):
    """
    Processes inference results and draw detections (with optional tracking).

    Args:
        infer_results (list): Raw output from the model.
        original_frame (np.ndarray): Original image frame.
        labels (list): List of class labels.
        enable_tracking (bool): Whether tracking is enabled.
        tracker (BYTETracker, optional): ByteTrack tracker instance.
        onnx_config (dict, optional): ONNX postprocessing configuration.
        onnx_session (onnxruntime.InferenceSession, optional): ONNX Runtime session.

    Returns:
        np.ndarray: Frame with detections or tracks drawn.
    """
    # Route to appropriate postprocessing backend
    if onnx_session is not None:
        # ONNX-based postprocessing (HEF outputs or Full-ONNX intermediates -> ONNX postproc)
        if onnx_config is None:
            raise ValueError("onnx_session provided but onnx_config is None")
        detections = extract_detections_onnx(original_frame, infer_results, onnx_config, onnx_session, config_data)
    else:
        # Default: HailoRT-NMS postprocessing
        detections = extract_detections(original_frame, infer_results, config_data)
    
    frame_with_detections = draw_detections(detections, original_frame, labels, tracker=tracker, draw_trail=draw_trail)
    return frame_with_detections


def draw_detection(image: np.ndarray, box: list, labels: list, score: float, color: tuple, track=False):
    """
    Draw box and label for one detection.

    Args:
        image (np.ndarray): Image to draw on.
        box (list): Bounding box coordinates.
        labels (list): List of labels (1 or 2 elements).
        score (float): Detection score.
        color (tuple): Color for the bounding box.
        track (bool): Whether to include tracking info.
    """
    xmin, ymin, xmax, ymax = map(int, box)
    cv2.rectangle(image, (xmin, ymin), (xmax, ymax), color, 2)
    font = cv2.FONT_HERSHEY_SIMPLEX

    # Compose texts
    top_text = f"{labels[0]}: {score:.1f}%" if not track or len(labels) == 2 else f"{score:.1f}%"
    bottom_text = None

    if track:
        if len(labels) == 2:
            bottom_text = labels[1]
        else:
            bottom_text = labels[0]


    # Set colors
    text_color = (255, 255, 255)  # White
    border_color = (0, 0, 0)  # Black

    # Draw top text with black border first
    cv2.putText(image, top_text, (xmin + 4, ymin + 20), font, 0.5, border_color, 2, cv2.LINE_AA)
    cv2.putText(image, top_text, (xmin + 4, ymin + 20), font, 0.5, text_color, 1, cv2.LINE_AA)

    # Draw bottom text if exists
    if bottom_text:
        pos = (xmax - 50, ymax - 6)
        cv2.putText(image, bottom_text, pos, font, 0.5, border_color, 2, cv2.LINE_AA)
        cv2.putText(image, bottom_text, pos, font, 0.5, text_color, 1, cv2.LINE_AA)


def denormalize_and_rm_pad(box: list, size: int, padding_length: int, input_height: int, input_width: int) -> list:
    """
    Denormalize bounding box coordinates and remove padding.

    Args:
        box (list): Normalized bounding box coordinates [x1, y1, x2, y2] in 0-1 range.
        size (int): Size to scale the coordinates (max of height/width).
        padding_length (int): Length of padding to remove.
        input_height (int): Height of the input image.
        input_width (int): Width of the input image.

    Returns:
        list: Denormalized bounding box coordinates [ymin, xmin, ymax, xmax] with padding removed.
    """
    DEBUG = False  # Disable debug to reduce noise
    if DEBUG:
        from hailo_apps.python.core.common.hailo_logger import get_logger
        logger = get_logger(__name__)
        logger.info(f"denormalize_and_rm_pad: input box={box}, size={size}, pad={padding_length}, img_h={input_height}, img_w={input_width}")
    
    # Scale box coordinates
    box = [int(x * size) for x in box]
    if DEBUG:
        logger.info(f"  After scaling by {size}: {box}")

    # Apply padding correction (ORIGINAL LOGIC - WORKS FOR OTHER NETWORKS)
    for i in range(4):
        if i % 2 == 0:  # x-coordinates
            if input_height != size:
                box[i] -= padding_length
        else:  # y-coordinates
            if input_width != size:
                box[i] -= padding_length
    
    if DEBUG:
        logger.info(f"  After padding removal: {box}")

    # Swap to [ymin, xmin, ymax, xmax]
    result = [box[1], box[0], box[3], box[2]]
    if DEBUG:
        logger.info(f"  After swap to [ymin,xmin,ymax,xmax]: {result}")
    return result


def extract_detections(image: np.ndarray, detections: list, config_data) -> dict:
    """
    Extract detections from the input data.

    Args:
        image (np.ndarray): Image to draw on.
        detections (list): Raw detections from the model.
        config_data (Dict): Loaded JSON config containing post-processing metadata.

    Returns:
        dict: Filtered detection results containing 'detection_boxes', 'detection_classes', 'detection_scores', and 'num_detections'.
    """

    visualization_params = config_data["visualization_params"]
    score_threshold = visualization_params.get("score_thres", 0.5)
    max_boxes = visualization_params.get("max_boxes_to_draw", 50)

    img_height, img_width = image.shape[:2]
    size = max(img_height, img_width)
    padding_length = int(abs(img_height - img_width) / 2)

    all_detections = []
    
    if isinstance(detections, dict):
        # Dict format - likely raw HEF outputs, not HailoRT-NMS
        raise ValueError(
            f"Expected HailoRT-NMS format (list of per-class detections), "
            f"but got dict with keys: {list(detections.keys())}. "
            f"This model may not have on-device NMS enabled. "
            f"Use the ONNX-postprocessing standalone app variant for this model."
        )
    
    for class_id, detection in enumerate(detections):
        if not isinstance(detection, (list, np.ndarray)):
            raise ValueError(
                f"Unexpected detection format for class {class_id}: {type(detection)}. "
                f"Expected array of detections, got: {detection}"
            )
        for det in detection:
            if len(det) < 5:
                raise ValueError(
                    f"Invalid detection format: expected at least 5 values [x1, y1, x2, y2, score], "
                    f"but got {len(det)} values: {det}"
                )
            bbox, score = det[:4], det[4]
            if score >= score_threshold:
                denorm_bbox = denormalize_and_rm_pad(bbox, size, padding_length, img_height, img_width)
                all_detections.append((score, class_id, denorm_bbox))

    # Sort all detections by score descending
    all_detections.sort(reverse=True, key=lambda x: x[0])

    # Take top max_boxes
    top_detections = all_detections[:max_boxes]

    scores, class_ids, boxes = zip(*top_detections) if top_detections else ([], [], [])

    return {
        'detection_boxes': list(boxes),
        'detection_classes': list(class_ids),
        'detection_scores': list(scores),
        'num_detections': len(top_detections)
    }


def draw_detections(detections: dict, img_out: np.ndarray, labels, tracker=None, draw_trail=False) -> np.ndarray:
    """
    Draw detections or tracking results on the image.

    Args:
        detections (dict): Raw detection outputs.
        img_out (np.ndarray): Image to draw on.
        labels (list): List of class labels.
        enable_tracking (bool): Whether to use tracker output (ByteTrack).
        tracker (BYTETracker, optional): ByteTrack tracker instance.

    Returns:
        np.ndarray: Annotated image.
    """

    # Extract detection data from the dictionary
    boxes = detections["detection_boxes"]  # List of [xmin,ymin,xmaxm, ymax] boxes
    scores = detections["detection_scores"]  # List of detection confidences
    num_detections = detections["num_detections"]  # Total number of valid detections
    classes = detections["detection_classes"]  # List of class indices per detection

    if tracker:
        dets_for_tracker = []

        # Convert detection format to [xmin,ymin,xmaxm ymax,score] for tracker
        for idx in range(num_detections):
            box = boxes[idx]  # [x, y, w, h]
            score = scores[idx]
            dets_for_tracker.append([*box, score])

        # Skip tracking if no detections passed
        if not dets_for_tracker:
            return img_out

        # Run BYTETracker and get active tracks
        online_targets = tracker.update(np.array(dets_for_tracker))

        # Draw tracked bounding boxes with ID labels
        for track in online_targets:
            track_id = track.track_id  # Unique tracker ID
            x1, y1, x2, y2 = track.tlbr  # Bounding box (top-left, bottom-right)
            xmin, ymin, xmax, ymax = map(int, [x1, y1, x2, y2])
            best_idx = find_best_matching_detection_index(track.tlbr, boxes)
            color = tuple(id_to_color(classes[best_idx]).tolist())  # Color based on class
            if best_idx is None:
                draw_detection(img_out, [xmin, ymin, xmax, ymax], f"ID {track_id}",
                               track.score * 100.0, color, track=True)
            else:
                draw_detection(img_out, [xmin, ymin, xmax, ymax], [labels[classes[best_idx]], f"ID {track_id}"],
                               track.score * 100.0, color, track=True)
                               
            if not classes[best_idx] in TRACKLET_CLASSES:
                continue

            # Get the centroid of the current bounding box
            center_x = int((x1 + x2) / 2)
            center_y = int((y1 + y2) / 2)
            centroid = (center_x, center_y)
            
            # Initialize or update the tracklet history
            if track_id not in tracklet_history:
                tracklet_history[track_id] = deque(maxlen=trail_length)
            tracklet_history[track_id].append(centroid)

            if draw_trail:
                for i in range(1, len(tracklet_history[track_id])):
                    # Get the center point for the current and previous frames
                    point_a = tracklet_history[track_id][i-1]
                    point_b = tracklet_history[track_id][i]

                    # Draw a line between the points and draw the points as circles
                    cv2.line(img_out, point_a, point_b, color, 3) #(255, 0, 0), 2)
                    cv2.circle(img_out, point_b, radius=20, thickness=1, color=color) #, thickness=-1) # -1 for filled circle



    else:
        # No tracking — draw raw model detections
        for idx in range(num_detections):
            class_id = classes[idx]
            # Validate class ID is within labels range
            if class_id >= len(labels):
                print(f"Warning: Class ID {class_id} out of range for labels (max: {len(labels)-1}). Skipping detection.")
                continue
            color = tuple(id_to_color(class_id).tolist())  # Color based on class
            draw_detection(img_out, boxes[idx], [labels[class_id]], scores[idx] * 100.0, color)

    return img_out


def find_best_matching_detection_index(track_box, detection_boxes):
    """
    Finds the index of the detection box with the highest IoU relative to the given tracking box.

    Args:
        track_box (list or tuple): The tracking box in [x_min, y_min, x_max, y_max] format.
        detection_boxes (list): List of detection boxes in [x_min, y_min, x_max, y_max] format.

    Returns:
        int or None: Index of the best matching detection, or None if no match is found.
    """
    best_iou = 0
    best_idx = -1

    for i, det_box in enumerate(detection_boxes):
        iou = compute_iou(track_box, det_box)
        if iou > best_iou:
            best_iou = iou
            best_idx = i

    return best_idx if best_idx != -1 else None


def compute_iou(boxA, boxB):
    """
    Compute Intersection over Union (IoU) between two bounding boxes.

    IoU measures the overlap between two boxes:
        IoU = (area of intersection) / (area of union)
    Values range from 0 (no overlap) to 1 (perfect overlap).

    Args:
        boxA (list or tuple): [x_min, y_min, x_max, y_max]
        boxB (list or tuple): [x_min, y_min, x_max, y_max]

    Returns:
        float: IoU value between 0 and 1.
    """
    xA, yA = max(boxA[0], boxB[0]), max(boxA[1], boxB[1])
    xB, yB = min(boxA[2], boxB[2]), min(boxA[3], boxB[3])
    inter = max(0, xB - xA) * max(0, yB - yA)
    areaA = max(1e-5, (boxA[2] - boxA[0]) * (boxA[3] - boxA[1]))
    areaB = max(1e-5, (boxB[2] - boxB[0]) * (boxB[3] - boxB[1]))
    return inter / (areaA + areaB - inter + 1e-5)


# ==================== ONNX Postprocessing Functions ====================

# Supported output formats for ONNX postprocessing
SUPPORTED_OUTPUT_FORMATS = ["yolon26", "yolov8", "yolov5"]


def extract_detections_onnx(image: np.ndarray, hailo_outputs: dict, onnx_config: dict, onnx_session, config_data: dict) -> dict:
    """
    Extract detections using ONNX postprocessing model.
    Maps HEF output tensors to ONNX inputs, runs inference, and parses results.
    
    Args:
        image (np.ndarray): Original image frame for coordinate denormalization.
        hailo_outputs (dict): Dict of HEF output tensors {name: numpy array}.
        onnx_config (dict): ONNX configuration with tensor mapping and format spec.
        onnx_session: ONNX Runtime inference session for postprocessing model.
        config_data (dict): Main config with visualization_params.
        
    Returns:
        dict: Detection results with 'detection_boxes', 'detection_classes', 
              'detection_scores', and 'num_detections'.
    """
    tensor_mapping = onnx_config["output_tensor_mapping"]
    output_format = onnx_config["output_format"]
    
    # Validate output format
    if output_format not in SUPPORTED_OUTPUT_FORMATS:
        raise ValueError(
            f"Unsupported output_format '{output_format}'. "
            f"Supported formats: {SUPPORTED_OUTPUT_FORMATS}"
        )
    
    # Map HEF outputs to ONNX inputs (handles NHWC->NCHW, shape/dtype validation)
    onnx_inputs = map_hef_outputs_to_onnx_inputs(hailo_outputs, tensor_mapping)
    
    # Run ONNX postprocessing inference
    onnx_output_names = [out.name for out in onnx_session.get_outputs()]
    onnx_results = onnx_session.run(onnx_output_names, onnx_inputs)
    
    # Parse ONNX output to normalized coords (matching HailoRT-NMS format)
    if output_format == "yolon26":
        detections = parse_yolon26_output(onnx_results, image, onnx_config, config_data)
    elif output_format == "yolov8":
        detections = parse_yolov8_output(onnx_results, image, onnx_config)
    elif output_format == "yolov5":
        detections = parse_yolov5_output(onnx_results, image, onnx_config)
    else:
        raise NotImplementedError(f"Parser for format '{output_format}' not implemented")
    
    # Reuse extract_detections to handle denormalization and filtering
    return extract_detections(image, detections, config_data)


def extract_detections_onnx_direct(image: np.ndarray, onnx_output, onnx_config: dict) -> dict:
    """
    Extract detections from full ONNX model output (debug mode).
    Used when use_full_onnx_mode=True and inference was done entirely in ONNX.
    
    Args:
        image (np.ndarray): Original image frame for coordinate denormalization.
        onnx_output: Direct output from full ONNX model inference.
        onnx_config (dict): ONNX configuration with format spec.
        
    Returns:
        dict: Detection results with 'detection_boxes', 'detection_classes', 
              'detection_scores', and 'num_detections'.
    """
    output_format = onnx_config["output_format"]
    
    # Validate output format
    if output_format not in SUPPORTED_OUTPUT_FORMATS:
        raise ValueError(
            f"Unsupported output_format '{output_format}'. "
            f"Supported formats: {SUPPORTED_OUTPUT_FORMATS}"
        )
    
    # Wrap output in list format expected by parsers
    onnx_results = [onnx_output] if not isinstance(onnx_output, list) else onnx_output
    
    # Parse ONNX output to normalized coords (matching HailoRT-NMS format)
    if output_format == "yolon26":
        detections = parse_yolon26_output(onnx_results, image, onnx_config)
    elif output_format == "yolov8":
        detections = parse_yolov8_output(onnx_results, image, onnx_config)
    elif output_format == "yolov5":
        detections = parse_yolov5_output(onnx_results, image, onnx_config)
    else:
        raise NotImplementedError(f"Parser for format '{output_format}' not implemented")
    
    # Reuse extract_detections to handle denormalization and filtering
    return extract_detections(image, detections, onnx_config)


def parse_yolon26_output(onnx_results, image: np.ndarray, onnx_config: dict, config_data: dict) -> list:
    """
    Parse YOLOv26n ONNX output to per-class detection list.
    Returns per-class detections in normalized coordinates matching HailoRT-NMS format.
    
    Args:
        onnx_results (list): ONNX inference outputs (first element is detection tensor).
        image (np.ndarray): Original image (not used, kept for compatibility).
        onnx_config (dict): Config with postprocess_params (input_size).
        config_data (dict): Main config with visualization_params (score_thres).
        
    Returns:
        list: Per-class detections [[bbox, score], ...] where bbox is [x1, y1, x2, y2] normalized 0-1.
    """
    # Read score threshold from shared visualization_params
    visualization_params = config_data.get("visualization_params", {})
    score_threshold = visualization_params.get("score_thres", 0.25)
    
    # Read model-specific params from ONNX config
    params = onnx_config.get("postprocess_params", {})
    input_size = params.get("input_size", 640)
    
    # Extract detection tensor (assume first output)
    detections = onnx_results[0]
    
    # Validate shape
    if detections.ndim == 3:  # Batch dimension
        detections = detections[0]  # Take first batch
    
    expected_shape = (300, 6)
    if detections.shape != expected_shape:
        raise ValueError(
            f"YOLOv26n output shape mismatch: expected {expected_shape}, got {detections.shape}"
        )
    
    # Parse detections: [x1, y1, x2, y2, score, class_id]
    # ONNX outputs are in pixel space (0-640), normalize to 0-1 to match yolov5 format
    
    # Normalize by input_size to get 0-1 range, then clip negatives at 0
    x1s = np.clip(detections[:, 0] / input_size, 0, 1)
    y1s = np.clip(detections[:, 1] / input_size, 0, 1)
    x2s = np.clip(detections[:, 2] / input_size, 0, 1)
    y2s = np.clip(detections[:, 3] / input_size, 0, 1)
    confidences = detections[:, 4]
    class_ids = detections[:, 5].astype(int)
    
    # Apply score threshold
    valid_mask = confidences >= score_threshold
    x1s = x1s[valid_mask]
    y1s = y1s[valid_mask]
    x2s = x2s[valid_mask]
    y2s = y2s[valid_mask]
    confidences = confidences[valid_mask]
    class_ids = class_ids[valid_mask]
    
    # Debug checkpoint: detection count
    DEBUG = True
    if DEBUG and len(confidences) > 0:
        from hailo_apps.python.core.common.hailo_logger import get_logger
        logger = get_logger(__name__)
        logger.debug(f"YOLOv26n detections after threshold {score_threshold}: {len(confidences)}")
    
    # Group by class ID in HailoRT-NMS format: list of per-class detections
    # Each detection must match HailoRT-NMS output format which is [ymin, xmin, ymax, xmax, score]
    # (verified by checking yolov5 debug output)
    class_detections = {}
    for x1, y1, x2, y2, score, class_id in zip(x1s, y1s, x2s, y2s, confidences, class_ids):
        if class_id not in class_detections:
            class_detections[class_id] = []
        # Swap to [ymin, xmin, ymax, xmax, score] to match HailoRT-NMS format
        class_detections[class_id].append([float(y1), float(x1), float(y2), float(x2), float(score)])
    
    # Convert to list format (index = class_id)
    max_class_id = max(class_detections.keys()) if class_detections else 0
    detections_list = []
    for class_id in range(max_class_id + 1):
        detections_list.append(class_detections.get(class_id, []))
    
    return detections_list


def parse_yolov8_output(onnx_results: list, image: np.ndarray, onnx_config: dict) -> list:
    """
    Parse YOLOv8 output format (placeholder for future implementation).
    
    Args:
        onnx_results (list): ONNX inference outputs.
        image (np.ndarray): Original image (not used, kept for compatibility).
        onnx_config (dict): Config with postprocess_params.
        
    Returns:
        list: Per-class detections in HailoRT-NMS format.
    """
    raise NotImplementedError(
        "YOLOv8 format parser not yet implemented. "
        "This is a placeholder to demonstrate extensibility. "
        "Expected format: [batch, 84, 8400] with [x, y, w, h, class_scores...]"
    )


def parse_yolov5_output(onnx_results: list, image: np.ndarray, onnx_config: dict) -> list:
    """
    Parse YOLOv5 output format (placeholder for future implementation).
    
    Args:
        onnx_results (list): ONNX inference outputs.
        image (np.ndarray): Original image (not used, kept for compatibility).
        onnx_config (dict): Config with postprocess_params.
        
    Returns:
        list: Per-class detections in HailoRT-NMS format.
    """
    raise NotImplementedError(
        "YOLOv5 format parser not yet implemented. "
        "This is a placeholder to demonstrate extensibility. "
        "Expected format: [batch, num_anchors, 85] with [x, y, w, h, objectness, class_scores...]"
    )

