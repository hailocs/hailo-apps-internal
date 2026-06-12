#!/usr/bin/env python3
"""
Traffic Light Detector - Detect and classify traffic light states from dashcam video.

Detects traffic lights in dashcam footage using YOLOv8 object detection on a Hailo
accelerator, then classifies each detected light's state (red, yellow, green) using
color analysis on the cropped region. Outputs annotated video/images and an optional
JSON summary of traffic light states per frame.

Usage:
    python -m hailo_apps.python.standalone_apps.traffic_light_detector.traffic_light_detector --input dashcam.mp4
    python -m hailo_apps.python.standalone_apps.traffic_light_detector.traffic_light_detector --input dashcam.mp4 --save-output --json-summary
    python -m hailo_apps.python.standalone_apps.traffic_light_detector.traffic_light_detector --input images/ --no-display
"""
import os
import sys
import queue
import threading
from functools import partial
from types import SimpleNamespace
from pathlib import Path
import collections
import json
import numpy as np

# Handle both installed-package and direct-script execution
try:
    from hailo_apps.python.core.common.hailo_inference import HailoInfer
    from hailo_apps.python.core.common.toolbox import (
        init_input_source,
        get_labels,
        load_json_file,
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
    from hailo_apps.python.core.common.parser import get_standalone_parser
    from hailo_apps.python.core.common.hailo_logger import get_logger, init_logging, level_from_args
    from hailo_apps.python.core.common.core import handle_and_resolve_args
    from community.apps.standalone_apps.traffic_light_detector.traffic_light_post_process import inference_result_handler
except ImportError:
    # Fallback for running as a plain script outside the package
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
        get_labels,
        load_json_file,
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
    from hailo_apps.python.core.common.parser import get_standalone_parser
    from hailo_apps.python.core.common.hailo_logger import get_logger, init_logging, level_from_args
    from hailo_apps.python.core.common.core import handle_and_resolve_args
    from community.apps.standalone_apps.traffic_light_detector.traffic_light_post_process import inference_result_handler


APP_NAME = Path(__file__).stem
logger = get_logger(__name__)

# Frame-level summary storage for JSON output
frame_summaries = []
frame_counter = [0]


def parse_args():
    """
    Parse command-line arguments for the traffic light detection application.

    Returns:
        argparse.Namespace: Parsed CLI arguments.
    """
    parser = get_standalone_parser()
    parser.description = (
        "Detect traffic lights in dashcam footage and classify their state "
        "(red, yellow, green) using YOLOv8 detection + color analysis."
    )

    parser.add_argument(
        "--labels", "-l",
        type=str,
        default=None,
        help=(
            "Path to a text file containing class labels, one per line. "
            "If not specified, default COCO labels will be used."
        ),
    )

    parser.add_argument(
        "--json-summary",
        action="store_true",
        help=(
            "Save a JSON summary of traffic light states per frame to the output directory. "
            "The file will contain frame number, timestamp, and detected light states."
        ),
    )

    parser.add_argument(
        "--confidence-threshold",
        type=float,
        default=None,
        help=(
            "Override the detection confidence threshold from config.json. "
            "Lower values detect more lights but may increase false positives."
        ),
    )

    args = parser.parse_args()
    return args


def run_inference_pipeline(
    net,
    input_src,
    batch_size,
    labels,
    output_dir,
    save_output=False,
    camera_resolution="sd",
    output_resolution=None,
    show_fps=False,
    frame_rate=None,
    no_display=False,
    json_summary=False,
    confidence_threshold=None,
) -> None:
    """
    Initialize queues, HailoAsyncInference instance, and run the inference pipeline.

    Architecture:
        preprocess_thread --> input_queue --> infer_thread --> output_queue --> visualize_thread

    The preprocess thread reads frames, resizes them to model input size, and queues them.
    The infer thread runs async inference on the Hailo device.
    The visualize thread applies post-processing (traffic light detection + color
    classification), draws results, and displays/saves output.
    """
    labels = get_labels(labels)
    config_data = load_json_file("config.json")

    # Override confidence threshold if provided via CLI
    if confidence_threshold is not None:
        config_data.setdefault("visualization_params", {})["score_thres"] = confidence_threshold

    # Initialize input source from string: video file or image folder
    cap, images, input_type = init_input_source(input_src, batch_size, camera_resolution)
    cap_processing_mode = None
    if cap is not None:
        cap_processing_mode = select_cap_processing_mode(input_type, save_output, frame_rate)

    stop_event = threading.Event()

    fps_tracker = None
    if show_fps:
        fps_tracker = FrameRateTracker()

    input_queue = queue.Queue(MAX_INPUT_QUEUE_SIZE)
    output_queue = queue.Queue(MAX_OUTPUT_QUEUE_SIZE)

    post_process_callback_fn = partial(
        inference_result_handler,
        labels=labels,
        config_data=config_data,
        frame_summaries=frame_summaries if json_summary else None,
        frame_counter=frame_counter,
    )

    hailo_inference = HailoInfer(net, batch_size)
    height, width, _ = hailo_inference.get_input_shape()

    preprocess_thread = threading.Thread(
        target=preprocess,
        args=(images, cap, frame_rate, batch_size, input_queue,
              width, height, cap_processing_mode, None, stop_event)
    )
    postprocess_thread = threading.Thread(
        target=visualize,
        args=(output_queue, cap, save_output, output_dir,
              post_process_callback_fn, fps_tracker, output_resolution,
              frame_rate, False, stop_event, no_display)
    )
    infer_thread = threading.Thread(
        target=infer,
        args=(hailo_inference, input_queue, output_queue, stop_event)
    )

    preprocess_thread.start()
    postprocess_thread.start()
    infer_thread.start()

    if show_fps:
        fps_tracker.start()

    try:
        preprocess_thread.join()
        infer_thread.join()
        postprocess_thread.join()
    except KeyboardInterrupt:
        logger.info("Interrupted (Ctrl+C). Shutting down...")
        stop_event.set()
    finally:
        if show_fps:
            logger.info(fps_tracker.frame_rate_summary())

        # Save JSON summary if requested
        if json_summary and frame_summaries:
            summary_path = os.path.join(output_dir, "traffic_light_summary.json")
            os.makedirs(output_dir, exist_ok=True)
            with open(summary_path, "w") as f:
                json.dump({
                    "total_frames": len(frame_summaries),
                    "frames": frame_summaries,
                }, f, indent=2)
            logger.info(f"Traffic light summary saved to '{summary_path}'.")

        logger.success("Processing completed successfully.")
        if save_output or input_type == "images":
            logger.info(f"Saved outputs to '{output_dir}'.")


def infer(hailo_inference, input_queue, output_queue, stop_event):
    """
    Main inference loop that pulls data from the input queue, runs asynchronous
    inference, and pushes results to the output queue.

    Each item in the input queue is expected to be a tuple:
        (input_batch, preprocessed_batch)

    Args:
        hailo_inference (HailoInfer): The inference engine to run model predictions.
        input_queue (queue.Queue): Provides (input_batch, preprocessed_batch) tuples.
        output_queue (queue.Queue): Collects (input_frame, result) tuples for visualization.
        stop_event (threading.Event): Signal to stop processing.
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
            inference_callback,
            input_batch=input_batch,
            output_queue=output_queue
        )

        while len(pending_jobs) >= MAX_ASYNC_INFER_JOBS:
            pending_jobs.popleft().wait(10000)

        job = hailo_inference.run(preprocessed_batch, inference_callback_fn)
        pending_jobs.append(job)

    hailo_inference.close()
    output_queue.put(None)


def inference_callback(
    completion_info,
    bindings_list: list,
    input_batch: list,
    output_queue: queue.Queue
) -> None:
    """
    Inference callback to handle inference results and push them to the output queue.

    Args:
        completion_info: Hailo inference completion info.
        bindings_list (list): Output bindings for each inference.
        input_batch (list): Original input frames.
        output_queue (queue.Queue): Queue to push output results to.
    """
    if completion_info.exception:
        logger.error(f"Inference error: {completion_info.exception}")
    else:
        for i, bindings in enumerate(bindings_list):
            if len(bindings._output_names) == 1:
                result = bindings.output().get_buffer()
            else:
                result = {
                    name: np.expand_dims(
                        bindings.output(name).get_buffer(), axis=0
                    )
                    for name in bindings._output_names
                }
            output_queue.put((input_batch[i], result))


def main() -> None:
    """
    Main function to run the traffic light detection application.
    """
    args = parse_args()
    init_logging(level=level_from_args(args))
    handle_and_resolve_args(args, APP_NAME)
    run_inference_pipeline(
        args.hef_path,
        args.input,
        args.batch_size,
        args.labels,
        args.output_dir,
        args.save_output,
        args.camera_resolution,
        args.output_resolution,
        args.show_fps,
        args.frame_rate,
        args.no_display,
        args.json_summary,
        args.confidence_threshold,
    )


if __name__ == "__main__":
    main()
