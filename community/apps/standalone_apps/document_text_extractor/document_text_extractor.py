#!/usr/bin/env python3
"""
Document Text Extractor - Batch OCR for document images using PaddleOCR on Hailo-8.

Processes a directory of document images (jpg/png), detects text regions using
PaddleOCR detection model, recognizes text with the OCR recognition model, and
outputs structured JSON with bounding box coordinates and recognized text.
Optionally saves annotated images with text overlay.

Usage:
    python -m hailo_apps.python.standalone_apps.document_text_extractor.document_text_extractor --input /path/to/images/
    python -m hailo_apps.python.standalone_apps.document_text_extractor.document_text_extractor --input /path/to/images/ --save-output --save-json
"""
import os
import sys
import json
import queue
import threading
from functools import partial
from pathlib import Path
import collections
import uuid
from collections import defaultdict

try:
    from hailo_apps.python.core.common.hailo_logger import get_logger, init_logging, level_from_args
except ImportError:
    repo_root = None
    for p in Path(__file__).resolve().parents:
        if (p / "hailo_apps" / "config" / "config_manager.py").exists():
            repo_root = p
            break
    if repo_root is not None:
        sys.path.insert(0, str(repo_root))
    from hailo_apps.python.core.common.hailo_logger import get_logger, init_logging, level_from_args

# Check OCR dependencies before importing OCR-specific modules
def check_ocr_dependencies():
    """
    Check if all required OCR dependencies are installed.
    Exits the program with installation instructions if any dependencies are missing.
    """
    missing_deps = []
    ocr_deps = {
        "paddlepaddle": "paddle",
        "shapely": "shapely",
        "pyclipper": "pyclipper",
    }

    for package_name, import_name in ocr_deps.items():
        try:
            __import__(import_name)
        except ImportError:
            missing_deps.append(package_name)

    if missing_deps:
        print("\n" + "=" * 70)
        print("MISSING REQUIRED DEPENDENCIES")
        print("=" * 70)
        print("\nThe following dependencies are required but not installed:")
        for dep in missing_deps:
            print(f"  - {dep}")
        print("\n" + "-" * 70)
        print("INSTALLATION INSTRUCTIONS:")
        print("-" * 70)
        print("\nTo install all dependencies (recommended):")
        print('  1. Navigate to the repository root directory')
        print('  2. Run: pip install -e ".[ocr]"')
        print("\n" + "=" * 70)
        sys.exit(1)


check_ocr_dependencies()

# Import OCR utilities from the existing paddle_ocr standalone app
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "paddle_ocr"))
from paddle_ocr_utils import (
    det_postprocess,
    resize_with_padding,
    ocr_eval_postprocess,
)

try:
    from hailo_apps.python.core.common.hailo_inference import HailoInfer
    from hailo_apps.python.core.common.toolbox import (
        init_input_source,
        preprocess,
        visualize,
        select_cap_processing_mode,
        FrameRateTracker,
    )
    from hailo_apps.python.core.common.defines import (
        MAX_INPUT_QUEUE_SIZE,
        MAX_OUTPUT_QUEUE_SIZE,
        MAX_ASYNC_INFER_JOBS,
    )
    from hailo_apps.python.core.common.core import configure_multi_model_hef_path, handle_and_resolve_args
    from hailo_apps.python.core.common.parser import get_standalone_parser
except ImportError:
    repo_root = None
    for p in Path(__file__).resolve().parents:
        if (p / "hailo_apps" / "config" / "config_manager.py").exists():
            repo_root = p
            break
    if repo_root is not None:
        sys.path.insert(0, str(repo_root))
    from hailo_apps.python.core.common.hailo_inference import HailoInfer
    from hailo_apps.python.core.common.toolbox import (
        init_input_source,
        preprocess,
        visualize,
        select_cap_processing_mode,
        FrameRateTracker,
    )
    from hailo_apps.python.core.common.defines import (
        MAX_INPUT_QUEUE_SIZE,
        MAX_OUTPUT_QUEUE_SIZE,
        MAX_ASYNC_INFER_JOBS,
    )
    from hailo_apps.python.core.common.core import configure_multi_model_hef_path, handle_and_resolve_args
    from hailo_apps.python.core.common.parser import get_standalone_parser

APP_NAME = Path(__file__).stem
logger = get_logger(__name__)

# Per-frame OCR result accumulator: groups OCR crops by frame ID
ocr_results_dict = defaultdict(lambda: {"frame": None, "results": [], "boxes": [], "count": 0, "image_path": None})
ocr_expected_counts = {}

# Global list to collect all JSON results across images
all_json_results = []
json_results_lock = threading.Lock()


def parse_args():
    """
    Initialize argument parser for the document text extractor.
    Returns:
        argparse.Namespace: Parsed arguments.
    """
    parser = get_standalone_parser()
    parser.description = (
        "Document Text Extractor: Batch OCR for document images using PaddleOCR "
        "detection + recognition on Hailo-8. Outputs structured JSON with text "
        "and bounding box coordinates."
    )
    configure_multi_model_hef_path(parser)

    parser.add_argument(
        "--save-json",
        action="store_true",
        help="Save OCR results as a JSON file in the output directory.",
    )
    parser.add_argument(
        "--confidence-threshold",
        type=float,
        default=0.3,
        help="Minimum confidence threshold for text detection (default: 0.3).",
    )
    parser.add_argument(
        "--use-corrector",
        action="store_true",
        help="Enable text correction after OCR (e.g., for spelling or formatting).",
    )

    args = parser.parse_args()
    return args


def detector_hailo_infer(hailo_inference, input_queue, output_queue, stop_event):
    """
    Detection inference loop: pulls frames from input_queue, runs async inference
    on the text detection model, pushes results to output_queue.
    """
    pending_jobs = collections.deque()

    while True:
        next_batch = input_queue.get()
        if not next_batch:
            break

        if stop_event.is_set():
            continue

        input_batch, preprocessed_batch = next_batch

        inference_callback_fn = partial(
            detector_inference_callback,
            input_batch=input_batch,
            output_queue=output_queue,
        )

        while len(pending_jobs) >= MAX_ASYNC_INFER_JOBS:
            pending_jobs.popleft().wait(10000)

        job = hailo_inference.run(preprocessed_batch, inference_callback_fn)
        pending_jobs.append(job)

    hailo_inference.close()
    output_queue.put(None)


def ocr_hailo_infer(hailo_inference, input_queue, output_queue, stop_event):
    """
    OCR recognition inference loop: pulls cropped text regions from input_queue,
    runs async inference on the recognition model, pushes results to output_queue.
    """
    pending_jobs = collections.deque()

    while True:
        next_batch = input_queue.get()
        if not next_batch:
            break

        if stop_event.is_set():
            continue

        input_batch, preprocessed_batch, extra_context = next_batch

        inference_callback_fn = partial(
            ocr_inference_callback,
            input_batch=input_batch,
            output_queue=output_queue,
            extra_context=extra_context,
        )

        while len(pending_jobs) >= MAX_ASYNC_INFER_JOBS:
            pending_jobs.popleft().wait(10000)

        job = hailo_inference.run(preprocessed_batch, inference_callback_fn)
        pending_jobs.append(job)

    hailo_inference.close()
    output_queue.put(None)


def detector_inference_callback(
    completion_info,
    bindings_list,
    input_batch,
    output_queue,
):
    """Callback triggered after detection inference completes."""
    if completion_info.exception:
        logger.error(f"Inference error: {completion_info.exception}")
    else:
        for i, bindings in enumerate(bindings_list):
            result = bindings.output().get_buffer()
            output_queue.put(([input_batch[i], result]))


def detection_postprocess(
    det_postprocess_queue,
    ocr_input_queue,
    vis_output_queue,
    model_height,
    model_width,
    stop_event,
):
    """
    Worker thread: postprocesses detection results, crops text regions,
    and feeds them to the OCR recognition stage.
    """
    while True:
        item = det_postprocess_queue.get()
        if item is None:
            break

        if stop_event.is_set():
            continue

        input_frame, result = item

        det_pp_res, boxes = det_postprocess(result, input_frame, model_height, model_width)

        frame_id = str(uuid.uuid4())
        ocr_expected_counts[frame_id] = len(det_pp_res)

        if len(det_pp_res) == 0:
            vis_output_queue.put((input_frame, [], []))
            continue

        for idx, cropped in enumerate(det_pp_res):
            resized = resize_with_padding(cropped)
            ocr_input_queue.put((input_frame, [resized], (frame_id, boxes[idx])))


def ocr_inference_callback(
    completion_info,
    bindings_list,
    input_batch,
    output_queue,
    extra_context=None,
):
    """Callback triggered after OCR recognition inference completes."""
    if completion_info.exception:
        logger.error(f"OCR Inference error: {completion_info.exception}")
        return

    result = bindings_list[0].output().get_buffer()
    original_frame = input_batch
    frame_id, box = extra_context
    output_queue.put((frame_id, original_frame, result, box))


def ocr_postprocess(
    ocr_postprocess_queue,
    vis_output_queue,
    stop_event,
):
    """
    Worker thread: accumulates OCR recognition results per frame and emits
    complete results to the visualization queue.
    """
    while True:
        item = ocr_postprocess_queue.get()
        if item is None:
            break

        if stop_event.is_set():
            continue

        frame_id, original_frame, ocr_output, denorm_box = item
        ocr_results_dict[frame_id]["results"].append(ocr_output)
        ocr_results_dict[frame_id]["boxes"].append(denorm_box)
        ocr_results_dict[frame_id]["count"] += 1
        ocr_results_dict[frame_id]["frame"] = original_frame

        expected = ocr_expected_counts.get(frame_id, None)

        if expected is not None and ocr_results_dict[frame_id]["count"] == expected:
            vis_output_queue.put((
                ocr_results_dict[frame_id]["frame"],
                ocr_results_dict[frame_id]["results"],
                ocr_results_dict[frame_id]["boxes"],
            ))
            del ocr_results_dict[frame_id]
            del ocr_expected_counts[frame_id]


def document_result_handler(original_frame, infer_results, boxes, ocr_corrector, save_json):
    """
    Handles inference results: decodes OCR text and collects structured JSON output.

    Args:
        original_frame: The original image frame.
        infer_results: List of raw OCR model outputs.
        boxes: Detected text region bounding boxes.
        ocr_corrector: Optional spell corrector.
        save_json: Whether to accumulate JSON results.

    Returns:
        Annotated image with original + OCR overlay.
    """
    import cv2
    import numpy as np

    texts_with_confidence = []
    for f in infer_results:
        pp_res = ocr_eval_postprocess(f)
        if pp_res:
            texts_with_confidence.append(pp_res[0])
        else:
            texts_with_confidence.append(("", 0.0))

    # Collect JSON results
    if save_json:
        text_regions = []
        for (text, confidence), box in zip(texts_with_confidence, boxes):
            text = text.strip()
            if not text:
                continue
            if ocr_corrector:
                text = ocr_corrector.correct_text(text)
            x, y, w, h = box
            text_regions.append({
                "text": text,
                "confidence": round(confidence, 4),
                "bbox": {
                    "x": int(x),
                    "y": int(y),
                    "width": int(w),
                    "height": int(h),
                },
            })

        with json_results_lock:
            all_json_results.append({
                "image_index": len(all_json_results),
                "text_regions": text_regions,
            })

    # Create annotated visualization
    texts_l = [tc[0] for tc in texts_with_confidence]
    return _visualize_document_ocr(original_frame, boxes, texts_l, ocr_corrector)


def _visualize_document_ocr(image, boxes, labels, ocr_corrector):
    """
    Draws OCR results on a copy of the image: original on the left,
    annotated version with white boxes and recognized text on the right.
    """
    import cv2
    import numpy as np

    left = image.copy()
    right = image.copy()

    for (x, y, w, h), text in zip(boxes, labels):
        if not text.strip():
            continue
        cv2.rectangle(right, (x, y), (x + w, y + h), (255, 255, 255), -1)

    for (x, y, w, h), text in zip(boxes, labels):
        if not text.strip():
            continue
        if ocr_corrector:
            text = ocr_corrector.correct_text(text)

        # Auto-scale font to fit within the bounding box
        font = cv2.FONT_HERSHEY_SIMPLEX
        padding = 4
        inner_w, inner_h = w - 2 * padding, h - 2 * padding
        font_scale = 1.0
        thickness = 1
        while font_scale >= 0.3:
            (text_w, text_h), _ = cv2.getTextSize(text, font, font_scale, thickness)
            if text_w <= inner_w and text_h <= inner_h:
                break
            font_scale -= 0.05

        (text_w, text_h), _ = cv2.getTextSize(text, font, font_scale, thickness)
        text_x = x + padding
        text_y = y + padding + (inner_h + text_h) // 2
        cv2.putText(right, text, (text_x, text_y), font, font_scale,
                    (0, 0, 255), thickness, cv2.LINE_AA)

    return np.hstack([left, right])


def run_inference_pipeline(
    det_net,
    ocr_net,
    input_src,
    batch_size,
    output_dir,
    camera_resolution,
    output_resolution,
    frame_rate,
    save_output=False,
    show_fps=False,
    use_corrector=False,
    no_display=False,
    save_json=False,
    confidence_threshold=0.3,
):
    """
    Run the full document text extraction pipeline with multi-threading.

    Architecture (6 threads):
        preprocess -> det_infer -> det_postprocess -> ocr_infer -> ocr_postprocess -> visualize

    Args:
        det_net: HEF path for the text detection model.
        ocr_net: HEF path for the text recognition model.
        input_src: Input source (image directory path).
        batch_size: Inference batch size.
        output_dir: Directory for saving outputs.
        camera_resolution: Camera resolution setting.
        output_resolution: Output display resolution.
        frame_rate: Target frame rate.
        save_output: Whether to save annotated images.
        show_fps: Whether to display FPS counter.
        use_corrector: Whether to enable spell correction.
        no_display: Run without display window.
        save_json: Whether to save JSON results.
        confidence_threshold: Minimum detection confidence.
    """
    cap, images, input_type = init_input_source(input_src, batch_size, camera_resolution)
    cap_processing_mode = None
    if cap is not None:
        cap_processing_mode = select_cap_processing_mode(input_type, save_output, frame_rate)

    stop_event = threading.Event()

    # Queues for passing data between threads
    det_input_queue = queue.Queue(maxsize=MAX_INPUT_QUEUE_SIZE)
    ocr_input_queue = queue.Queue(maxsize=MAX_INPUT_QUEUE_SIZE)
    det_postprocess_queue = queue.Queue(maxsize=MAX_INPUT_QUEUE_SIZE)
    ocr_postprocess_queue = queue.Queue(maxsize=MAX_INPUT_QUEUE_SIZE)
    vis_output_queue = queue.Queue(maxsize=MAX_OUTPUT_QUEUE_SIZE)

    fps_tracker = None
    if show_fps:
        fps_tracker = FrameRateTracker()

    ocr_corrector = None
    if use_corrector:
        # Import from paddle_ocr utils
        from paddle_ocr_utils import OcrCorrector
        ocr_corrector = OcrCorrector()

    # Post-process callback for visualization
    post_process_callback_fn = partial(
        document_result_handler,
        ocr_corrector=ocr_corrector,
        save_json=save_json,
    )

    # Initialize Hailo inference engines
    detector_hailo_inference = HailoInfer(det_net, batch_size)
    ocr_hailo_inference = HailoInfer(ocr_net, batch_size, priority=1)

    height, width, _ = detector_hailo_inference.get_input_shape()

    # Create threads
    preprocess_thread = threading.Thread(
        target=preprocess,
        args=(images, cap, frame_rate, batch_size, det_input_queue,
              width, height, cap_processing_mode, None, stop_event),
    )
    detection_postprocess_thread = threading.Thread(
        target=detection_postprocess,
        args=(det_postprocess_queue, ocr_input_queue, vis_output_queue,
              height, width, stop_event),
    )
    ocr_postprocess_thread = threading.Thread(
        target=ocr_postprocess,
        args=(ocr_postprocess_queue, vis_output_queue, stop_event),
    )
    vis_postprocess_thread = threading.Thread(
        target=visualize,
        args=(vis_output_queue, cap, save_output, output_dir,
              post_process_callback_fn, fps_tracker, output_resolution,
              frame_rate, True, stop_event, no_display),
    )
    det_thread = threading.Thread(
        target=detector_hailo_infer,
        args=(detector_hailo_inference, det_input_queue, det_postprocess_queue, stop_event),
    )
    ocr_thread = threading.Thread(
        target=ocr_hailo_infer,
        args=(ocr_hailo_inference, ocr_input_queue, ocr_postprocess_queue, stop_event),
    )

    if show_fps:
        fps_tracker.start()

    # Start all threads
    preprocess_thread.start()
    det_thread.start()
    detection_postprocess_thread.start()
    ocr_thread.start()
    ocr_postprocess_thread.start()
    vis_postprocess_thread.start()

    try:
        preprocess_thread.join()
        det_thread.join()
        det_postprocess_queue.put(None)
        detection_postprocess_thread.join()
        ocr_input_queue.put(None)
        ocr_thread.join()
        ocr_postprocess_queue.put(None)
        ocr_postprocess_thread.join()
        vis_output_queue.put(None)
        vis_postprocess_thread.join()

    except KeyboardInterrupt:
        logger.info("Interrupted (Ctrl+C). Shutting down...")
        stop_event.set()

    finally:
        if show_fps:
            logger.info(fps_tracker.frame_rate_summary())

        # Save JSON results if requested
        if save_json:
            json_output_path = os.path.join(output_dir, "ocr_results.json")
            os.makedirs(output_dir, exist_ok=True)
            with open(json_output_path, "w") as f:
                json.dump(
                    {"document_ocr_results": all_json_results},
                    f,
                    indent=2,
                    ensure_ascii=False,
                )
            logger.info(f"Saved JSON results to '{json_output_path}'.")

        logger.success("Processing completed successfully.")
        if save_output or input_type == "images":
            logger.info(f"Saved outputs to '{output_dir}'.")


def main():
    """Main entry point for the document text extractor."""
    args = parse_args()
    init_logging(level=level_from_args(args))
    handle_and_resolve_args(args, APP_NAME, multi_hef=True)
    args.det_net, args.ocr_net = [model for model in args.hef_path]

    run_inference_pipeline(
        args.det_net,
        args.ocr_net,
        args.input,
        args.batch_size,
        args.output_dir,
        args.camera_resolution,
        args.output_resolution,
        args.frame_rate,
        args.save_output,
        args.show_fps,
        args.use_corrector,
        args.no_display,
        args.save_json,
        args.confidence_threshold,
    )


if __name__ == "__main__":
    main()
