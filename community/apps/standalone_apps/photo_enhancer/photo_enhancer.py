#!/usr/bin/env python3
"""
Photo Enhancer - Batch 2x upscale of photos using Real-ESRGAN super resolution on Hailo-8.

Processes a directory of images (jpg/png), runs Real-ESRGAN x2 inference on each,
and saves the upscaled results to an output directory.

Based on the super_resolution standalone app template.

Run with:
    source setup_env.sh
    python -m community.apps.standalone_apps.photo_enhancer.photo_enhancer --input /path/to/images/ --save-output
"""
import numpy as np
from pathlib import Path
import sys
import threading
import queue
from functools import partial

# Make the local utils module importable whether this file is run as a script
# (``python community/.../photo_enhancer.py``) or as a module
# (``python -m community.apps.standalone_apps.photo_enhancer.photo_enhancer``).
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Ensure the repo root is on sys.path so ``hailo_apps`` imports resolve when run
# directly from the repo root.
repo_root = None
for p in Path(__file__).resolve().parents:
    if (p / "hailo_apps" / "config" / "config_manager.py").exists():
        repo_root = p
        break
if repo_root is not None:
    sys.path.insert(0, str(repo_root))

from photo_enhancer_utils import inference_result_handler

from hailo_apps.python.core.common.hailo_inference import HailoInfer
from hailo_apps.python.core.common.hailo_logger import get_logger, init_logging, level_from_args
from hailo_apps.python.core.common.core import handle_and_resolve_args
from hailo_apps.python.core.common.parser import get_standalone_parser
from hailo_apps.python.core.common.toolbox import (
    InputContext,
    VisualizationSettings,
    init_input_source,
    preprocess,
    visualize,
    FrameRateTracker,
    stop_after_timeout,
)
from hailo_apps.python.core.common.defines import (
    MAX_INPUT_QUEUE_SIZE,
    MAX_OUTPUT_QUEUE_SIZE,
)

# APP_NAME intentionally reuses "super_resolution" so this app picks up the
# same resource/model configuration as the super_resolution reference app.
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

    output_queue.put(None)  # Signal that this batch is done processing


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
    net_path,
    input_context: InputContext,
    visualization_settings: VisualizationSettings,
    show_fps: bool = False,
    time_to_run: int | None = None,
    enhanced_only: bool = False,
) -> None:
    """
    Initialize queues, create HailoInfer instance, and run the photo enhancement pipeline.

    Args:
        net_path (str): Path to the HEF model file (Real-ESRGAN x2).
        input_context (InputContext): Context containing input source information.
        visualization_settings (VisualizationSettings): Settings for visualization/saving.
        show_fps (bool): Whether to log FPS information during execution.
        time_to_run (int | None): Optional run duration in seconds.
        enhanced_only (bool): If True, save only the enhanced image (no side-by-side).

    Returns:
        None
    """
    stop_event = threading.Event()

    input_queue = queue.Queue(MAX_INPUT_QUEUE_SIZE)
    output_queue = queue.Queue(MAX_OUTPUT_QUEUE_SIZE)

    fps_tracker = None
    if show_fps:
        fps_tracker = FrameRateTracker()

    # Convert net_path to string if it's a Path object
    net_path = str(net_path)

    hailo_inference = HailoInfer(net_path, input_context.batch_size)

    height, width, _ = hailo_inference.get_input_shape()

    post_process_callback_fn = partial(
        inference_result_handler,
        model_height=height,
        model_width=width,
        enhanced_only=enhanced_only,
    )

    preprocess_thread = threading.Thread(
        target=preprocess,
        args=(
            input_context,
            input_queue,
            width,
            height,
            None,
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

    if time_to_run is not None:
        timer_thread = threading.Thread(
            target=stop_after_timeout,
            args=(stop_event, time_to_run),
            name="timer-thread",
            daemon=True,
        )
        timer_thread.start()

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

    logger.success("Processing completed successfully.")

    if visualization_settings.save_stream_output or input_context.has_images:
        logger.info(f"Saved upscaled outputs to '{visualization_settings.output_dir}'.")


def main() -> None:
    """
    Main function to run the photo enhancer.
    """
    # Parse command line arguments
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
        net_path=args.hef_path,
        input_context=input_context,
        visualization_settings=visualization_settings,
        show_fps=args.show_fps,
        time_to_run=args.time_to_run,
        enhanced_only=args.enhanced_only,
    )


if __name__ == "__main__":
    main()
