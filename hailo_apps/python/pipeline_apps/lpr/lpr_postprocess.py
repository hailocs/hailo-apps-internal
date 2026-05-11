"""LPR postprocessing: CTC decoding for OCR engines and LP crop extraction."""

from pathlib import Path

import cv2
import numpy as np

import hailo

from hailo_apps.python.core.common.defines import RESOURCES_ROOT_PATH_DEFAULT

# ---------------------------------------------------------------------------
# LPRNet character sets (CTC blank is always the last character '-')
# ---------------------------------------------------------------------------
# Original digits-only model (11 classes: 0-9 + blank)
LPRNET_CHARS_11 = "0123456789-"
# International model (37 classes: 0-9, A-Z + blank)
LPRNET_CHARS_37 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-"

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
# Engine-specific OCR confidence thresholds. LPRNet's CTC head outputs over a
# tiny vocabulary (11 or 37 classes) so per-character confidence concentrates
# sharply on the right class — 0.78 is a meaningful "high confidence" cutoff.
# PaddleOCR's head outputs over 97-18,385 classes so confidence is naturally
# diffuse even when the read is correct — the same 0.78 cutoff rejects nearly
# every read. The 0.30 cutoff for Paddle is consistent with the confidences
# observed on the Hailo `ocr.mp4` text demo, where correct decodes land in
# the 0.18-0.37 range.
MIN_OCR_CONFIDENCE_LPRNET = 0.78
MIN_OCR_CONFIDENCE_PADDLE = 0.30
# Back-compat alias for callers that don't know the engine.
MIN_OCR_CONFIDENCE = MIN_OCR_CONFIDENCE_LPRNET

MIN_LENGTH = 4
SUMMARY_INTERVAL = 30  # seconds

# Cap the number of plates kept in the display panel so a long-running session
# doesn't grow the list unbounded. TAPPAS uses MAP_LIMIT=5; we keep more so
# the UI shows useful recent history.
DISPLAY_PLATE_LOG_MAX = 50


def min_ocr_confidence_for(engine: str) -> float:
    """Return the confidence threshold appropriate to the given OCR engine."""
    if engine == "paddle":
        return MIN_OCR_CONFIDENCE_PADDLE
    return MIN_OCR_CONFIDENCE_LPRNET

# Minimum plate crop size in pixels for reliable OCR.
MIN_LP_WIDTH_PIXELS = 20
MIN_LP_HEIGHT_PIXELS = 8

# Maximum plate crop size — a plate covering most of the frame is a false positive.
MAX_LP_WIDTH_PIXELS = 600
MAX_LP_HEIGHT_PIXELS = 200

# ROI zone: only process vehicles whose center falls in the center 1/3 of the frame.
ROI_Y_START = 1.0 / 3.0
ROI_Y_END = 2.0 / 3.0

# Sharpness gate: variance of Laplacian on the central 80% of the LP crop.
# Plates below this variance are rejected as too blurry to OCR reliably.
# Threshold matches the TAPPAS reference (core/hailo/libs/croppers/lpr).
SHARPNESS_MIN_VARIANCE = 100.0
SHARPNESS_INNER_TRIM = 0.1  # trim 10% from each side before measuring

# Minimum vehicle bounding-box area in pixels — vehicles smaller than this
# produce sub-OCR-resolution plate crops even after upscaling. Set lower than
# TAPPAS's reference (40000) because highway footage has more distant vehicles
# than the close-camera scenarios that reference targets.
MIN_VEHICLE_AREA_PX = 10000  # ~100x100

# Output-class counts for the supported PaddleOCR variants.
PADDLE_V3V4_NUM_CLASSES = 97       # legacy "simplified" PaddleOCR (v3/v4 era)
PADDLE_V5_NUM_CLASSES = 18385      # PP-OCRv5 mobile recognition (v2.18 model zoo)
PADDLE_V5_DICT_FILENAME = "ppocrv5_char_dict.npz"


# ---------------------------------------------------------------------------
# CTC decoders
# ---------------------------------------------------------------------------
def ctc_decode_lprnet(output_data):
    """Decode LPRNet output to license plate string.

    Automatically selects the character set based on the output shape:
      - (1, 19, 11) or (19, 11) → digits-only model (LPRNET_CHARS_11)
      - (1, 37, 19) or (1, 19, 37) or (19, 37) → international model (LPRNET_CHARS_37)
    """
    data = np.array(output_data, dtype=np.float32)
    if data.ndim == 3:
        data = data[0]

    # Auto-detect model variant from output shape
    # HEF output may be (19, num_classes) or (num_classes, 19)
    if data.shape == (37, 19):
        data = data.T  # → (19, 37)
    num_classes = data.shape[-1]

    if num_classes == 37:
        lprnet_chars = LPRNET_CHARS_37
    else:
        lprnet_chars = LPRNET_CHARS_11

    blank_idx = len(lprnet_chars) - 1
    data = data.reshape(19, num_classes)

    # Softmax per time-step
    data -= data.max(axis=1, keepdims=True)
    exp_data = np.exp(data)
    probs = exp_data / exp_data.sum(axis=1, keepdims=True)

    indices = np.argmax(probs, axis=1)
    max_probs = probs[np.arange(19), indices]

    chars, confs = [], []
    prev = blank_idx
    for i, idx in enumerate(indices):
        if idx != prev and idx != blank_idx:
            chars.append(lprnet_chars[idx])
            confs.append(float(max_probs[i]))
        prev = idx

    text = "".join(chars)
    conf = float(np.mean(confs)) if confs else 0.0
    return text, conf


_PADDLE_V5_CHARS = None  # lazy-loaded list of 18382 dictionary characters


def _load_paddle_v5_dict():
    """Load the PP-OCRv5 character dictionary from the resources tree.

    Returned list contains the 18,382 dictionary characters in index order
    (no special tokens). The CTC blank, space, and pad live outside the dict
    at fixed positions in the model output.
    """
    global _PADDLE_V5_CHARS
    if _PADDLE_V5_CHARS is not None:
        return _PADDLE_V5_CHARS
    candidates = [
        Path(RESOURCES_ROOT_PATH_DEFAULT) / "models" / arch / PADDLE_V5_DICT_FILENAME
        for arch in ("hailo8", "hailo8l", "hailo10h")
    ]
    for path in candidates:
        if path.exists():
            data = np.load(str(path), allow_pickle=True)
            _PADDLE_V5_CHARS = data["dictionary"].tolist()
            return _PADDLE_V5_CHARS
    return None


def ctc_decode_paddle(output_data):
    """Decode PaddleOCR recognition output to text via greedy CTC.

    Auto-detects the model variant from the class count:
      - 97 classes  → legacy "simplified" PaddleOCR (v3/v4 era), full ASCII
      - 18385 classes → PP-OCRv5 mobile (multi-language); requires dict file
    """
    data = np.array(output_data, dtype=np.float32)
    if data.ndim == 2:
        data = np.expand_dims(data, axis=0)
    num_classes = data.shape[-1]

    if num_classes == PADDLE_V3V4_NUM_CLASSES:
        characters = PADDLE_CHARACTERS
        blank_idx = PADDLE_BLANK_IDX
    elif num_classes == PADDLE_V5_NUM_CLASSES:
        chars_list = _load_paddle_v5_dict()
        if chars_list is None:
            return "", 0.0
        # PP-OCRv5 layout: index 0 = CTC blank, indices 1..18382 = dictionary,
        # remaining indices (18383..) = special tokens we treat as no-output.
        characters = ["", *chars_list]
        characters.extend([""] * (num_classes - len(characters)))
        blank_idx = 0
    else:
        return "", 0.0

    text_index = data.argmax(axis=2)
    text_prob = data.max(axis=2)
    indices = text_index[0]
    probs = text_prob[0]

    chars, confs = [], []
    prev = blank_idx
    for i, idx in enumerate(indices):
        if idx != prev and idx != blank_idx and idx < len(characters):
            ch = characters[idx]
            if ch:
                chars.append(ch)
                confs.append(float(probs[i]))
        prev = idx

    text = "".join(chars)
    conf = float(np.mean(confs)) if confs else 0.0
    return text, conf


def laplacian_variance(crop_bgr):
    """TAPPAS-style sharpness metric: variance of Laplacian on the central 80%.

    Higher values = sharper edges. Plates with motion blur or poor focus
    produce low values. The threshold (~100) was chosen to match the
    `quality_estimation` helper in TAPPAS's LPR cropper.
    """
    if crop_bgr is None or crop_bgr.size == 0:
        return 0.0
    h, w = crop_bgr.shape[:2]
    x_off = int(SHARPNESS_INNER_TRIM * w)
    y_off = int(SHARPNESS_INNER_TRIM * h)
    inner = crop_bgr[y_off:max(y_off + 1, h - y_off), x_off:max(x_off + 1, w - x_off)]
    if inner.size == 0:
        return 0.0
    canon = cv2.resize(inner, (200, 40), interpolation=cv2.INTER_AREA)
    blurred = cv2.GaussianBlur(canon, (3, 3), 0)
    gray = cv2.cvtColor(blurred, cv2.COLOR_BGR2GRAY)
    gray_n = cv2.normalize(gray, None, alpha=255, beta=0, norm_type=cv2.NORM_INF)
    lap = cv2.Laplacian(gray_n, cv2.CV_64F)
    _mean, stddev = cv2.meanStdDev(lap)
    return float(stddev[0][0] ** 2)


def letterbox_resize(img_bgr, target_w, target_h, pad_value=0):
    """Resize keeping aspect ratio with right-padding, matching PaddleOCR rec preprocessing.

    PaddleOCR recognition models expect input that preserves the source
    aspect ratio scaled to the target height, then right-padded with zeros
    to the target width. A plain cv2.resize would distort character widths
    and degrade accuracy.
    """
    if img_bgr is None or img_bgr.size == 0:
        return np.full((target_h, target_w, 3), pad_value, dtype=np.uint8)
    src_h, src_w = img_bgr.shape[:2]
    scale = target_h / max(1, src_h)
    new_w = max(1, min(target_w, int(round(src_w * scale))))
    resized = cv2.resize(img_bgr, (new_w, target_h), interpolation=cv2.INTER_AREA)
    if new_w == target_w:
        return resized
    out = np.full((target_h, target_w, 3), pad_value, dtype=img_bgr.dtype)
    out[:, :new_w] = resized
    return out


# ---------------------------------------------------------------------------
# LP detection helpers
# ---------------------------------------------------------------------------
def detect_lps_gstreamer(detection, frame, frame_w, frame_h):
    """Extract LP sub-detections from GStreamer cropper/hailofilter pipeline.

    LP detections are added by the custom libyolov4_lp_postprocess.so running
    inside the hailocropper element. Works on all architectures (H8/H8L/H10H).

    Crops failing the size or sharpness gates are dropped here so they never
    reach OCR. The sharpness gate runs on the BGR crop using a Laplacian
    variance check (TAPPAS-style).

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
        
        # Sharpness gate: a blurry plate produces garbage OCR even when
        # detection confidence is high.
        lp_crop_bgr = cv2.cvtColor(lp_crop, cv2.COLOR_RGB2BGR)
        if laplacian_variance(lp_crop_bgr) < SHARPNESS_MIN_VARIANCE:
            continue

        results.append((lp_crop, x1, y1, x2, y2))
    return results
