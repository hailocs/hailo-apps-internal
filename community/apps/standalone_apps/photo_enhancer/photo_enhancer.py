#!/usr/bin/env python3
"""
Photo Enhancer - Batch 2x upscale of photos using Real-ESRGAN super resolution on Hailo-8.

Processes a directory of images (jpg/png), runs Real-ESRGAN x2 inference on each,
and saves the upscaled results to an output directory.

Based on the super_resolution standalone app template.
"""
import argparse
import numpy as np
from pathlib import Path
import sys
import threading
import queue
from photo_enhancer_utils import PhotoEnhancerUtils, inference_result_handler
from functools import partial

try:
    from hailo_apps.python.core.common.hailo_inference import HailoInfer
    from hailo_apps.python.core.common.hailo_logger import get_logger, init_logging, level_from_args
    from hailo_apps.python.core.common.core import handle_and_resolve_args
    from hailo_apps.python.core.common.parser import get_standalone_parser
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
    )
except ImportError:
    repo_root = None
    for p in Path(__file__).resolve().parents:
        if (p / "hailo_apps" / "config" / "config_manager.py").exists():
            repo_root = p
            break
    if repo_root is not None:
        sys.path.insert(0, str(repo_root))
    from hailo_apps.python.core.common.hailo_inference import HailoInfer
    from hailo_apps.python.core.common.hailo_logger import get_logger, init_logging, level_from_args
    from hailo_apps.python.core.common.core import handle_and_resolve_args
    from hailo_apps.python.core.common.parser import get_standalone_parser
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
    )

APP_NAME = "super_resolution"
logger = get_logger(__name__)


def parse_args():
    """
    Initialize argument parser for the photo enhancer script.

    Returns:
        argparse.Namespace: Parsed arguments.
    """
    parser = get_standalone_parser()
    parser.description = (
        "Photo Enhancer - Batch 2x upscale of photos using Real-ESRGAN "
        "super resolution on Hailo-8."
    )
    parser.add_argument(
        "--enhanced-only",
        action="store_true",
        default=False,
        help="Save only the enhanced image (no side-by-side comparison).",
    )

    args = parser.parse_args()
    return args


def inference_callback(
        completion_info,
        bindings_list: list,
        input_batch: list,
        output_queue: queue.Queue
) -> None:
    """
    Inference callback to handle inference results and push them to a queue.

    Args:
        completion_info: Hailo inference completion info.
        bindings_list (list): Output bindings for each inference.
        input_batch (list): Original input frames.
        output_queue (queue.Queue): Queue to push output results to.
    """
    if completion_info.exception:
        logger.error(f'Inference error: {completion_info.exception}')
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


def infer(hailo_inference, input_queue, output_queue, stop_event):
    """
    Main inference loop that pulls data from the input queue, runs asynchronous
    inference, and pushes results to the output queue.

    Args:
        hailo_inference (HailoInfer): The inference engine to run model predictions.
        input_queue (queue.Queue): Provides (input_batch, preprocessed_batch) tuples.
        output_queue (queue.Queue): Collects (input_frame, result) tuples for visualization.
        stop_event (threading.Event): Signal to stop processing.

    Returns:
        None
    """
    while True:
        next_batch = input_queue.get()
        if not next_batch:
            break  # Stop signal received

        if stop_event.is_set():
            continue  # Skip processing if stop signal is set

        input_batch, preprocessed_batch = next_batch

        # Prepare the callback for handling the inference result
        inference_callback_fn = partial(
            inference_callback,
            input_batch=input_batch,
            output_queue=output_queue
        )

        if hailo_inference.last_infer_job is not None:
            hailo_inference.last_infer_job.wait(10000)

        # Run async inference
        hailo_inference.run(preprocessed_batch, inference_callback_fn)

    # Release resources and context
    hailo_inference.close()
    output_queue.put(None)


def run_inference_pipeline(
    net_path: str,
    input_src: str,
    batch_size: int,
    output_dir: str,
    camera_resolution: str,
    output_resolution: str,
    frame_rate: float,
    save_output: bool,
    show_fps: bool,
    no_display: bool,
    enhanced_only: bool = False
) -> None:
    """
    Initialize queues, create HailoInfer instance, and run the photo enhancement pipeline.

    Args:
        net_path (str): Path to the HEF model file (Real-ESRGAN x2).
        input_src (str): Input source path (image directory).
        batch_size (int): Number of frames to process per batch.
        output_dir (str): Directory path to save upscaled output images.
        camera_resolution (str): Camera input resolution (unused for batch image mode).
        output_resolution (str): Output resolution for display/saving.
        frame_rate (float): Target frame rate for processing.
        save_output (bool): Whether to save the processed images.
        show_fps (bool): Whether to log FPS information during execution.
        no_display (bool): Whether to suppress display output.
        enhanced_only (bool): If True, save only the enhanced image (no side-by-side).

    Returns:
        None
    """
    # Initialize input source from string: image folder
    cap, images, input_type = init_input_source(input_src, batch_size, camera_resolution)
    cap_processing_mode = None
    if cap is not None:
        cap_processing_mode = select_cap_processing_mode(input_type, save_output, frame_rate)

    stop_event = threading.Event()

    input_queue = queue.Queue(MAX_INPUT_QUEUE_SIZE)
    output_queue = queue.Queue(MAX_OUTPUT_QUEUE_SIZE)

    fps_tracker = None
    if show_fps:
        fps_tracker = FrameRateTracker()

    # Convert net_path to string if it's a Path object
    net_path = str(net_path)

    # Use SRGAN (Real-ESRGAN) utilities for preprocessing and postprocessing
    utils = PhotoEnhancerUtils()
    hailo_inference = HailoInfer(net_path, batch_size)

    height, width, _ = hailo_inference.get_input_shape()

    post_process_callback_fn = partial(
        inference_result_handler,
        model_height=height,
        model_width=width,
        enhanced_only=enhanced_only
    )

    preprocess_thread = threading.Thread(
        target=preprocess,
        args=(images, cap, frame_rate, batch_size, input_queue, width, height,
              cap_processing_mode, None, stop_event)
    )
    postprocess_thread = threading.Thread(
        target=visualize,
        args=(output_queue, cap, save_output, output_dir, post_process_callback_fn,
              fps_tracker, output_resolution, frame_rate, True, stop_event, no_display)
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

        logger.success("Processing completed successfully.")
        if save_output or input_type == "images":
            logger.info(f"Saved upscaled outputs to '{output_dir}'.")


def main() -> None:
    """
    Main function to run the photo enhancer.
    """
    # Parse command line arguments
    args = parse_args()
    init_logging(level=level_from_args(args))
    handle_and_resolve_args(args, APP_NAME)
    # Start the inference pipeline
    run_inference_pipeline(
        args.hef_path,
        args.input,
        args.batch_size,
        args.output_dir,
        args.camera_resolution,
        args.output_resolution,
        args.frame_rate,
        args.save_output,
        args.show_fps,
        args.no_display,
        enhanced_only=args.enhanced_only,
    )


if __name__ == "__main__":
    main()
