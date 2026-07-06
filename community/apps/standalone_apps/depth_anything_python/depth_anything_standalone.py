#!/usr/bin/env python3
"""
Depth Anything Standalone - Monocular depth estimation using HailoRT Python API.

Runs Depth Anything V1 or V2 on a Hailo accelerator without GStreamer.
Reads from an image file, video file, or camera (OpenCV), runs inference,
normalizes the raw depth output to 0-255, applies a colormap, and displays
or saves the result.

Usage:
    python depth_anything_standalone.py --input image.jpg
    python depth_anything_standalone.py --input video.mp4 --colormap turbo
    python depth_anything_standalone.py --input usb --model-version v1
    python depth_anything_standalone.py --input video.mp4 --display-mode side-by-side --save-output
"""
import os
import sys
import queue
import threading
import collections
import urllib.request
from functools import partial
from pathlib import Path

import cv2
import numpy as np

# Handle both installed-package and direct-script execution
try:
    from hailo_apps.python.core.common.hailo_inference import HailoInfer
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
        MAX_ASYNC_INFER_JOBS,
    )
    from hailo_apps.python.core.common.parser import get_standalone_parser
    from hailo_apps.python.core.common.hailo_logger import get_logger, init_logging, level_from_args
    from hailo_apps.python.core.common.installation_utils import detect_hailo_arch
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
        MAX_ASYNC_INFER_JOBS,
    )
    from hailo_apps.python.core.common.parser import get_standalone_parser
    from hailo_apps.python.core.common.hailo_logger import get_logger, init_logging, level_from_args
    from hailo_apps.python.core.common.installation_utils import detect_hailo_arch


APP_NAME = Path(__file__).stem
logger = get_logger(__name__)

# --------------------------------------------------------------------------- #
# Model configuration
# --------------------------------------------------------------------------- #

# HEF download URLs from Hailo Model Zoo (same as pipeline app)
MODEL_URLS = {
    ("v1", "hailo8"): "https://hailo-model-zoo.s3.eu-west-2.amazonaws.com/ModelZoo/Compiled/v2.18.0/hailo8/depth_anything_vits.hef",
    ("v1", "hailo8l"): "https://hailo-model-zoo.s3.eu-west-2.amazonaws.com/ModelZoo/Compiled/v2.18.0/hailo8l/depth_anything_vits.hef",
    ("v1", "hailo10h"): "https://hailo-model-zoo.s3.eu-west-2.amazonaws.com/ModelZoo/Compiled/v5.2.0/hailo10h/depth_anything_vits.hef",
    ("v2", "hailo8"): "https://hailo-model-zoo.s3.eu-west-2.amazonaws.com/ModelZoo/Compiled/v2.18.0/hailo8/depth_anything_v2_vits.hef",
    ("v2", "hailo8l"): "https://hailo-model-zoo.s3.eu-west-2.amazonaws.com/ModelZoo/Compiled/v2.18.0/hailo8l/depth_anything_v2_vits.hef",
    ("v2", "hailo10h"): "https://hailo-model-zoo.s3.eu-west-2.amazonaws.com/ModelZoo/Compiled/v5.2.0/hailo10h/depth_anything_v2_vits.hef",
}

MODEL_NAMES = {
    "v1": "depth_anything_vits",
    "v2": "depth_anything_v2_vits",
}

# OpenCV colormap options
COLORMAP_MAP = {
    "inferno": cv2.COLORMAP_INFERNO,
    "spectral": cv2.COLORMAP_RAINBOW,
    "magma": cv2.COLORMAP_MAGMA,
    "turbo": cv2.COLORMAP_TURBO,
}


def get_hef_path(model_version, arch, user_hef_path=None):
    """Resolve HEF path: use user-provided path, or download from Model Zoo."""
    if user_hef_path and Path(user_hef_path).exists():
        logger.info("Using user-provided HEF: %s", user_hef_path)
        return str(user_hef_path)

    model_name = MODEL_NAMES[model_version]
    resources_dir = Path(__file__).parent / "resources"
    resources_dir.mkdir(exist_ok=True)
    hef_path = resources_dir / f"{model_name}.hef"

    if hef_path.exists():
        logger.info("Found local HEF: %s", hef_path)
        return str(hef_path)

    url_key = (model_version, arch)
    if url_key not in MODEL_URLS:
        raise RuntimeError(
            f"No HEF URL for model version '{model_version}' on architecture '{arch}'. "
            f"Available: {list(MODEL_URLS.keys())}"
        )

    url = MODEL_URLS[url_key]
    logger.info("Downloading HEF from %s ...", url)
    print(f"Downloading {model_name}.hef for {arch}...")
    try:
        urllib.request.urlretrieve(url, str(hef_path))
        logger.info("Downloaded HEF to %s", hef_path)
        print(f"Downloaded to {hef_path}")
    except Exception as e:
        raise RuntimeError(
            f"Failed to download HEF from {url}: {e}\n"
            f"Please download manually and pass via --hef-path"
        ) from e

    return str(hef_path)


# --------------------------------------------------------------------------- #
# Post-processing (identity: normalize + colormap)
# --------------------------------------------------------------------------- #

def depth_postprocess(
    frame: np.ndarray,
    result: np.ndarray,
    colormap_cv2: int = cv2.COLORMAP_INFERNO,
    display_mode: str = "depth",
    alpha: float = 0.5,
    **kwargs,
) -> np.ndarray:
    """
    Post-process a single depth inference result.

    The model output is a raw relative depth map. Post-processing is identity:
    just normalize min-max to 0-255 and apply a colormap.

    Args:
        frame: Original input frame (RGB, uint8, original resolution).
        result: Raw model output -- depth map as a numpy array.
        colormap_cv2: OpenCV colormap constant for depth visualization.
        display_mode: One of "depth", "side-by-side", "overlay".
        alpha: Blend alpha for overlay mode (0.0-1.0).

    Returns:
        np.ndarray: Visualized frame (RGB).
    """
    # Squeeze to 2D depth map (model outputs HxWx1 or HxW)
    depth = result.squeeze()

    # Normalize to 0-255
    d_min = depth.min()
    d_max = depth.max()
    depth_norm = ((depth - d_min) / (d_max - d_min + 1e-6) * 255).astype(np.uint8)

    # Apply colormap (produces BGR) then convert to RGB to match pipeline convention
    depth_color_bgr = cv2.applyColorMap(depth_norm, colormap_cv2)
    depth_color = cv2.cvtColor(depth_color_bgr, cv2.COLOR_BGR2RGB)

    # Resize depth colormap to original frame dimensions
    h, w = frame.shape[:2]
    depth_color_resized = cv2.resize(depth_color, (w, h), interpolation=cv2.INTER_LINEAR)

    if display_mode == "depth":
        return depth_color_resized

    elif display_mode == "side-by-side":
        half_w = w // 2
        left = cv2.resize(frame, (half_w, h))
        right = cv2.resize(depth_color_resized, (half_w, h))
        return np.hstack([left, right])

    elif display_mode == "overlay":
        return cv2.addWeighted(frame, 1 - alpha, depth_color_resized, alpha, 0)

    else:
        return depth_color_resized


# --------------------------------------------------------------------------- #
# Inference callback and loop
# --------------------------------------------------------------------------- #

def inference_callback(completion_info, bindings_list, input_batch, output_queue):
    """Called when async inference completes. Extracts depth output and queues it."""
    if completion_info.exception:
        logger.error(f"Inference error: {completion_info.exception}")
    else:
        for i, bindings in enumerate(bindings_list):
            if len(bindings._output_names) == 1:
                result = bindings.output().get_buffer()
            else:
                result = {
                    name: np.expand_dims(bindings.output(name).get_buffer(), axis=0)
                    for name in bindings._output_names
                }
            output_queue.put((input_batch[i], result))


def infer(hailo_inference, input_queue, output_queue, stop_event):
    """Inference loop: pulls batches from input_queue, runs async inference."""
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
            output_queue=output_queue,
        )

        while len(pending_jobs) >= MAX_ASYNC_INFER_JOBS:
            pending_jobs.popleft().wait(10000)

        job = hailo_inference.run(preprocessed_batch, inference_callback_fn)
        pending_jobs.append(job)

    hailo_inference.close()
    output_queue.put(None)


# --------------------------------------------------------------------------- #
# Pipeline orchestration
# --------------------------------------------------------------------------- #

def run_inference_pipeline(
    hef_path,
    input_context: InputContext,
    visualization_settings: VisualizationSettings,
    show_fps=False,
    colormap_name="inferno",
    display_mode="depth",
    alpha=0.5,
    time_to_run=None,
) -> None:
    """
    Main inference pipeline with 3-thread architecture:
        preprocess_thread --> input_queue --> infer_thread --> output_queue --> visualize (main thread)
    """
    colormap_cv2 = COLORMAP_MAP.get(colormap_name, cv2.COLORMAP_INFERNO)

    stop_event = threading.Event()
    fps_tracker = FrameRateTracker() if show_fps else None

    input_queue = queue.Queue(MAX_INPUT_QUEUE_SIZE)
    output_queue = queue.Queue(MAX_OUTPUT_QUEUE_SIZE)

    post_process_callback_fn = partial(
        depth_postprocess,
        colormap_cv2=colormap_cv2,
        display_mode=display_mode,
        alpha=alpha,
    )

    hailo_inference = HailoInfer(hef_path, input_context.batch_size)
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
        logger.info(f"Saved outputs to '{visualization_settings.output_dir}'.")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def parse_args():
    """Parse command-line arguments."""
    parser = get_standalone_parser()
    parser.description = (
        "Depth Anything standalone depth estimation using HailoRT Python API. "
        "Supports V1 and V2 models with multiple visualization modes."
    )

    parser.add_argument(
        "--model-version",
        type=str,
        choices=["v1", "v2"],
        default="v2",
        help="Depth Anything model version (default: v2).",
    )
    parser.add_argument(
        "--display-mode",
        type=str,
        choices=["depth", "side-by-side", "overlay"],
        default="depth",
        help="Display mode: depth-only, side-by-side (original + depth), overlay (default: depth).",
    )
    parser.add_argument(
        "--colormap",
        type=str,
        choices=list(COLORMAP_MAP.keys()),
        default="inferno",
        help="Colormap for depth visualization (default: inferno).",
    )
    parser.add_argument(
        "--alpha",
        type=float,
        default=0.5,
        help="Blend alpha for overlay mode, 0.0-1.0 (default: 0.5).",
    )

    args = parser.parse_args()
    return args


def main() -> None:
    """Main entry point."""
    args = parse_args()
    init_logging(level=level_from_args(args))

    # Detect hardware architecture
    arch = detect_hailo_arch()
    if not arch:
        arch = "hailo8"
        logger.warning("Could not detect Hailo architecture, defaulting to %s", arch)

    # Resolve HEF path (auto-download if needed)
    hef_path = get_hef_path(
        args.model_version,
        arch,
        user_hef_path=getattr(args, "hef_path", None),
    )

    logger.info(
        "Depth Anything %s | arch=%s | hef=%s | display=%s | colormap=%s",
        args.model_version.upper(), arch, hef_path,
        args.display_mode, args.colormap,
    )

    # Resolve output directory
    output_dir = args.output_dir
    if output_dir is None:
        output_dir = os.path.join(os.getcwd(), "output")
    os.makedirs(output_dir, exist_ok=True)

    # Resolve input source
    input_context = InputContext(
        input_src=args.input,
        batch_size=args.batch_size,
        resolution=args.camera_resolution,
        frame_rate=args.frame_rate,
        video_unpaced=args.video_unpaced,
    )
    input_context = init_input_source(input_context)

    visualization_settings = VisualizationSettings(
        output_dir=output_dir,
        save_stream_output=args.save_output,
        output_resolution=args.output_resolution,
        no_display=args.no_display,
    )

    run_inference_pipeline(
        hef_path=hef_path,
        input_context=input_context,
        visualization_settings=visualization_settings,
        show_fps=args.show_fps,
        colormap_name=args.colormap,
        display_mode=args.display_mode,
        alpha=args.alpha,
        time_to_run=args.time_to_run,
    )


if __name__ == "__main__":
    main()
