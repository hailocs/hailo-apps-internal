#!/usr/bin/env python3
import os
import sys
import multiprocessing as mp
from queue import Queue
from functools import partial
import numpy as np
import threading
from pathlib import Path
import collections
try:
    from hailo_apps.python.core.common.hailo_logger import get_logger, init_logging, level_from_args
    from hailo_apps.python.core.common.hailo_inference import HailoInfer
    from hailo_apps.python.core.common.core import handle_and_resolve_args
    from hailo_apps.python.core.common.parser import get_standalone_parser
    from hailo_apps.python.core.common.toolbox import (
        InputContext,
        VisualizationSettings,
        init_input_source,
        preprocess,
        visualize,
        FrameRateTracker,
    )
    from hailo_apps.python.core.common.onnx_utils import (
        load_onnx_config,
        init_onnx_sessions,
        normalized_preprocess,
        infer_full_onnx,
    )
    from hailo_apps.python.standalone_apps.yolo26_pose_estimation.yolo26_pose_estimation_utils import PoseEstPostProcessing
    from hailo_apps.python.standalone_apps.yolo26_pose_estimation.aigym import AIGymCallback, make_tracker_args, EXERCISE_PRESETS
    from hailo_apps.python.core.common.defines import (
        MAX_INPUT_QUEUE_SIZE,
        MAX_OUTPUT_QUEUE_SIZE,
        MAX_ASYNC_INFER_JOBS
    )
except ImportError:
    repo_root = None
    for p in Path(__file__).resolve().parents:
        if (p / "hailo_apps" / "config" / "config_manager.py").exists():
            repo_root = p
            break
    if repo_root is not None:
        sys.path.insert(0, str(repo_root))

    from hailo_apps.python.core.common.hailo_logger import get_logger, init_logging, level_from_args
    from hailo_apps.python.core.common.hailo_inference import HailoInfer
    from hailo_apps.python.core.common.core import handle_and_resolve_args
    from hailo_apps.python.core.common.parser import get_standalone_parser
    from hailo_apps.python.core.common.toolbox import (
        InputContext,
        VisualizationSettings,
        init_input_source,
        preprocess,
        visualize,
        FrameRateTracker,
    )
    from hailo_apps.python.core.common.defines import (
        MAX_INPUT_QUEUE_SIZE,
        MAX_OUTPUT_QUEUE_SIZE,
        MAX_ASYNC_INFER_JOBS
    )    
    from hailo_apps.python.core.common.onnx_utils import (
        load_onnx_config,
        init_onnx_sessions,
        normalized_preprocess,
        infer_full_onnx,
    )
    from hailo_apps.python.standalone_apps.yolo26_pose_estimation.yolo26_pose_estimation_utils import PoseEstPostProcessing
    from hailo_apps.python.standalone_apps.yolo26_pose_estimation.aigym import AIGymCallback, make_tracker_args, EXERCISE_PRESETS


APP_NAME = Path(__file__).stem
logger = get_logger(__name__)


def parse_args():
    """
    Initialize argument parser for the script.

    Returns:
        argparse.Namespace: Parsed arguments.
    """
    parser = get_standalone_parser()
    parser.description = "YOLO26 pose estimation with ONNX postprocessing."

    # App-specific arguments
    parser.add_argument(
        "--class-num",
        "-cn",
        type=int,
        default=1,
        help="The number of classes the model is trained on. Defaults to 1.",
    )

    parser.add_argument(
        "--pose-trail",
        type=int,
        default=0,
        metavar="N",
        help=(
            "Number of previous frames whose pose skeletons are kept and drawn "
            "as a fading trail behind the current detection. "
            "0 (default) disables the trail. Typical value: 10."
        ),
    )

    parser.add_argument(
        "--mute-background",
        type=float,
        default=None,
        metavar="ALPHA",
        help=(
            "Dim the background image to emphasize pose skeletons. "
            "ALPHA is the blending factor for the original frame (0.0 = black, 1.0 = unchanged). "
            "Typical value: 0.3. Omit to keep the background at full brightness."
        ),
    )

    parser.add_argument(
        "--onnxconfig",
        type=str,
        default=None,
        help=(
            "Path to ONNX postprocessing configuration file (JSON). "
            "When specified, enables ONNX-based postprocessing instead of HailoRT NMS. "
            "The config must include: postproc_onnx_path, output_tensor_mapping, output_format, "
            "and postprocess_params."
        ),
    )

    parser.add_argument(
        "--full-onnx",
        action="store_true",
        help=(
            "Use full ONNX mode (bypass HEF, run entire model in ONNX). "
            "Overrides use_full_onnx_mode setting in config. "
            "Requires hef_like_proc_onnx_path in ONNX config."
        ),
    )

    parser.add_argument(
        "--aigym",
        type=str,
        default=None,
        choices=list(EXERCISE_PRESETS.keys()),
        metavar="EXERCISE",
        help=(
            "Enable exercise rep-counting mode.  "
            "Adds ByteTrack multi-person tracking and angle-based "
            "hysteresis counting.  "
            f"Choices: {', '.join(EXERCISE_PRESETS.keys())}."
        ),
    )

    args = parser.parse_args()
    return args


def inference_callback(
        completion_info,
        bindings_list: list,
        input_batch: list,
        output_queue: mp.Queue
) -> None:
    """
    infernce callback to handle inference results and push them to a queue.

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
            inference_callback,
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


def run_inference_pipeline(
    net_path: str,
    input_src: str,
    batch_size: int,
    class_num: int,
    output_dir: str,
    camera_resolution: str,
    output_resolution: tuple[int, int] | None,
    frame_rate: float,
    save_output: bool,
    show_fps: bool,
    no_display: bool = False,
    pose_trail: int = 0,
    mute_background: float | None = None,
    onnxconfig=None,
    aigym: str | None = None,
    args=None,
) -> None:
    """
    Run the inference pipeline using HailoInfer, with optional ONNX postprocessing.

    Args:
        net_path (str): Path to the HEF model file.
        input_src (str): Path to the input source (image, video, folder, or camera).
        batch_size (int): Number of frames to process per batch.
        class_num (int): Number of output classes expected by the model.
        output_dir (str): Directory where processed output will be saved.
        camera_resolution (str): Camera only, input resolution (e.g., 'sd', 'hd', 'fhd').
        output_resolution (str): Output resolution for display/saving.
        frame_rate (float): Target frame rate for processing.
        save_output (bool): If True, saves the output stream as a video file.
        show_fps (bool): If True, display real-time FPS on the output.
        onnxconfig (str): Path to ONNX postprocessing config JSON (or None).
        args: Full parsed CLI args (for --full-onnx flag).

    Returns:
        None
    """
    input_queue = Queue(MAX_INPUT_QUEUE_SIZE)
    output_queue = Queue(MAX_OUTPUT_QUEUE_SIZE)

    # --- ONNX setup ---
    onnx_config = None
    onnx_session = None
    full_onnx_intermediate_session = None
    use_full_onnx = False

    if not onnxconfig:
        raise ValueError(
            "This app runs ONNX-postprocessing only. "
            "Provide --onnxconfig, or place the convention file and rely on auto-resolution."
        )
    onnx_config, config_path = load_onnx_config(onnxconfig, caller_file=__file__)
    use_full_onnx = (
        getattr(args, "full_onnx", False)
        or onnx_config.get("use_full_onnx_mode", False)
    )
    sessions = init_onnx_sessions(onnx_config, config_path, use_full_onnx)
    onnx_session = sessions["onnx_session"]
    full_onnx_intermediate_session = sessions["full_onnx_intermediate_session"]

    # --- Post-processing ---
    pose_post_processing = PoseEstPostProcessing(
        max_detections=300,
        score_threshold=0.001,
        nms_iou_thresh=0.7,
        regression_length=15,
        strides=[8, 16, 32],
        trail_length=pose_trail,
        bg_alpha=mute_background,
    )

    input_context = InputContext(
        input_src=input_src,
        batch_size=batch_size,
        resolution=camera_resolution,
        frame_rate=frame_rate,
    )
    input_context = init_input_source(input_context)

    visualization_settings = VisualizationSettings(
        output_dir=output_dir,
        save_stream_output=save_output,
        output_resolution=output_resolution,
        no_display=no_display,
    )

    stop_event = threading.Event()
    fps_tracker = None
    if show_fps:
        fps_tracker = FrameRateTracker()

    # --- Model / shape setup ---
    hailo_inference = None
    if use_full_onnx:
        # Derive input shape from the intermediate ONNX model
        input_info = full_onnx_intermediate_session.get_inputs()[0]
        input_shape = input_info.shape
        if len(input_shape) == 4:
            if input_shape[1] in [1, 3]:  # NCHW
                height, width = input_shape[2], input_shape[3]
            else:  # NHWC
                height, width = input_shape[1], input_shape[2]
        else:
            raise ValueError(f"Unexpected full ONNX input shape: {input_shape}")
        logger.info(
            f"Full ONNX mode enabled – intermediate + ONNX postproc (input {height}x{width})"
        )
    else:
        output_type = "FLOAT32" if onnx_session is not None else "FLOAT32"
        hailo_inference = HailoInfer(net_path, batch_size, output_type=output_type)
        height, width, _ = hailo_inference.get_input_shape()

    # --- Choose callback: AIGym mode vs. regular pose visualization ---
    if aigym is not None:
        from hailo_apps.python.core.tracker.byte_tracker import BYTETracker

        tracker = BYTETracker(make_tracker_args(), frame_rate=int(frame_rate or 30))
        aigym_cb = AIGymCallback(
            pose_processor=pose_post_processing,
            tracker=tracker,
            exercise=aigym,
            model_height=height,
            model_width=width,
            class_num=class_num,
            onnx_config=onnx_config,
            onnx_session=onnx_session,
        )
        post_process_callback_fn = aigym_cb
        logger.info(f"AIGym mode enabled – exercise: {aigym}")
    else:
        post_process_callback_fn = partial(
            pose_post_processing.inference_result_handler,
            model_height=height,
            model_width=width,
            class_num=class_num,
            onnx_config=onnx_config,
            onnx_session=onnx_session,
        )

    preprocess_thread = threading.Thread(
        target=preprocess,
        args=(
            input_context,
            input_queue,
            width,
            height,
            normalized_preprocess if use_full_onnx else None,
            stop_event,
        ),
    )

    postprocess_thread = threading.Thread(
        target=visualize,
        args=(
            input_context,
            visualization_settings,
            output_queue,
            post_process_callback_fn,
            fps_tracker,
            stop_event,
        ),
    )

    if use_full_onnx:
        infer_thread = threading.Thread(
            target=infer_full_onnx,
            args=(full_onnx_intermediate_session, onnx_session,
                  onnx_config, input_queue, output_queue),
    )
    else:
        infer_thread = threading.Thread(
            target=infer,
            args=(hailo_inference, input_queue, output_queue, stop_event),
        )

    infer_thread.start()
    preprocess_thread.start()
    postprocess_thread.start()

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
        if save_output or input_context.has_images:
            logger.info(f"Saved outputs to '{output_dir}'.")



def main() -> None:
    args = parse_args()
    init_logging(level=level_from_args(args))
    handle_and_resolve_args(args, APP_NAME)

    # --no-display implies --save-output
    no_display = getattr(args, "no_display", False)
    save_output = args.save_output or no_display

    run_inference_pipeline(
        args.hef_path,
        args.input,
        args.batch_size,
        args.class_num,
        args.output_dir,
        args.camera_resolution,
        args.output_resolution,
        args.frame_rate,
        save_output,
        args.show_fps,
        no_display=no_display,
        pose_trail=args.pose_trail,
        mute_background=args.mute_background,
        onnxconfig=args.onnxconfig,
        aigym=args.aigym,
        args=args        
    )


if __name__ == "__main__":
    main()
