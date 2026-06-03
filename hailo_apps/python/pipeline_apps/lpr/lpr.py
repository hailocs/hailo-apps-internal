"""Hailo LPR — License Plate Recognition app.

Two orthogonal choices control the pipeline:

  --backbone : which detector finds license plates in the frame
  --ocr      : which network reads the characters off each plate crop

Backbones
=========

  yolov8n        A single yolov8n_384x640 (4 classes: person/vehicle/face/
                 license_plate) run once per full frame. We filter for the
                 license_plate class and crop directly. One inference per
                 frame, no vehicle dependency.

  yolov8n_tiled  Same network, but each video frame is split into 5 tiles
                 (4 quadrants from a 2x2 grid + 1 full frame) which are
                 inferred together (batch=5) and aggregated. Each plate
                 lands in a quadrant at roughly 2x the pixels per plate
                 compared to the full-frame view, recovering small plates
                 that a single 384x640 inference would miss.
                 Recommended for FHD (1920x1080) and 4K input; the win
                 shrinks below ~720p where the full-frame inference
                 already has enough pixels per plate.

OCR engines
===========

  lprnet         Compact CTC head, 37 classes (digits + A–Z + CTC blank),
                 locally retrained on a Latin-alphanumeric plate corpus.
                 HEF resolves from a separate file (`lprnet_intl.hef`) so
                 it doesn't conflict with the bundled Hailo `lprnet.hef`
                 (11-class digits-only) sitting at the same install path.
                 See pipeline_apps/lpr/README.md for training / accuracy
                 details. Lower confidence threshold (0.50) than the old
                 bundled 11-class HEF (0.78) because 37-class softmax is
                 spread over a wider vocab.

  paddle         paddle_ocr_v5_mobile_recognition. Large multilingual
                 vocabulary (18,385 classes). Reads non-Latin scripts and
                 handles formatting (hyphens, dots) more gracefully. Slower
                 per-character confidence and a lower exact-match rate on
                 ASCII-only plates than a plate-specialised model. Use this
                 when you need multilingual support or richer formatting.

Run examples
============

  # Recommended for HD+ video: tiled yolov8n + retrained Latin LPRNet
  hailo-lpr --backbone yolov8n_tiled --ocr lprnet --input clip.mp4

  # Default: full-frame yolov8n + retrained Latin LPRNet
  hailo-lpr --ocr lprnet --input clip.mp4

  # Multilingual OCR
  hailo-lpr --backbone yolov8n_tiled --ocr paddle --input clip.mp4
"""

import os
import threading
import time
from pathlib import Path

_existing_gst_rank = os.environ.get("GST_PLUGIN_FEATURE_RANK", "")
_lpr_gst_rank = "vaapidecodebin:NONE"
os.environ["GST_PLUGIN_FEATURE_RANK"] = (
    f"{_existing_gst_rank},{_lpr_gst_rank}" if _existing_gst_rank else _lpr_gst_rank
)

import cv2
import numpy as np

import hailo

from hailo_apps.python.core.common.buffer_utils import (
    get_caps_from_pad,
    get_numpy_from_buffer_efficient,
)
from hailo_apps.python.core.common.core import (
    detect_hailo_arch,
    get_pipeline_parser,
    handle_list_models_flag,
)
from hailo_apps.python.core.common.defines import RESOURCES_ROOT_PATH_DEFAULT
from hailo_apps.python.core.common.hailo_inference import HailoInfer
from hailo_apps.python.core.gstreamer.gstreamer_app import app_callback_class
from hailo_apps.python.pipeline_apps.lpr.lpr_display import (
    PANEL_WIDTH,
    lpr_display_thread,
)
from hailo_apps.python.pipeline_apps.lpr.lpr_pipeline import (
    BACKBONE_YOLOV8N,
    BACKBONES,
    GStreamerLPRApp,
    LPR_PIPELINE,
)
from hailo_apps.python.pipeline_apps.lpr.lpr_postprocess import (
    DISPLAY_PLATE_LOG_MAX,
    MAX_LP_HEIGHT_PIXELS,
    MAX_LP_WIDTH_PIXELS,
    MIN_LENGTH,
    MIN_LP_HEIGHT_PIXELS,
    MIN_LP_WIDTH_PIXELS,
    SHARPNESS_MIN_VARIANCE,
    SUMMARY_INTERVAL,
    ctc_decode_lprnet,
    ctc_decode_paddle,
    laplacian_variance,
    letterbox_resize,
    min_ocr_confidence_for,
)

# Label used by the yolov8n 4-class detector for the license-plate class
# (matches resources/json/hailo_4_classes.json).
LP_LABEL = "license_plate"


class user_app_callback_class(app_callback_class):
    def __init__(self, ocr_hef_path, ocr="lprnet",
                 backbone=BACKBONE_YOLOV8N,
                 save_ocr_inputs_dir=None):
        super().__init__()
        self.backbone = backbone
        self.ocr = ocr
        self.seen_plates = {}     # track_id → plate text (after OCR gate)
        self.vehicles_seen = set()
        self.last_summary_time = time.time()
        self.decode_fn = ctc_decode_lprnet if ocr == "lprnet" else ctc_decode_paddle
        self.min_ocr_confidence = min_ocr_confidence_for(ocr)
        # Plate log for display panel: list of (crop_bgr, text, conf, track_id)
        self.plate_log = []
        self.plate_log_lock = threading.Lock()
        # Diagnostic: dump every array fed to the OCR network (post-letterbox /
        # post-resize) plus the decoded text + confidence, for visual review.
        self.save_ocr_inputs_dir = save_ocr_inputs_dir
        self.ocr_input_counter = 0

        # Initialize OCR inference via HailoRT
        self.ocr_infer = HailoInfer(ocr_hef_path, batch_size=1, output_type="FLOAT32")
        self.ocr_input_shape = self.ocr_infer.get_input_shape()
        self.ocr_h = self.ocr_input_shape[0]
        self.ocr_w = self.ocr_input_shape[1]
        self.ocr_result = None

    def ocr_callback(self, completion_info, bindings_list):
        """Called when OCR async inference completes."""
        if bindings_list:
            buf = bindings_list[0].output().get_buffer()
            if isinstance(buf, dict):
                self.ocr_result = next(iter(buf.values()))
            elif isinstance(buf, np.ndarray):
                self.ocr_result = buf
            else:
                self.ocr_result = buf


def _run_ocr_on_crop(user_data, lp_crop_rgb, track_id):
    """Resize → OCR → length/conf gate → print + log. Returns True if accepted.

    Takes an RGB plate crop in source-frame pixels.
    """
    lp_crop_bgr = cv2.cvtColor(lp_crop_rgb, cv2.COLOR_RGB2BGR)

    # Engine-aware preprocessing.
    # LPRNet is trained on plates stretched to 300x75; the deformation is part
    # of its expected input distribution. PaddleOCR rec is trained with
    # aspect-ratio-preserving resize + right-padding to the target width.
    if user_data.ocr == "paddle":
        lp_resized = letterbox_resize(
            lp_crop_bgr, user_data.ocr_w, user_data.ocr_h
        )
    else:
        lp_resized = cv2.resize(
            lp_crop_bgr, (user_data.ocr_w, user_data.ocr_h),
            interpolation=cv2.INTER_AREA,
        )

    user_data.ocr_result = None
    user_data.ocr_infer.run([lp_resized], user_data.ocr_callback)
    if user_data.ocr_infer.last_infer_job:
        user_data.ocr_infer.last_infer_job.wait(5000)
    if user_data.ocr_result is None:
        return False

    text, ocr_conf = user_data.decode_fn(user_data.ocr_result)

    if user_data.save_ocr_inputs_dir:
        safe_text = "".join(c if c.isalnum() else "_" for c in text)[:24] or "empty"
        fname = (
            f"{user_data.ocr_input_counter:06d}_t{track_id:04d}_"
            f"c{int(round(ocr_conf*100)):03d}_{safe_text}.png"
        )
        cv2.imwrite(os.path.join(user_data.save_ocr_inputs_dir, fname), lp_resized)
        user_data.ocr_input_counter += 1

    if len(text) < MIN_LENGTH:
        return False
    if ocr_conf < user_data.min_ocr_confidence:
        return False

    print(
        f"Vehicle #{track_id:<4d}"
        f" | {text:<10s}"
        f" | conf {ocr_conf:>4.0%}"
        f" | len {len(text)}"
    )

    user_data.seen_plates[track_id] = text
    with user_data.plate_log_lock:
        user_data.plate_log.insert(0, (lp_crop_bgr, text, ocr_conf, track_id))
        if len(user_data.plate_log) > DISPLAY_PLATE_LOG_MAX:
            del user_data.plate_log[DISPLAY_PLATE_LOG_MAX:]
    return True


def app_callback(element, buffer, user_data):
    """Single entry point called by GStreamer for every output buffer.

    Iterates top-level detections, keeps those labelled license_plate, crops
    from the source frame, and dispatches each crop to OCR.
    """
    if buffer is None:
        return

    now = time.time()
    if now - user_data.last_summary_time >= SUMMARY_INTERVAL:
        total = len(user_data.vehicles_seen)
        recognized = len(user_data.seen_plates)
        # `vehicles_seen` holds plate track IDs; the label in the summary
        # line stays "Vehicles detected" for backward compat with
        # test_lpr_end_to_end.py parsing.
        print(
            f"--- Summary ({SUMMARY_INTERVAL}s) | "
            f"Vehicles detected: {total} | "
            f"Plates recognized (>{user_data.min_ocr_confidence:.0%}): {recognized} ---"
        )
        user_data.last_summary_time = now

    try:
        roi = hailo.get_roi_from_buffer(buffer)
    except Exception:
        return

    pad = element.get_static_pad("src")
    frame_format, frame_w, frame_h = get_caps_from_pad(pad)
    frame = None
    if frame_format is not None:
        frame = get_numpy_from_buffer_efficient(
            buffer, frame_format, frame_w, frame_h
        )

    detections = roi.get_objects_typed(hailo.HAILO_DETECTION)
    for det in detections:
        if det.get_label() != LP_LABEL:
            continue

        track_id = 0
        track = det.get_objects_typed(hailo.HAILO_UNIQUE_ID)
        if len(track) == 1:
            track_id = track[0].get_id()
        user_data.vehicles_seen.add(track_id)

        if track_id in user_data.seen_plates:
            continue
        if frame is None or frame_w is None or frame_h is None:
            continue

        bbox = det.get_bbox()
        x1 = max(0, int(bbox.xmin() * frame_w))
        y1 = max(0, int(bbox.ymin() * frame_h))
        x2 = min(frame_w, int((bbox.xmin() + bbox.width()) * frame_w))
        y2 = min(frame_h, int((bbox.ymin() + bbox.height()) * frame_h))
        crop_w, crop_h = x2 - x1, y2 - y1
        if crop_w < MIN_LP_WIDTH_PIXELS or crop_h < MIN_LP_HEIGHT_PIXELS:
            continue
        if crop_w > MAX_LP_WIDTH_PIXELS or crop_h > MAX_LP_HEIGHT_PIXELS:
            continue

        lp_crop = frame[y1:y2, x1:x2]
        if lp_crop.size == 0:
            continue
        if laplacian_variance(cv2.cvtColor(lp_crop, cv2.COLOR_RGB2BGR)) \
                < SHARPNESS_MIN_VARIANCE:
            continue

        _run_ocr_on_crop(user_data, lp_crop, track_id)


def main():
    parser = get_pipeline_parser()
    parser.add_argument(
        "--backbone", type=str, choices=BACKBONES, default=BACKBONE_YOLOV8N,
        help=(
            "Detector backbone (default: yolov8n). "
            "'yolov8n' = single yolov8n_384x640 with direct license_plate class. "
            "'yolov8n_tiled' = same network with 5-tile preprocessing "
            "(4 quadrants + full frame); recommended for FHD/4K input."
        ),
    )
    parser.add_argument(
        "--ocr", type=str, choices=["lprnet", "paddle"], default="lprnet",
        help=(
            "OCR engine (default: lprnet). "
            "'lprnet' = locally-retrained 37-class Latin alphanumeric LPRNet "
            "(file: lprnet_intl.hef — separate from the bundled Hailo lprnet.hef). "
            "'paddle' = paddle_ocr_v5 multilingual, broader script support."
        ),
    )
    parser.add_argument(
        "--save-ocr-inputs", type=str, default=None, nargs="?",
        const="/tmp/lpr_ocr_inputs",
        help="Save exact OCR-network inputs to directory "
             "(default: /tmp/lpr_ocr_inputs). Filenames encode track id, "
             "OCR confidence, and decoded text — useful for visually "
             "verifying preprocessing on failure cases.",
    )
    handle_list_models_flag(parser, LPR_PIPELINE)
    args, _ = parser.parse_known_args()

    arch = detect_hailo_arch()

    # Resolve OCR HEF (orthogonal to backbone). Both engines live at
    # standard install-time paths under <resources>/models/<arch>/.
    #
    # - lprnet  → lprnet_intl.hef (the retrained 37-class build; distinct
    #             filename so it never collides with the bundled Hailo
    #             lprnet.hef).
    # - paddle  → paddle_ocr_v5.hef (the v5 build the LPR app's `install.sh`
    #             pulls from hefs/<arch>/LPR/ocr.hef). If that file isn't
    #             present (e.g. older install or paddle_ocr-only install
    #             that only laid down the legacy v3/v4 ocr.hef), fall back
    #             to the legacy filename with a warning — postprocess
    #             auto-detects v3/v4 vs v5 by class count.
    models_dir = Path(RESOURCES_ROOT_PATH_DEFAULT) / "models" / arch
    if args.ocr == "lprnet":
        ocr_hef = str(models_dir / "lprnet_intl.hef")
    else:  # paddle
        v5 = models_dir / "paddle_ocr_v5.hef"
        legacy = models_dir / "ocr.hef"
        if v5.exists():
            ocr_hef = str(v5)
        elif legacy.exists():
            ocr_hef = str(legacy)
            print(
                "WARNING: paddle_ocr_v5.hef not found; falling back to legacy "
                f"{legacy.name} (v3/v4). Run `sudo ./install.sh` to fetch the "
                "v5 build for better accuracy."
            )
        else:
            ocr_hef = str(v5)  # use v5 path in the error so the install hint is correct
    if not Path(ocr_hef).exists():
        print(f"ERROR: OCR HEF not found at {ocr_hef}")
        print("Run: sudo ./install.sh to download LPR + paddle_ocr resources")
        return

    print(f"LPR backbone: {args.backbone}   OCR: {args.ocr}")
    print(f"OCR HEF: {ocr_hef}")

    save_ocr_inputs_dir = args.save_ocr_inputs
    if save_ocr_inputs_dir:
        os.makedirs(save_ocr_inputs_dir, exist_ok=True)
        print(f"Saving OCR-network inputs to: {save_ocr_inputs_dir}")

    user_data = user_app_callback_class(
        ocr_hef, ocr=args.ocr, backbone=args.backbone,
        save_ocr_inputs_dir=save_ocr_inputs_dir,
    )

    cv2.namedWindow("LPR Panel", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("LPR Panel", PANEL_WIDTH, 700)
    panel_thread = threading.Thread(
        target=lpr_display_thread, args=(user_data,), daemon=True)
    panel_thread.start()

    app = GStreamerLPRApp(app_callback, user_data, parser=parser,
                          backbone=args.backbone)
    app.run()


if __name__ == "__main__":
    main()
