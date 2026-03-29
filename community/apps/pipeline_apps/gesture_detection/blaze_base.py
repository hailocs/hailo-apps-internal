"""
Common utilities for MediaPipe Blaze palm detection and hand landmark models.

Ported from AlbertaBeef/blaze_app_python (https://github.com/AlbertaBeef/blaze_app_python).
Reference: https://www.hackster.io/AlbertaBeef/blaze-app-hailo-8-edition-f1e14c

Includes:
- SSD anchor generation for palm detection
- Box decoding and NMS
- ROI extraction (affine warp) for hand landmark
- Coordinate denormalization utilities
"""

import cv2
import numpy as np


# --- Palm detection v0.10 config (192x192 input, 2016 anchors) ---

PALM_ANCHOR_OPTIONS = {
    "num_layers": 4,
    "min_scale": 0.1484375,
    "max_scale": 0.75,
    "input_size_height": 192,
    "input_size_width": 192,
    "anchor_offset_x": 0.5,
    "anchor_offset_y": 0.5,
    "strides": [8, 16, 16, 16],
    "aspect_ratios": [1.0],
    "reduce_boxes_in_lowest_layer": False,
    "interpolated_scale_aspect_ratio": 1.0,
    "fixed_anchor_size": True,
}

PALM_MODEL_CONFIG = {
    "num_classes": 1,
    "num_anchors": 2016,
    "num_coords": 18,
    "score_clipping_thresh": 100.0,
    "x_scale": 192.0,
    "y_scale": 192.0,
    "h_scale": 192.0,
    "w_scale": 192.0,
    "min_score_thresh": 0.5,
    "min_suppression_threshold": 0.3,
    "num_keypoints": 7,
    "detection2roi_method": "box",
    "kp1": 0,
    "kp2": 2,
    "theta0": np.pi / 2,
    "dscale": 2.6,
    "dy": -0.5,
}

HAND_LANDMARK_RESOLUTION = 224


# --- Anchor generation ---

def generate_anchors(options):
    """Generate SSD anchors following MediaPipe's ssd_anchors_calculator.

    Args:
        options: Dict with anchor generation parameters.

    Returns:
        np.ndarray of shape (num_anchors, 4) with columns [x_center, y_center, w, h].
    """
    anchors = []
    layer_id = 0
    n_strides = len(options["strides"])

    while layer_id < n_strides:
        anchor_height = []
        anchor_width = []
        aspect_ratios = []
        scales = []

        # Collect consecutive layers with same stride
        last_same_stride_layer = layer_id
        while (last_same_stride_layer < n_strides and
               options["strides"][last_same_stride_layer] == options["strides"][layer_id]):
            scale = (options["min_scale"] +
                     (options["max_scale"] - options["min_scale"]) *
                     last_same_stride_layer / (n_strides - 1.0))
            if last_same_stride_layer == 0 and options["reduce_boxes_in_lowest_layer"]:
                aspect_ratios.append(1.0)
                aspect_ratios.append(2.0)
                aspect_ratios.append(0.5)
                scales.append(0.1)
                scales.append(scale)
                scales.append(scale)
            else:
                for ar in options["aspect_ratios"]:
                    aspect_ratios.append(ar)
                    scales.append(scale)
                if options["interpolated_scale_aspect_ratio"] > 0.0:
                    if last_same_stride_layer == n_strides - 1:
                        scale_next = 1.0
                    else:
                        scale_next = (options["min_scale"] +
                                      (options["max_scale"] - options["min_scale"]) *
                                      (last_same_stride_layer + 1) / (n_strides - 1.0))
                    aspect_ratios.append(options["interpolated_scale_aspect_ratio"])
                    scales.append(np.sqrt(scale * scale_next))
            last_same_stride_layer += 1

        for i in range(len(aspect_ratios)):
            ratio_sqrts = np.sqrt(aspect_ratios[i])
            anchor_height.append(scales[i] / ratio_sqrts)
            anchor_width.append(scales[i] * ratio_sqrts)

        stride = options["strides"][layer_id]
        feature_map_height = int(np.ceil(options["input_size_height"] / stride))
        feature_map_width = int(np.ceil(options["input_size_width"] / stride))

        for y in range(feature_map_height):
            for x in range(feature_map_width):
                for anchor_id in range(len(anchor_height)):
                    x_center = (x + options["anchor_offset_x"]) / feature_map_width
                    y_center = (y + options["anchor_offset_y"]) / feature_map_height
                    if options["fixed_anchor_size"]:
                        new_anchor = [x_center, y_center, 1.0, 1.0]
                    else:
                        new_anchor = [x_center, y_center,
                                      anchor_width[anchor_id], anchor_height[anchor_id]]
                    anchors.append(new_anchor)

        layer_id = last_same_stride_layer

    return np.array(anchors, dtype=np.float32)


# --- Detection decoding ---

def decode_boxes(raw_boxes, anchors, config):
    """Decode raw box predictions relative to anchors.

    Args:
        raw_boxes: np.ndarray of shape (batch, num_anchors, num_coords).
        anchors: np.ndarray of shape (num_anchors, 4).
        config: Model config dict with scale values.

    Returns:
        np.ndarray of shape (batch, num_anchors, num_coords) with decoded boxes.
        Format: [ymin, xmin, ymax, xmax, kp0_x, kp0_y, kp1_x, kp1_y, ...].
    """
    x_scale = config["x_scale"]
    y_scale = config["y_scale"]
    w_scale = config["w_scale"]
    h_scale = config["h_scale"]
    num_keypoints = config["num_keypoints"]

    boxes = np.zeros_like(raw_boxes)

    x_center = raw_boxes[..., 0] / x_scale * anchors[:, 2] + anchors[:, 0]
    y_center = raw_boxes[..., 1] / y_scale * anchors[:, 3] + anchors[:, 1]
    w = raw_boxes[..., 2] / w_scale * anchors[:, 2]
    h = raw_boxes[..., 3] / h_scale * anchors[:, 3]

    boxes[..., 0] = y_center - h / 2.0  # ymin
    boxes[..., 1] = x_center - w / 2.0  # xmin
    boxes[..., 2] = y_center + h / 2.0  # ymax
    boxes[..., 3] = x_center + w / 2.0  # xmax

    for k in range(num_keypoints):
        offset = 4 + k * 2
        kp_x = raw_boxes[..., offset] / x_scale * anchors[:, 2] + anchors[:, 0]
        kp_y = raw_boxes[..., offset + 1] / y_scale * anchors[:, 3] + anchors[:, 1]
        boxes[..., offset] = kp_x
        boxes[..., offset + 1] = kp_y

    return boxes


def tensors_to_detections(raw_box_tensor, raw_score_tensor, anchors, config):
    """Full decode pipeline: decode boxes, apply sigmoid to scores, threshold + filter.

    Args:
        raw_box_tensor: np.ndarray (batch, num_anchors, num_coords).
        raw_score_tensor: np.ndarray (batch, num_anchors, 1).
        anchors: np.ndarray (num_anchors, 4).
        config: Model config dict.

    Returns:
        List of np.ndarray per batch, each (N, num_coords+1) where last col is score.
    """
    detection_boxes = decode_boxes(raw_box_tensor, anchors, config)

    thresh = config["score_clipping_thresh"]
    raw_score_tensor = np.clip(raw_score_tensor, -thresh, thresh)
    detection_scores = 1.0 / (1.0 + np.exp(-raw_score_tensor))

    # Remove score dimension
    detection_scores = detection_scores[..., 0]

    mask = detection_scores >= config["min_score_thresh"]

    output_detections = []
    for i in range(raw_box_tensor.shape[0]):
        boxes_i = detection_boxes[i][mask[i]]
        scores_i = detection_scores[i][mask[i]]
        if len(scores_i) > 0:
            det = np.concatenate([boxes_i, scores_i[:, np.newaxis]], axis=-1)
        else:
            det = np.zeros((0, config["num_coords"] + 1), dtype=np.float32)
        output_detections.append(det)

    return output_detections


def weighted_non_max_suppression(detections, min_suppression_threshold):
    """BlazeFace-style weighted NMS.

    Instead of discarding overlapping detections, takes a weighted average
    of their coordinates based on confidence scores.

    Args:
        detections: np.ndarray of shape (N, num_coords+1), last col is score.
        min_suppression_threshold: IOU threshold for suppression.

    Returns:
        List of remaining detections (np.ndarray rows).
    """
    if len(detections) == 0:
        return []

    remaining = np.argsort(-detections[:, -1]).tolist()
    output = []

    while len(remaining) > 0:
        det = detections[remaining[0]]
        first_box = det[:4]

        other_indices = remaining[1:]
        if len(other_indices) == 0:
            output.append(det)
            break

        other_boxes = detections[other_indices][:, :4]

        # Compute IOU
        ious = _compute_iou(first_box, other_boxes)

        # Find overlapping boxes
        mask = ious > min_suppression_threshold
        overlapping = [remaining[0]] + [other_indices[j] for j in range(len(other_indices)) if mask[j]]
        non_overlapping = [other_indices[j] for j in range(len(other_indices)) if not mask[j]]

        # Weighted average of overlapping detections
        overlap_dets = detections[overlapping]
        weights = overlap_dets[:, -1:]  # scores as weights
        weighted_det = np.sum(overlap_dets[:, :-1] * weights, axis=0) / np.sum(weights)
        merged = np.append(weighted_det, det[-1])  # keep best score
        output.append(merged)

        remaining = non_overlapping

    return output


def _compute_iou(box, boxes):
    """Compute IOU between one box and an array of boxes.

    Box format: [ymin, xmin, ymax, xmax].
    """
    y1 = np.maximum(box[0], boxes[:, 0])
    x1 = np.maximum(box[1], boxes[:, 1])
    y2 = np.minimum(box[2], boxes[:, 2])
    x2 = np.minimum(box[3], boxes[:, 3])

    intersection = np.maximum(0, y2 - y1) * np.maximum(0, x2 - x1)

    area1 = (box[2] - box[0]) * (box[3] - box[1])
    area2 = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    union = area1 + area2 - intersection

    return intersection / np.maximum(union, 1e-6)


# --- Image preprocessing ---

def resize_pad(img, target_size):
    """Resize image maintaining aspect ratio and pad to target_size.

    Args:
        img: Input image (H, W, C).
        target_size: Tuple (height, width) for output.

    Returns:
        (padded_img, scale, pad) where:
        - padded_img: Resized and padded image.
        - scale: Scale factor applied (for denormalization).
        - pad: (pad_y, pad_x) offset in original image coordinates.
    """
    h, w = img.shape[:2]
    th, tw = target_size

    scale = min(th / h, tw / w)
    new_h, new_w = int(h * scale), int(w * scale)

    resized = cv2.resize(img, (new_w, new_h))

    pad_h = (th - new_h) // 2
    pad_w = (tw - new_w) // 2

    padded = np.zeros((th, tw, 3), dtype=img.dtype)
    padded[pad_h:pad_h + new_h, pad_w:pad_w + new_w] = resized

    # Return scale and pad in original image coordinates
    inv_scale = 1.0 / scale
    pad_orig = (pad_h * inv_scale, pad_w * inv_scale)

    return padded, inv_scale, pad_orig


def denormalize_detections(detections, scale, pad, model_scale):
    """Map normalized [0,1] detection coordinates back to original image space.

    Args:
        detections: np.ndarray (N, num_coords+1), coords in [0,1].
        scale: Inverse scale from resize_pad.
        pad: (pad_y, pad_x) from resize_pad.
        model_scale: Model input size (e.g. 192.0).

    Returns:
        Modified detections with coordinates in original image pixels.
    """
    if len(detections) == 0:
        return detections

    detections = np.array(detections, dtype=np.float32)

    # Box coords: [ymin, xmin, ymax, xmax]
    detections[:, 0] = detections[:, 0] * scale * model_scale - pad[0]  # ymin
    detections[:, 1] = detections[:, 1] * scale * model_scale - pad[1]  # xmin
    detections[:, 2] = detections[:, 2] * scale * model_scale - pad[0]  # ymax
    detections[:, 3] = detections[:, 3] * scale * model_scale - pad[1]  # xmax

    # Keypoints: alternating x, y starting at index 4
    num_kp_coords = detections.shape[1] - 1 - 4  # exclude score col and box
    for k in range(0, num_kp_coords, 2):
        detections[:, 4 + k] = detections[:, 4 + k] * scale * model_scale - pad[1]      # x
        detections[:, 4 + k + 1] = detections[:, 4 + k + 1] * scale * model_scale - pad[0]  # y

    return detections


# --- ROI extraction for hand landmark ---

def detection2roi(detection, config):
    """Convert palm detection to oriented ROI for hand landmark cropping.

    Uses box center and keypoints to determine rotation.

    Args:
        detection: np.ndarray (N, num_coords+1).
        config: Model config dict with kp1, kp2, theta0, dscale, dy.

    Returns:
        (xc, yc, scale, theta) arrays for each detection.
    """
    if len(detection) == 0:
        return np.array([]), np.array([]), np.array([]), np.array([])

    kp1 = config["kp1"]
    kp2 = config["kp2"]
    theta0 = config["theta0"]
    dscale = config["dscale"]
    dy = config["dy"]

    # Box center
    xc = (detection[:, 1] + detection[:, 3]) / 2  # (xmin + xmax) / 2
    yc = (detection[:, 0] + detection[:, 2]) / 2  # (ymin + ymax) / 2

    # Scale from box width (assumes roughly square)
    scale = detection[:, 3] - detection[:, 1]  # xmax - xmin

    # Rotation from keypoints
    kp1_x = detection[:, 4 + kp1 * 2]
    kp1_y = detection[:, 4 + kp1 * 2 + 1]
    kp2_x = detection[:, 4 + kp2 * 2]
    kp2_y = detection[:, 4 + kp2 * 2 + 1]

    theta = np.arctan2(kp1_y - kp2_y, kp1_x - kp2_x) - theta0

    # Apply offsets — shift along the hand axis (rotated coordinate frame)
    xc += -dy * scale * np.sin(theta)
    yc += dy * scale * np.cos(theta)
    scale *= dscale

    return xc, yc, scale, theta


def extract_roi(frame, xc, yc, theta, scale, resolution):
    """Extract oriented ROI crops from frame using affine warp.

    Args:
        frame: Input image (H, W, C).
        xc, yc: ROI centers in image coords.
        theta: Rotation angles.
        scale: ROI sizes.
        resolution: Output crop size (e.g. 224).

    Returns:
        (imgs, affines) where:
        - imgs: np.ndarray (N, resolution, resolution, 3) normalized to [0,1] float32.
        - affines: List of 2x3 inverse affine matrices for denormalization.
    """
    n = len(xc)
    if n == 0:
        return np.zeros((0, resolution, resolution, 3), dtype=np.float32), []

    imgs = np.zeros((n, resolution, resolution, 3), dtype=np.float32)
    affines = []

    for i in range(n):
        # Source points: center and two axis endpoints
        cos_t = np.cos(theta[i])
        sin_t = np.sin(theta[i])
        half = scale[i] / 2.0

        # Points in image space: center, center+right, center+down
        src = np.array([
            [xc[i], yc[i]],
            [xc[i] + half * cos_t, yc[i] + half * sin_t],
            [xc[i] - half * sin_t, yc[i] + half * cos_t],
        ], dtype=np.float32)

        # Destination points in crop space
        dst = np.array([
            [resolution / 2.0, resolution / 2.0],
            [resolution, resolution / 2.0],
            [resolution / 2.0, resolution],
        ], dtype=np.float32)

        # Forward affine: image → crop
        M = cv2.getAffineTransform(src, dst)
        crop = cv2.warpAffine(frame, M, (resolution, resolution))
        imgs[i] = crop.astype(np.float32) / 255.0

        # Inverse affine: crop → image (for denormalizing landmarks)
        M_inv = cv2.getAffineTransform(dst, src)
        affines.append(M_inv)

    return imgs, affines


def denormalize_landmarks(landmarks, affines, resolution):
    """Map landmarks from crop space back to original image coordinates.

    Args:
        landmarks: np.ndarray (N, 21, 3) with coords in [0,1].
        affines: List of 2x3 inverse affine matrices.
        resolution: Crop resolution (e.g. 224).

    Returns:
        np.ndarray (N, 21, 3) with x, y in original image pixels.
    """
    output = landmarks.copy()
    output[:, :, :2] *= resolution  # scale to pixel coords in crop

    for i in range(len(landmarks)):
        M = affines[i]
        xy = output[i, :, :2]  # (21, 2)
        # Apply affine: [x', y'] = M[:, :2] @ [x, y]^T + M[:, 2]
        transformed = (M[:, :2] @ xy.T + M[:, 2:]).T
        output[i, :, :2] = transformed

    return output
