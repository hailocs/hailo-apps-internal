#!/usr/bin/env python3
"""
Traffic Light Detector - Detect and classify traffic light states from dashcam video.

Detects traffic lights in dashcam footage using YOLOv8 object detection on a Hailo
accelerator, then classifies each detected light's state (red, yellow, green) using
color analysis on the cropped region. Outputs annotated video/images and an optional
JSON summary of traffic light states per frame.

Usage:
    source setup_env.sh
    python -m community.apps.standalone_apps.traffic_light_detector.traffic_light_detector --input dashcam.mp4
    python -m community.apps.standalone_apps.traffic_light_detector.traffic_light_detector --input dashcam.mp4 --save-output --json-summary
    python -m community.apps.standalone_apps.traffic_light_detector.traffic_light_detector --input images/ --no-display
"""
import os
import queue
import threading
from functools import partial
from pathlib import Path
import collections
import json
import numpy as np

from hailo_apps.python.core.common.hailo_inference import HailoInfer
from hailo_apps.python.core.common.toolbox import (
    InputContext,
    VisualizationSettings,
    init_input_source,
    get_labels,
    load_json_file,
    preprocess,
    visualize,
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


# Use a registered COCO-detection app key so the default YOLOv8 HEF resolves
# (this app filters COCO class 9 = traffic light from a standard detection model).
# Override the model with --hef-path to use a different YOLOv8 HEF.
APP_NAME = "object_detection"
logger = get_logger(__name__)


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
    labels,
    input_context: InputContext,
    visualization_settings: VisualizationSettings,
    show_fps: bool = False,
    json_summary: bool = False,
    confidence_threshold=None,
) -> None:
    """
    Initialize queues, HailoInfer instance, and run the inference pipeline.

    Architecture:
        preprocess_thread --> input_queue --> infer_thread --> output_queue --> visualize

    The preprocess thread reads frames, resizes them to model input size, and queues them.
    The infer thread runs async inference on the Hailo device.
    The main thread runs visualize(): post-processing (traffic light detection + color
    classification), drawing, and display/save.
    """
    labels = get_labels(labels)
    app_dir = Path(__file__).resolve().parent
    config_path = app_dir / "config.json"
    config_data = load_json_file(str(config_path))

    # Override confidence threshold if provided via CLI
    if confidence_threshold is not None:
        config_data.setdefault("visualization_params", {})["score_thres"] = confidence_threshold

    # Per-run JSON-summary state (only allocated when requested)
    frame_summaries = [] if json_summary else None
    frame_counter = [0]

    stop_event = threading.Event()
    fps_tracker = FrameRateTracker() if show_fps else None

    input_queue = queue.Queue(MAX_INPUT_QUEUE_SIZE)
    output_queue = queue.Queue(MAX_OUTPUT_QUEUE_SIZE)

    post_process_callback_fn = partial(
        inference_result_handler,
        labels=labels,
        config_data=config_data,
        frame_summaries=frame_summaries,
        frame_counter=frame_counter,
    )

    hailo_inference = HailoInfer(net, input_context.batch_size)
    height, width, _ = hailo_inference.get_input_shape()

    preprocess_thread = threading.Thread(
        target=preprocess,
        args=(
            input_context,
            input_queue,
            width,
            height,
            None,  # Use default preprocess from toolbox
            stop_event,
        ),
        name="preprocess-thread",
    )
    infer_thread = threading.Thread(
        target=infer,
        args=(hailo_inference, input_queue, output_queue, stop_event),
        name="infer-thread",
    )

    preprocess_thread.start()
    infer_thread.start()

    if show_fps:
        fps_tracker.start()

    try:
        visualize(
            input_context,
            visualization_settings,
            output_queue,
            post_process_callback_fn,
            fps_tracker,
            stop_event,
        )
    finally:
        stop_event.set()
        preprocess_thread.join()
        infer_thread.join()

        if show_fps:
            logger.info(fps_tracker.frame_rate_summary())

        # Save JSON summary if requested
        if json_summary and frame_summaries:
            output_dir = visualization_settings.output_dir
            summary_path = os.path.join(output_dir, "traffic_light_summary.json")
            os.makedirs(output_dir, exist_ok=True)
            with open(summary_path, "w") as f:
                json.dump({
                    "total_frames": len(frame_summaries),
                    "frames": frame_summaries,
                }, f, indent=2)
            logger.info(f"Traffic light summary saved to '{summary_path}'.")

        logger.success("Processing completed successfully.")
        if visualization_settings.save_stream_output or input_context.has_images:
            logger.info(f"Saved outputs to '{visualization_settings.output_dir}'.")


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
    )

    run_inference_pipeline(
        net=args.hef_path,
        labels=args.labels,
        input_context=input_context,
        visualization_settings=visualization_settings,
        show_fps=args.show_fps,
        json_summary=args.json_summary,
        confidence_threshold=args.confidence_threshold,
    )


if __name__ == "__main__":
    main()
