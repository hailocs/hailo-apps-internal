"""LPR postprocessing: CTC decoding for OCR engines and LP crop extraction."""

import cv2
import numpy as np

import hailo

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
# LP detection helpers
# ---------------------------------------------------------------------------
def detect_lps_gstreamer(detection, frame, frame_w, frame_h):
    """Extract LP sub-detections from GStreamer cropper/hailofilter pipeline.

    LP detections are added by the custom libyolov4_lp_postprocess.so running
    inside the hailocropper element. Works on all architectures (H8/H8L/H10H).

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
