"""LPR postprocessing: CTC decoding for OCR engines and YOLOv4 LP detection."""

import cv2
import numpy as np

import hailo

from hailo_apps.python.core.common.hailo_inference import HailoInfer

# ---------------------------------------------------------------------------
# LPRNet character set (digits only, CTC blank is last)
# ---------------------------------------------------------------------------
LPRNET_CHARS = "0123456789-"
LPRNET_BLANK_IDX = len(LPRNET_CHARS) - 1

# ---------------------------------------------------------------------------
# PaddleOCR character set (97 classes: blank at index 0, full ASCII)
# ---------------------------------------------------------------------------
PADDLE_CHARACTERS = [
    "blank", "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
    ":", ";", "<", "=", ">", "?", "@",
    "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M",
    "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z",
    "[", "\\", "]", "^", "_", "`",
    "a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m",
    "n", "o", "p", "q", "r", "s", "t", "u", "v", "w", "x", "y", "z",
    "{", "|", "}", "~", "!", '"', "#", "$", "%", "&",
    "'", "(", ")", "*", "+", ",", "-", ".", "/", " ", " ",
]
PADDLE_BLANK_IDX = 0

# ---------------------------------------------------------------------------
# OCR and detection thresholds / constants
# ---------------------------------------------------------------------------
MIN_OCR_CONFIDENCE = 0.78
MIN_LENGTH = 4
SUMMARY_INTERVAL = 30  # seconds

# Minimum plate crop size in pixels for reliable OCR.
MIN_LP_WIDTH_PIXELS = 20
MIN_LP_HEIGHT_PIXELS = 8

# Maximum plate crop size — a plate covering most of the frame is a false positive.
MAX_LP_WIDTH_PIXELS = 600
MAX_LP_HEIGHT_PIXELS = 200

# ROI zone: only process vehicles whose center falls in the center 1/3 of the frame.
ROI_Y_START = 1.0 / 3.0
ROI_Y_END = 2.0 / 3.0


# ---------------------------------------------------------------------------
# CTC decoders
# ---------------------------------------------------------------------------
def ctc_decode_lprnet(output_data):
    """Decode LPRNet output (1,19,11) to license plate string (digits only)."""
    data = np.array(output_data, dtype=np.float32)
    if data.ndim == 3:
        data = data[0]
    data = data.reshape(19, 11)
    # Softmax per time-step
    data -= data.max(axis=1, keepdims=True)
    exp_data = np.exp(data)
    probs = exp_data / exp_data.sum(axis=1, keepdims=True)

    indices = np.argmax(probs, axis=1)
    max_probs = probs[np.arange(19), indices]

    chars, confs = [], []
    prev = LPRNET_BLANK_IDX
    for i, idx in enumerate(indices):
        if idx != prev and idx != LPRNET_BLANK_IDX:
            chars.append(LPRNET_CHARS[idx])
            confs.append(float(max_probs[i]))
        prev = idx

    text = "".join(chars)
    conf = float(np.mean(confs)) if confs else 0.0
    return text, conf


def ctc_decode_paddle(output_data):
    """Decode PaddleOCR recognition output (1,40,97) to text (full charset)."""
    data = np.array(output_data, dtype=np.float32)
    if data.ndim == 2:
        data = np.expand_dims(data, axis=0)
    text_index = data.argmax(axis=2)
    text_prob = data.max(axis=2)

    indices = text_index[0]
    probs = text_prob[0]
    chars, confs = [], []
    prev = PADDLE_BLANK_IDX
    for i, idx in enumerate(indices):
        if idx != prev and idx != PADDLE_BLANK_IDX:
            if idx < len(PADDLE_CHARACTERS):
                chars.append(PADDLE_CHARACTERS[idx])
                confs.append(float(probs[i]))
        prev = idx

    text = "".join(chars)
    conf = float(np.mean(confs)) if confs else 0.0
    return text, conf


# ---------------------------------------------------------------------------
# Tiny-YOLOv4 postprocess (Python implementation)
# ---------------------------------------------------------------------------
# Standard tiny-YOLOv4 anchors for license plate detection
LP_ANCHORS = [
    [(81, 82), (135, 169), (344, 319)],   # 13×13 grid (large objects)
    [(10, 14), (23, 27), (37, 58)],        # 26×26 grid (small objects)
]
LP_DETECTION_THRESHOLD = 0.3
LP_NMS_IOU_THRESHOLD = 0.45
LP_INPUT_SIZE = 416


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-np.clip(x, -50, 50)))


def _yolov4_decode_output(output, anchors, input_size, num_classes=1):
    """Decode a single YOLOv4 output tensor into bounding boxes.

    Args:
        output: numpy array of shape (grid_h, grid_w, num_anchors * (5 + num_classes))
        anchors: list of (w, h) tuples for anchors at this scale
        input_size: model input size (e.g. 416)
        num_classes: number of detection classes

    Returns:
        List of (x1, y1, x2, y2, obj_conf, cls_conf, cls_id) in pixel coords
    """
    grid_h, grid_w, _ = output.shape
    num_anchors = len(anchors)
    box_attrs = 5 + num_classes
    output = output.reshape(grid_h, grid_w, num_anchors, box_attrs)

    boxes = []
    for ay in range(grid_h):
        for ax in range(grid_w):
            for a_idx in range(num_anchors):
                raw = output[ay, ax, a_idx]
                tx, ty, tw, th = raw[0], raw[1], raw[2], raw[3]
                obj = _sigmoid(raw[4])

                if obj < LP_DETECTION_THRESHOLD:
                    continue

                cx = (_sigmoid(tx) + ax) / grid_w
                cy = (_sigmoid(ty) + ay) / grid_h
                w = (np.exp(tw) * anchors[a_idx][0]) / input_size
                h = (np.exp(th) * anchors[a_idx][1]) / input_size

                cls_scores = _sigmoid(raw[5: 5 + num_classes])
                cls_id = int(np.argmax(cls_scores))
                cls_conf = float(cls_scores[cls_id])
                score = float(obj * cls_conf)

                if score < LP_DETECTION_THRESHOLD:
                    continue

                x1 = cx - w / 2
                y1 = cy - h / 2
                x2 = cx + w / 2
                y2 = cy + h / 2
                boxes.append((x1, y1, x2, y2, score, cls_id))

    return boxes


def _nms(boxes, iou_threshold):
    """Simple NMS on list of (x1, y1, x2, y2, score, cls_id)."""
    if not boxes:
        return []
    boxes = sorted(boxes, key=lambda b: b[4], reverse=True)
    keep = []
    while boxes:
        best = boxes.pop(0)
        keep.append(best)
        remaining = []
        for b in boxes:
            iou = _compute_iou(best, b)
            if iou < iou_threshold:
                remaining.append(b)
        boxes = remaining
    return keep


def _compute_iou(a, b):
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0


def detect_license_plates(lp_outputs, lp_output_names):
    """Run YOLOv4 postprocess on LP detection model outputs.

    Args:
        lp_outputs: dict of {output_name: np.ndarray}
        lp_output_names: list of output names in order

    Returns:
        List of (x1, y1, x2, y2, score) in normalized coords (0-1)
    """
    all_boxes = []
    # Sort outputs by grid size (ascending) so smaller grid (13×13) comes first
    sorted_outputs = sorted(lp_output_names, key=lambda n: lp_outputs[n].shape[0])
    for i, name in enumerate(sorted_outputs):
        data = lp_outputs[name]
        anchor_set = LP_ANCHORS[i] if i < len(LP_ANCHORS) else LP_ANCHORS[-1]
        boxes = _yolov4_decode_output(data, anchor_set, LP_INPUT_SIZE)
        all_boxes.extend(boxes)

    return _nms(all_boxes, LP_NMS_IOU_THRESHOLD)


# ---------------------------------------------------------------------------
# LP detection helpers (GStreamer vs Python paths)
# ---------------------------------------------------------------------------
def detect_lps_gstreamer(detection, frame, frame_w, frame_h):
    """Hailo-10H path: read LP sub-detections from GStreamer cropper/hailofilter.

    Returns list of (lp_crop, x1, y1, x2, y2) tuples.
    """
    vbox = detection.get_bbox()
    results = []
    for lp in detection.get_objects_typed(hailo.HAILO_DETECTION):
        if lp.get_label() != "license_plate":
            continue
        lpbox = lp.get_bbox()
        x1 = max(0, int((vbox.xmin() + lpbox.xmin() * vbox.width()) * frame_w))
        y1 = max(0, int((vbox.ymin() + lpbox.ymin() * vbox.height()) * frame_h))
        x2 = min(
            frame_w,
            int((vbox.xmin() + (lpbox.xmin() + lpbox.width()) * vbox.width()) * frame_w),
        )
        y2 = min(
            frame_h,
            int((vbox.ymin() + (lpbox.ymin() + lpbox.height()) * vbox.height()) * frame_h),
        )
        crop_w = x2 - x1
        crop_h = y2 - y1
        if crop_w < MIN_LP_WIDTH_PIXELS or crop_h < MIN_LP_HEIGHT_PIXELS:
            continue
        if crop_w > MAX_LP_WIDTH_PIXELS or crop_h > MAX_LP_HEIGHT_PIXELS:
            continue
        lp_crop = frame[y1:y2, x1:x2]
        if lp_crop.size == 0:
            continue
        results.append((lp_crop, x1, y1, x2, y2))
    return results


def detect_lps_python(user_data, detection, frame, frame_w, frame_h):
    """Hailo-8/8L path: LP detection via HailoInfer + Python YOLOv4 postprocess.

    Returns list of (lp_crop, x1, y1, x2, y2) tuples.
    """
    vbox = detection.get_bbox()
    vx1 = max(0, int(vbox.xmin() * frame_w))
    vy1 = max(0, int(vbox.ymin() * frame_h))
    vx2 = min(frame_w, int((vbox.xmin() + vbox.width()) * frame_w))
    vy2 = min(frame_h, int((vbox.ymin() + vbox.height()) * frame_h))
    vehicle_crop = frame[vy1:vy2, vx1:vx2]
    if vehicle_crop.size == 0:
        return []

    vehicle_resized = cv2.resize(vehicle_crop, (user_data.lp_w, user_data.lp_h))

    user_data.lp_result = None
    user_data.lp_infer.run([vehicle_resized], user_data.lp_callback)
    if user_data.lp_infer.last_infer_job:
        user_data.lp_infer.last_infer_job.wait(5000)

    if user_data.lp_result is None or not isinstance(user_data.lp_result, dict):
        return []

    lp_boxes = detect_license_plates(user_data.lp_result, user_data.lp_output_names)

    results = []
    vehicle_h, vehicle_w = vehicle_crop.shape[:2]
    for lp_box in lp_boxes:
        lp_x1_norm, lp_y1_norm, lp_x2_norm, lp_y2_norm, _score, _cls = lp_box
        lp_x1 = max(0, vx1 + int(lp_x1_norm * vehicle_w))
        lp_y1 = max(0, vy1 + int(lp_y1_norm * vehicle_h))
        lp_x2 = min(frame_w, vx1 + int(lp_x2_norm * vehicle_w))
        lp_y2 = min(frame_h, vy1 + int(lp_y2_norm * vehicle_h))
        crop_w = lp_x2 - lp_x1
        crop_h = lp_y2 - lp_y1
        if crop_w < MIN_LP_WIDTH_PIXELS or crop_h < MIN_LP_HEIGHT_PIXELS:
            continue
        if crop_w > MAX_LP_WIDTH_PIXELS or crop_h > MAX_LP_HEIGHT_PIXELS:
            continue
        lp_crop = frame[lp_y1:lp_y2, lp_x1:lp_x2]
        if lp_crop.size == 0:
            continue
        results.append((lp_crop, lp_x1, lp_y1, lp_x2, lp_y2))
    return results
