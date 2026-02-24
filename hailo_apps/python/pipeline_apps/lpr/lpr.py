# region imports
import os

os.environ["GST_PLUGIN_FEATURE_RANK"] = "vaapidecodebin:NONE"

import cv2
import numpy as np
import time
import threading

import hailo

from hailo_apps.python.core.common.buffer_utils import (
    get_caps_from_pad,
    get_numpy_from_buffer_efficient,
)
from hailo_apps.python.core.common.hailo_inference import HailoInfer
from hailo_apps.python.core.gstreamer.gstreamer_app import app_callback_class
from hailo_apps.python.pipeline_apps.lpr.lpr_pipeline import GStreamerLPRApp

# endregion imports

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


class user_app_callback_class(app_callback_class):
    def __init__(self, ocr_hef_path, ocr_engine="lprnet"):
        super().__init__()
        self.seen_plates = {}  # track_id -> plate text (OCR >= threshold)
        self.vehicles_seen = set()  # all unique vehicle track IDs seen
        self.last_summary_time = time.time()
        self.ocr_engine = ocr_engine
        self.decode_fn = ctc_decode_lprnet if ocr_engine == "lprnet" else ctc_decode_paddle
        # Plate log for display panel: list of (crop_bgr, text, conf, track_id)
        self.plate_log = []
        self.plate_log_lock = threading.Lock()
        # Initialize OCR inference via HailoRT
        self.ocr_infer = HailoInfer(ocr_hef_path, batch_size=1, output_type="FLOAT32")
        self.ocr_input_shape = self.ocr_infer.get_input_shape()
        self.ocr_h = self.ocr_input_shape[0]
        self.ocr_w = self.ocr_input_shape[1]
        self.ocr_result = None  # stores latest inference result

    def ocr_callback(self, completion_info, bindings_list):
        """Called when OCR async inference completes."""
        if bindings_list:
            buf = bindings_list[0].output().get_buffer()
            if isinstance(buf, dict):
                for key in buf.keys():
                    self.ocr_result = buf[key]
                    break
            elif isinstance(buf, np.ndarray):
                self.ocr_result = buf
            else:
                self.ocr_result = buf


def app_callback(element, buffer, user_data):
    if buffer is None:
        return

    # Print summary every 30 seconds
    now = time.time()
    if now - user_data.last_summary_time >= SUMMARY_INTERVAL:
        total = len(user_data.vehicles_seen)
        recognized = len(user_data.seen_plates)
        print(
            f"--- Summary ({SUMMARY_INTERVAL}s) | "
            f"Vehicles detected: {total} | "
            f"Plates recognized (>{MIN_OCR_CONFIDENCE:.0%}): {recognized} ---"
        )
        user_data.last_summary_time = now

    try:
        roi = hailo.get_roi_from_buffer(buffer)
    except Exception:
        return
    detections = roi.get_objects_typed(hailo.HAILO_DETECTION)

    frame = None
    pad = element.get_static_pad("src")
    frame_format, frame_w, frame_h = get_caps_from_pad(pad)
    if frame_format is not None:
        frame = get_numpy_from_buffer_efficient(
            buffer, frame_format, frame_w, frame_h
        )

    for detection in detections:
        label = detection.get_label()
        if label != "car":
            continue

        track_id = 0
        track = detection.get_objects_typed(hailo.HAILO_UNIQUE_ID)
        if len(track) == 1:
            track_id = track[0].get_id()

        user_data.vehicles_seen.add(track_id)

        # Only process vehicles whose center is inside the ROI zone (center 1/3)
        vbox = detection.get_bbox()
        vehicle_center_y = vbox.ymin() + vbox.height() / 2.0
        if vehicle_center_y < ROI_Y_START or vehicle_center_y > ROI_Y_END:
            continue

        # Skip OCR entirely for vehicles already recognized
        if track_id in user_data.seen_plates:
            continue

        lp_detections = detection.get_objects_typed(hailo.HAILO_DETECTION)
        for lp in lp_detections:
            if lp.get_label() != "license_plate":
                continue

            if frame is None:
                break

            # Compute absolute LP coordinates (LP bbox is relative to the vehicle crop)
            lpbox = lp.get_bbox()
            x1 = max(0, int((vbox.xmin() + lpbox.xmin() * vbox.width()) * frame_w))
            y1 = max(0, int((vbox.ymin() + lpbox.ymin() * vbox.height()) * frame_h))
            x2 = min(frame_w, int((vbox.xmin() + (lpbox.xmin() + lpbox.width()) * vbox.width()) * frame_w))
            y2 = min(frame_h, int((vbox.ymin() + (lpbox.ymin() + lpbox.height()) * vbox.height()) * frame_h))

            crop_w = x2 - x1
            crop_h = y2 - y1
            if crop_w < MIN_LP_WIDTH_PIXELS or crop_h < MIN_LP_HEIGHT_PIXELS:
                continue
            if crop_w > MAX_LP_WIDTH_PIXELS or crop_h > MAX_LP_HEIGHT_PIXELS:
                continue

            # Crop and resize for OCR
            lp_crop = frame[y1:y2, x1:x2]
            lp_resized = cv2.resize(
                lp_crop, (user_data.ocr_w, user_data.ocr_h)
            )

            # Run OCR inference
            user_data.ocr_result = None
            user_data.ocr_infer.run(
                [lp_resized], user_data.ocr_callback
            )
            if user_data.ocr_infer.last_infer_job:
                user_data.ocr_infer.last_infer_job.wait(5000)

            if user_data.ocr_result is None:
                continue

            text, ocr_conf = user_data.decode_fn(user_data.ocr_result)

            if len(text) < MIN_LENGTH:
                continue

            if ocr_conf < MIN_OCR_CONFIDENCE:
                continue

            print(
                f"Vehicle #{track_id:<4d}"
                f" | {text:<10s}"
                f" | conf {ocr_conf:>4.0%}"
                f" | len {len(text)}"
            )

            # Store — first successful OCR per vehicle, skip future frames
            user_data.seen_plates[track_id] = text
            # Add to display log (convert RGB crop to BGR for OpenCV display)
            crop_bgr = cv2.cvtColor(lp_crop, cv2.COLOR_RGB2BGR)
            with user_data.plate_log_lock:
                user_data.plate_log.insert(0, (crop_bgr, text, ocr_conf, track_id))

    # Remove LP sub-detections so hailooverlay only draws vehicle boxes
    for detection in detections:
        for sub in detection.get_objects_typed(hailo.HAILO_DETECTION):
            detection.remove_object(sub)


# ---------------------------------------------------------------------------
# LPR display panel — separate OpenCV window showing recognized plates
# ---------------------------------------------------------------------------
PANEL_WIDTH = 420
ROW_HEIGHT = 60
CROP_DISPLAY_W = 140
CROP_DISPLAY_H = 48
BG_COLOR = (30, 30, 30)
TEXT_COLOR = (220, 220, 220)
HEADER_HEIGHT = 36


def lpr_display_thread(user_data):
    """Runs in a separate thread. Shows a scrollable panel of recognized plates.
    Note: cv2.namedWindow must be called from the main thread before starting this thread."""
    scroll_offset = 0  # 0 = top (newest)

    def on_mouse(event, x, y, flags, param):
        nonlocal scroll_offset
        if event == cv2.EVENT_MOUSEWHEEL:
            if flags > 0:
                scroll_offset = max(0, scroll_offset - 1)
            else:
                scroll_offset += 1

    cv2.setMouseCallback("LPR Panel", on_mouse)

    while user_data.running:
        with user_data.plate_log_lock:
            log_snapshot = list(user_data.plate_log)

        total = len(log_snapshot)
        # Clamp scroll offset
        win_h = 700
        visible_rows = max(1, (win_h - HEADER_HEIGHT) // ROW_HEIGHT)
        max_scroll = max(0, total - visible_rows)
        scroll_offset = min(scroll_offset, max_scroll)

        # Build panel image
        panel = np.full((win_h, PANEL_WIDTH, 3), BG_COLOR, dtype=np.uint8)

        # Header
        cv2.putText(
            panel, f"Recognized Plates: {total}",
            (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, TEXT_COLOR, 2,
        )
        cv2.line(panel, (0, HEADER_HEIGHT - 2), (PANEL_WIDTH, HEADER_HEIGHT - 2), (80, 80, 80), 1)

        # Draw visible rows
        for i in range(visible_rows):
            idx = scroll_offset + i
            if idx >= total:
                break
            crop_bgr, text, conf, track_id = log_snapshot[idx]
            y_top = HEADER_HEIGHT + i * ROW_HEIGHT
            y_bottom = y_top + ROW_HEIGHT

            # Resize crop to fixed display size
            try:
                crop_resized = cv2.resize(crop_bgr, (CROP_DISPLAY_W, CROP_DISPLAY_H))
                panel[y_top + 6 : y_top + 6 + CROP_DISPLAY_H, 4 : 4 + CROP_DISPLAY_W] = crop_resized
            except Exception:
                pass

            # Plate text (bold)
            text_x = CROP_DISPLAY_W + 12
            cv2.putText(
                panel, text,
                (text_x, y_top + 36), cv2.FONT_HERSHEY_SIMPLEX, 0.7, TEXT_COLOR, 2,
            )

            # Row separator
            cv2.line(panel, (0, y_bottom - 1), (PANEL_WIDTH, y_bottom - 1), (60, 60, 60), 1)

        # Scroll indicator
        if total > visible_rows:
            bar_h = max(20, int(win_h * visible_rows / total))
            bar_y = int((win_h - bar_h) * scroll_offset / max_scroll) if max_scroll > 0 else 0
            cv2.rectangle(panel, (PANEL_WIDTH - 8, bar_y), (PANEL_WIDTH - 2, bar_y + bar_h), (100, 100, 100), -1)

        cv2.imshow("LPR Panel", panel)
        key = cv2.waitKey(100) & 0xFF
        if key == 27:  # ESC to close panel
            break
        elif key == ord("k") or key == 82:  # k or Up arrow
            scroll_offset = max(0, scroll_offset - 1)
        elif key == ord("j") or key == 84:  # j or Down arrow
            scroll_offset += 1

    try:
        cv2.destroyWindow("LPR Panel")
    except Exception:
        pass


def main():
    from pathlib import Path

    from hailo_apps.python.core.common.core import (
        configure_multi_model_hef_path,
        get_pipeline_parser,
        handle_list_models_flag,
        resolve_hef_paths,
    )
    from hailo_apps.python.core.common.core import detect_hailo_arch
    from hailo_apps.python.core.common.defines import RESOURCES_ROOT_PATH_DEFAULT
    from hailo_apps.python.pipeline_apps.lpr.lpr_pipeline import LPR_PIPELINE

    parser = get_pipeline_parser()
    configure_multi_model_hef_path(parser)
    parser.add_argument(
        "--ocr-engine",
        type=str,
        choices=["lprnet", "paddle"],
        default="lprnet",
        help="OCR engine: 'lprnet' (digits only, default) or 'paddle' (full charset)",
    )
    handle_list_models_flag(parser, LPR_PIPELINE)
    args, _ = parser.parse_known_args()
    arch = detect_hailo_arch()
    models = resolve_hef_paths(
        hef_paths=args.hef_path if hasattr(args, "hef_path") else None,
        app_name=LPR_PIPELINE,
        arch=arch,
    )

    ocr_engine = args.ocr_engine
    if ocr_engine == "lprnet":
        ocr_hef = models[2].path  # 3rd model from resources_config (lprnet)
    else:
        # PaddleOCR recognition model — resolve from standard resources path
        ocr_hef = str(Path(RESOURCES_ROOT_PATH_DEFAULT) / "models" / arch / "ocr.hef")
        if not Path(ocr_hef).exists():
            print(f"ERROR: PaddleOCR model not found at {ocr_hef}")
            print("Run: sudo ./install.sh to download paddle_ocr resources")
            return

    print(f"LPR using OCR engine: {ocr_engine}")
    user_data = user_app_callback_class(ocr_hef, ocr_engine=ocr_engine)

    # Create display window on main thread to avoid Qt threading warnings
    cv2.namedWindow("LPR Panel", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("LPR Panel", PANEL_WIDTH, 700)

    # Start display panel thread
    panel_thread = threading.Thread(target=lpr_display_thread, args=(user_data,), daemon=True)
    panel_thread.start()

    app = GStreamerLPRApp(app_callback, user_data, parser=parser)
    app.run()


if __name__ == "__main__":
    main()
