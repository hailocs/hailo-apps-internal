#!/usr/bin/env python3

import os
import sys
import uuid
import queue
import threading
import collections

from functools import partial
from pathlib import Path
from collections import defaultdict


# Ensure repository root is available in sys.path
repo_root = None
for p in Path(__file__).resolve().parents:
    if (p / "hailo_apps" / "config" / "config_manager.py").exists():
        repo_root = p
        break

if repo_root is not None:
    sys.path.insert(0, str(repo_root))


# Dependency validation
def check_ocr_dependencies():
    """
    Validate that all required OCR dependencies are installed.

    If one or more dependencies are missing, print clear installation
    instructions and terminate the application.
    """
    missing_deps = []

    # Mapping between pip package names and Python import names
    ocr_dependencies = {
        "paddlepaddle": "paddle",
        "shapely": "shapely",
        "pyclipper": "pyclipper",
        "symspellpy": "symspellpy",
    }

    for package_name, import_name in ocr_dependencies.items():
        try:
            __import__(import_name)
        except ImportError:
            missing_deps.append(package_name)

    if missing_deps:
        print("\n" + "=" * 70)
        print("ERROR: Missing required OCR dependencies")
        print("=" * 70)
        print("\nThe following packages are required but not installed:")
        for dep in missing_deps:
            print(f"  - {dep}")

        print("\n" + "-" * 70)
        print("Installation instructions")
        print("-" * 70)
        print("\nRecommended installation:")
        print("  1. Navigate to the repository root directory")
        print('  2. Run: pip install -e ".[ocr]"')
        print("\n" + "=" * 70)

        sys.exit(1)


# Validate dependencies before importing OCR-specific modules
check_ocr_dependencies()


from paddle_ocr_utils import (
    det_postprocess,
    resize_with_padding,
    inference_result_handler,
    OcrCorrector,
    map_bbox_to_original_image,
)

from hailo_apps.python.core.common.hailo_logger import (
    get_logger,
    init_logging,
    level_from_args,
)
from hailo_apps.python.core.common.hailo_inference import HailoInfer
from hailo_apps.python.core.common.toolbox import (
    InputContext,
    VisualizationSettings,
    init_input_source,
    preprocess,
    visualize,
    FrameRateTracker,
    stop_after_timeout
)
from hailo_apps.python.core.common.defines import (
    MAX_INPUT_QUEUE_SIZE,
    MAX_OUTPUT_QUEUE_SIZE,
    MAX_ASYNC_INFER_JOBS,
)
from hailo_apps.python.core.common.core import (
    configure_multi_model_hef_path,
    handle_and_resolve_args,
)
from hailo_apps.python.core.common.parser import get_standalone_parser

APP_NAME = Path(__file__).stem
logger = get_logger(__name__)
# A dictionary that accumulates all OCR crops and their results for a single frame.
ocr_results_dict = defaultdict(lambda: {"frame": None, "results": [], "boxes": [], "count": 0})
ocr_expected_counts = {}


def parse_args():
    """
    Initialize argument parser for the script.
    Returns:
        argparse.Namespace: Parsed arguments.
    """
    parser = get_standalone_parser()
    parser.description = "Paddle OCR Example with detection + OCR networks."
    configure_multi_model_hef_path(parser)

    parser.add_argument(
        "--use-corrector",
        action="store_true",
        help="Enable text correction after OCR (e.g., for spelling or formatting).",
    )

    args = parser.parse_args()
    return args


def detector_hailo_infer(hailo_inference, input_queue, output_queue, stop_event):
    """
    Main inference loop that pulls data from the input queue, runs asynchronous
    inference, and pushes results to the output queue.

    Each item in the input queue is expected to be a tuple:
        (input_batch, preprocessed_batch)
        - input_batch: Original frames (used for visualization or tracking)
        - preprocessed_batch: Model-ready frames (e.g., resized, normalized)

    Args:
        hailo_inference (HailoInfer): The inference engine to run model predictions.
        input_queue (queue.Queue): Provides (input_batch, preprocessed_batch) tuples.
        output_queue (queue.Queue): Collects (input_frame, result) tuples for visualization.

    Returns:
        None
    """
    # Limit number of concurrent async inferences
    pending_jobs = collections.deque()

    while True:
        next_batch = input_queue.get()
        if not next_batch:
            break  # Stop signal received

        if stop_event.is_set():
            continue  # Skip processing if stop signal is set

        input_batch, preprocessed_batch = next_batch

        # Prepare the callback for handling the inference result
        inference_callback_fn = partial(
            detector_inference_callback,
            input_batch=input_batch,
            output_queue=output_queue
        )


        while len(pending_jobs) >= MAX_ASYNC_INFER_JOBS:
            pending_jobs.popleft().wait(10000)

        # Run async inference
        job = hailo_inference.run(preprocessed_batch, inference_callback_fn)
        pending_jobs.append(job)

    # Release resources and context
    hailo_inference.close()
    output_queue.put(None)


def ocr_hailo_infer(hailo_inference, input_queue, output_queue, stop_event):
    """
    Main inference loop that pulls data from the input queue, runs asynchronous
    inference, and pushes results to the output queue.

    Each item in the input queue is expected to be a tuple:
        (input_batch, preprocessed_batch)
        - input_batch: Original frames (used for visualization or tracking)
        - preprocessed_batch: Model-ready frames (e.g., resized, normalized)

    Args:
        hailo_inference (HailoInfer): The inference engine to run model predictions.
        input_queue (queue.Queue): Provides (input_batch, preprocessed_batch) tuples.
        output_queue (queue.Queue): Collects (input_frame, result) tuples for visualization.

    Returns:
        None
    """
    # Limit number of concurrent async inferences
    pending_jobs = collections.deque()

    while True:
        next_batch = input_queue.get()
        if not next_batch:
            break  # Stop signal received

        if stop_event.is_set():
            continue  # Skip processing if stop signal is set

        input_batch, preprocessed_batch, extra_context = next_batch

        # Prepare the callback for handling the inference result
        inference_callback_fn = partial(
            ocr_inference_callback,
            input_batch=input_batch,
            output_queue=output_queue,
            extra_context=extra_context
        )

        while len(pending_jobs) >= MAX_ASYNC_INFER_JOBS:
            pending_jobs.popleft().wait(10000)

        # Run async inference
        job = hailo_inference.run(preprocessed_batch, inference_callback_fn)
        pending_jobs.append(job)

    # Release resources and context
    hailo_inference.close()
    output_queue.put(None)


def run_inference_pipeline(
    det_net,
    ocr_net,
    input_context: InputContext,
    visualization_settings: VisualizationSettings,
    show_fps: bool = False,
    time_to_run: int | None = None,
    use_corrector=False
) -> None:
    """
    Run full detector + OCR inference pipeline with multi-threading and streaming.

    Args:
        det_net: Path to the detection model (HEF).
        ocr_net: Path to the OCR model (HEF).
        input_context (InputContext): Configured input source and runtime metadata
            (camera, video, or images).
        visualization_settings (VisualizationSettings): Visualization and output
            configuration (display, saving, output directory, etc.).
        show_fps (bool, optional): Enable FPS tracking and reporting. Defaults to False.
        time_to_run (int | None, optional): Optional timeout in seconds. If set,
            the pipeline stops automatically after the given duration.
        use_corrector (bool, optional): Enable OCR text correction post-processing.
            Defaults to False.

    Returns:
        None
    """

    stop_event = threading.Event()

    # Queues for passing data between threads
    det_input_queue = queue.Queue(maxsize=MAX_INPUT_QUEUE_SIZE)
    ocr_input_queue = queue.Queue(maxsize=MAX_INPUT_QUEUE_SIZE)

    det_postprocess_queue = queue.Queue(maxsize=MAX_INPUT_QUEUE_SIZE)
    ocr_postprocess_queue = queue.Queue(maxsize=MAX_INPUT_QUEUE_SIZE)

    vis_output_queue = queue.Queue(maxsize=MAX_OUTPUT_QUEUE_SIZE)

    fps_tracker=None
    if show_fps:
        fps_tracker = FrameRateTracker()

    ocr_corrector = None
    if use_corrector:
        ocr_corrector = OcrCorrector()


    ####### CALLBACKS ########

    # Final visualization callback function with optional correction
    post_process_callback_fn = partial(
        inference_result_handler,
        ocr_corrector=ocr_corrector
    )

    ###### THREADS ########

    # Start detector with async Hailo inference
    detector_hailo_inference = HailoInfer(det_net, input_context.batch_size)

    # Start ocr with async Hailo inference
    ocr_hailo_inference = HailoInfer(ocr_net, input_context.batch_size, priority=1)

    height, width, _ = detector_hailo_inference.get_input_shape()

    # Input preprocessing
    preprocess_thread = threading.Thread(
        target=preprocess,
        args=(
            input_context,
            det_input_queue,
            width,
            height,
            None,
            stop_event,
        ),
        name="preprocess-thread",
    )

    # Detection postprocess
    detection_postprocess_thread = threading.Thread(
        target=detection_postprocess,
        args=(
            det_postprocess_queue,
            ocr_input_queue,
            vis_output_queue,
            height,
            width,
            stop_event,
        ),
        name="detection-postprocess-thread",
    )

    # OCR postprocess
    ocr_postprocess_thread = threading.Thread(
        target=ocr_postprocess,
        args=(ocr_postprocess_queue, vis_output_queue, stop_event),
        name="ocr-postprocess-thread",
    )

    # Detection inference
    det_thread = threading.Thread(
        target=detector_hailo_infer,
        args=(
            detector_hailo_inference,
            det_input_queue,
            det_postprocess_queue,
            stop_event,
        ),
        name="detector-infer-thread",
    )

    # OCR inference
    ocr_thread = threading.Thread(
        target=ocr_hailo_infer,
        args=(
            ocr_hailo_inference,
            ocr_input_queue,
            ocr_postprocess_queue,
            stop_event,
        ),
        name="ocr-infer-thread",
    )

    if show_fps:
        fps_tracker.start()

    if time_to_run is not None:
        timer_thread = threading.Thread(
            target=stop_after_timeout,
            args=(stop_event, time_to_run),
            name="timer-thread",
            daemon=True,
        )
        timer_thread.start()

    # Start worker threads
    preprocess_thread.start()
    det_thread.start()
    detection_postprocess_thread.start()
    ocr_thread.start()
    ocr_postprocess_thread.start()

    try:
        # Visualization runs in the main thread
        visualize(
            input_context,
            visualization_settings,
            vis_output_queue,
            post_process_callback_fn,
            fps_tracker,
            stop_event,
        )
    finally:
        stop_event.set()
        preprocess_thread.join()
        det_thread.join()
        detection_postprocess_thread.join()
        ocr_thread.join()
        ocr_postprocess_thread.join()

    if show_fps:
        logger.info(fps_tracker.frame_rate_summary())

    logger.success("Processing completed successfully.")

    if visualization_settings.save_stream_output or input_context.has_images:
        logger.info(f"Saved outputs to '{visualization_settings.output_dir}'.")


def detector_inference_callback(
    completion_info,
    bindings_list: list,
    input_batch: list,
    output_queue,
) -> None:
    """
    Callback triggered after detection inference completes.

    Args:
        completion_info: Info about whether inference succeeded or failed.
        bindings_list (list): Output buffer objects for each input.
        input_batch (list): input frames.
        output_queue (queue.Queue): Queue to pass cropped regions to the OCR pipeline.
    Returns:
        None
    """
    if completion_info.exception:
        logger.error(f'Inference error: {completion_info.exception}')
    else:
        for i, bindings in enumerate(bindings_list):
            result = bindings.output().get_buffer()
            output_queue.put(([input_batch[i], result]))



def detection_postprocess(
    det_postprocess_queue: queue.Queue,
    ocr_input_queue: queue.Queue,
    vis_output_queue: queue.Queue,
    model_height,
    model_width,
    stop_event
) -> None:
    """
    Worker thread to handle postprocessing of detection results.

    Args:
        det_postprocess_queue (queue.Queue): Queue containing tuples of (input_frame, preprocessed_img, result).
        ocr_input_queue (queue.Queue): Queue to send cropped and resized regions along with metadata to OCR stage.
        vis_output_queue (queue.Queue): Queue to send empty OCR results directly to visualization if no detections.
        model_height (int): The height of the model input used for scaling detection boxes.
        model_width (int): The width of the model input used for scaling detection boxes.

    Returns:
        None
    """
    while True:
        item = det_postprocess_queue.get()
        if item is None:
            break  # Shutdown signal

        if stop_event.is_set():
            continue  # Skip processing if stop signal is set

        input_frame, result = item

        det_pp_res, boxes = det_postprocess(result, input_frame, model_height, model_width)

        frame_id = str(uuid.uuid4())
        # Register how many OCR crops are expected from this frame
        ocr_expected_counts[frame_id] = len(det_pp_res)

        # If no text regions were detected, skip OCR and go straight to visualization
        if len(det_pp_res) == 0:
            vis_output_queue.put((input_frame, [], []))
            continue

        # For each detected text region:
        for idx, cropped in enumerate(det_pp_res):
            # Resize the cropped region to match OCR input size (with padding)
            resized = resize_with_padding(cropped)
            # Push one OCR task to the OCR input queue
            ocr_input_queue.put((input_frame, [resized], (frame_id, boxes[idx])))

    ocr_input_queue.put(None)



def ocr_inference_callback(
    completion_info,
    bindings_list: list,
    input_batch: list,
    output_queue: queue.Queue,
    extra_context=None
) -> None:
    """
    Callback triggered after OCR inference completes. Extracts the result, attaches metadata,
    and pushes it to the OCR postprocessing queue.

    Args:
        completion_info: Info about whether inference succeeded or failed.
        bindings_list (list): Output buffer objects from the OCR model.
        input_batch (list): input frame (only one image per batch).
        output_queue (queue.Queue): Queue used to send the OCR results and metadata to the postprocessing stage.
        extra_context (tuple, optional): A tuple of (frame_id, [box]), where `box` is the denormalized detection
                                         bounding box from the detector. Used to group OCR results by frame.

    Returns:
        None
    """
    if completion_info.exception:
        logger.error(f"OCR Inference error: {completion_info.exception}")
        return

    # Handle the single result
    result = bindings_list[0].output().get_buffer()

    # Unpack inputs
    original_frame = input_batch
    frame_id, box = extra_context
    output_queue.put((frame_id, original_frame, result, box))


def ocr_postprocess(
    ocr_postprocess_queue: queue.Queue,
    vis_output_queue: queue.Queue,
    stop_event: threading.Event
) -> None:
    """
    Worker thread to handle postprocessing of OCR model results.

    Args:
        ocr_postprocess_queue (queue.Queue): Queue containing tuples of (frame_id, input_frame, ocr_output, denorm_box).
        vis_output_queue (queue.Queue): Queue to pass the final results to visualization.

    Returns:
        None
    """
    while True:

        item = ocr_postprocess_queue.get()
        if item is None:
            break  # Shutdown signal

        if stop_event.is_set():
            continue  # Skip processing if stop signal is set

        frame_id, original_frame, ocr_output, denorm_box = item
        ocr_results_dict[frame_id]["results"].append(ocr_output)
        ocr_results_dict[frame_id]["boxes"].append(denorm_box)
        ocr_results_dict[frame_id]["count"] += 1
        ocr_results_dict[frame_id]["frame"] = original_frame

        expected = ocr_expected_counts.get(frame_id, None)

        # If all OCR results for this frame are collected
        if expected is not None and ocr_results_dict[frame_id]["count"] == expected:
            # Push the grouped results to the visualization queue
            vis_output_queue.put((
                ocr_results_dict[frame_id]["frame"],   # The full input frame
                ocr_results_dict[frame_id]["results"], # All OCR outputs for this frame
                ocr_results_dict[frame_id]["boxes"]    # All box positions for this frame
            ))

            # Clean up to free memory
            del ocr_results_dict[frame_id]
            del ocr_expected_counts[frame_id]

    vis_output_queue.put(None)


def main() -> None:
    """
    Main function to run the script.
    """
    args = parse_args()
    init_logging(level=level_from_args(args))
    handle_and_resolve_args(args, APP_NAME, multi_hef=True)
    args.det_net, args.ocr_net = [model for model in args.hef_path]

    input_context = InputContext(
        input_src=args.input,
        batch_size=args.batch_size,
        resolution=args.camera_resolution,
        frame_rate=args.frame_rate,
        video_unpaced=args.video_unpaced,
    )

    input_context = init_input_source(input_context)

    visualization_settings = VisualizationSettings(
        output_dir=args.output_dir,
        save_stream_output=args.save_output,
        output_resolution=args.output_resolution,
        no_display=args.no_display,
        side_by_side=True,  # Enable side-by-side visualization for OCR results
    )

    run_inference_pipeline(
        args.det_net,
        args.ocr_net,
        input_context=input_context,
        visualization_settings=visualization_settings,
        show_fps=args.show_fps,
        time_to_run=args.time_to_run,
        use_corrector=args.use_corrector
    )


if __name__ == "__main__":
    main()