import os
from pathlib import Path

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
from hailo_apps.python.core.common.core import (
    configure_multi_model_hef_path,
    detect_hailo_arch,
    get_pipeline_parser,
    handle_list_models_flag,
    resolve_hef_paths,
)
from hailo_apps.python.core.common.defines import RESOURCES_ROOT_PATH_DEFAULT
from hailo_apps.python.core.common.hailo_inference import HailoInfer
from hailo_apps.python.core.gstreamer.gstreamer_app import app_callback_class
from hailo_apps.python.pipeline_apps.lpr.lpr_display import (
    PANEL_WIDTH,
    lpr_display_thread,
)
from hailo_apps.python.pipeline_apps.lpr.lpr_pipeline import GStreamerLPRApp, LPR_PIPELINE
from hailo_apps.python.pipeline_apps.lpr.lpr_postprocess import (
    MIN_LENGTH,
    MIN_OCR_CONFIDENCE,
    ROI_Y_END,
    ROI_Y_START,
    SUMMARY_INTERVAL,
    ctc_decode_lprnet,
    ctc_decode_paddle,
    detect_lps_gstreamer,
)


class user_app_callback_class(app_callback_class):
    def __init__(self, ocr_hef_path, ocr_engine="lprnet", save_crops_dir=None):
        super().__init__()
        self.seen_plates = {}  # track_id -> plate text (OCR >= threshold)
        self.vehicles_seen = set()  # all unique vehicle track IDs seen
        self.last_summary_time = time.time()
        self.ocr_engine = ocr_engine
        self.decode_fn = ctc_decode_lprnet if ocr_engine == "lprnet" else ctc_decode_paddle
        # Plate log for display panel: list of (crop_bgr, text, conf, track_id)
        self.plate_log = []
        self.plate_log_lock = threading.Lock()
        self.save_crops_dir = save_crops_dir
        self.crop_counter = 0

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
    """Called by GStreamer for each frame buffer. Runs LP detection + OCR."""
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

        # Skip entirely for vehicles already recognized
        if track_id in user_data.seen_plates:
            continue

        if frame is None:
            continue

        # LP sub-detections come from GStreamer cropper pipeline (all archs)
        lp_crops = detect_lps_gstreamer(detection, frame, frame_w, frame_h)

        # --- Stage 3: OCR on each detected license plate ---
        for lp_crop, lp_x1, lp_y1, lp_x2, lp_y2 in lp_crops:
            # Convert RGB (from GStreamer) to BGR (model trained on cv2.imread BGR images)
            lp_crop_bgr = cv2.cvtColor(lp_crop, cv2.COLOR_RGB2BGR)

            # Save crop to disk if --save-crops is enabled
            if user_data.save_crops_dir:
                crop_path = os.path.join(
                    user_data.save_crops_dir,
                    f"vehicle_{track_id}_plate_{user_data.crop_counter}.png",
                )
                cv2.imwrite(crop_path, lp_crop_bgr)
                user_data.crop_counter += 1

            lp_resized = cv2.resize(
                lp_crop_bgr, (user_data.ocr_w, user_data.ocr_h)
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


def main():
    parser = get_pipeline_parser()
    configure_multi_model_hef_path(parser)
    parser.add_argument(
        "--ocr-engine",
        type=str,
        choices=["lprnet", "paddle"],
        default="lprnet",
        help="OCR engine: 'lprnet' (digits only, default) or 'paddle' (full charset)",
    )
    parser.add_argument(
        "--save-crops",
        type=str,
        default=None,
        nargs="?",
        const="/tmp/lpr_crops",
        help="Save LP crops to directory (default: /tmp/lpr_crops)",
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

    # Handle --save-crops
    save_crops_dir = args.save_crops
    if save_crops_dir:
        os.makedirs(save_crops_dir, exist_ok=True)
        print(f"Saving LP crops to: {save_crops_dir}")

    # LP detection runs in the GStreamer pipeline on all architectures
    # via our custom libyolov4_lp_postprocess.so.
    user_data = user_app_callback_class(
        ocr_hef, ocr_engine=ocr_engine, save_crops_dir=save_crops_dir
    )

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
