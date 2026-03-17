#!/usr/bin/env python3
"""
Lane Departure Warning System

Processes dashcam video through UFLD v2 lane detection on Hailo-8, analyzes
the vehicle's lateral position relative to detected lanes, and generates an
annotated output video with departure warnings plus a text summary of all
departure events.

Based on the lane_detection standalone app template.
"""

import multiprocessing as mp
import sys
import os
import json
from functools import partial
from pathlib import Path
import numpy as np
import cv2
import threading
import argparse
import collections

from lane_departure_warning_utils import (
    UFLDProcessing,
    DepartureDetector,
    compute_scaled_radius,
    draw_departure_overlay,
)

try:
    from hailo_apps.python.core.common.hailo_logger import get_logger, init_logging, level_from_args
    from hailo_apps.python.core.common.hailo_inference import HailoInfer
    from hailo_apps.python.core.common.core import handle_and_resolve_args
    from hailo_apps.python.core.common.parser import get_standalone_parser
    from hailo_apps.python.core.common.defines import (
        MAX_INPUT_QUEUE_SIZE,
        MAX_OUTPUT_QUEUE_SIZE,
        MAX_ASYNC_INFER_JOBS,
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
    from hailo_apps.python.core.common.defines import (
        MAX_INPUT_QUEUE_SIZE,
        MAX_OUTPUT_QUEUE_SIZE,
        MAX_ASYNC_INFER_JOBS,
    )

APP_NAME = "lane_detection"  # Reuse lane_detection resources config
logger = get_logger(__name__)


def parser_init():
    """Parse command-line arguments for the lane departure warning app."""
    parser = get_standalone_parser()
    parser.description = "Lane Departure Warning System using UFLD v2 on Hailo"
    parser.add_argument(
        "--departure-threshold", type=float, default=0.15,
        help=(
            "Fractional offset from lane center that triggers a departure "
            "warning (0.0-0.5). Default: 0.15"
        ),
    )
    parser.add_argument(
        "--smoothing-window", type=int, default=5,
        help="Number of frames to average for offset smoothing. Default: 5",
    )
    return parser.parse_args()


def get_video_info(video_path):
    """
    Get video dimensions and frame count.

    Args:
        video_path (str): Path to the input video file.

    Returns:
        tuple: (frame_width, frame_height, frame_count, fps)
    """
    vidcap = cv2.VideoCapture(video_path)
    if not vidcap.isOpened():
        vidcap.release()
        logger.error(f"Cannot open video file {video_path}")
        raise ValueError(f"Cannot open video file {video_path}")
    frame_width = int(vidcap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_height = int(vidcap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frame_count = int(vidcap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = vidcap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        fps = 30.0
    vidcap.release()
    return frame_width, frame_height, frame_count, fps


def preprocess_input(video_path, input_queue, width, height, ufld_processing):
    """Read video frames, preprocess, and enqueue for inference."""
    vidcap = cv2.VideoCapture(video_path)
    success, frame = vidcap.read()

    while success:
        resized_frame = ufld_processing.resize(frame, height, width)
        input_queue.put(([frame], [resized_frame]))
        success, frame = vidcap.read()

    input_queue.put(None)


def postprocess_output(output_queue, output_dir, ufld_processing,
                        departure_detector, total_frames, fps):
    """
    Post-process inference results: detect lanes, analyze departure, write
    annotated video and departure summary.
    """
    from tqdm import tqdm

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    width, height = ufld_processing.get_original_frame_size()
    out_path = os.path.join(output_dir, "output_departure_warning.mp4")
    output_video = cv2.VideoWriter(out_path, fourcc, int(fps), (width, height))

    radius = compute_scaled_radius(width, height)
    pbar = tqdm(total=total_frames, desc="Processing frames")

    while True:
        result = output_queue.get()
        if result is None:
            break

        original_frame, inference_output = result
        slices = list(inference_output.values())
        output_tensor = np.concatenate(slices, axis=1)
        lanes = ufld_processing.get_coordinates(output_tensor)

        # Analyze departure
        analysis = departure_detector.analyze_lanes(lanes)

        # Draw overlays
        annotated_frame = draw_departure_overlay(
            original_frame, analysis, lanes, radius)

        output_video.write(annotated_frame.astype('uint8'))
        pbar.update(1)

    pbar.close()
    output_video.release()

    # Convert to H.264 for better compatibility
    import subprocess
    logger.info("Converting video to H.264 format...")
    temp_path = out_path.replace('.mp4', '_temp.mp4')
    try:
        subprocess.run([
            'ffmpeg', '-y', '-loglevel', 'error', '-i', out_path,
            '-c:v', 'libx264', '-preset', 'medium', '-crf', '23',
            temp_path
        ], check=True, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        os.replace(temp_path, out_path)
        logger.info("Video conversion complete!")
    except subprocess.CalledProcessError:
        logger.warning("Failed to convert video to H.264")
        if os.path.exists(temp_path):
            os.remove(temp_path)
    except FileNotFoundError:
        logger.warning("ffmpeg not found, keeping original mp4v format")

    # Write departure summary
    summary = departure_detector.get_summary()
    summary_path = os.path.join(output_dir, "departure_summary.json")
    with open(summary_path, 'w') as f:
        json.dump(summary, f, indent=2)
    logger.info(f"Departure summary saved to {summary_path}")

    # Print summary to console
    logger.info("=" * 60)
    logger.info("LANE DEPARTURE WARNING SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Total frames analyzed: {summary['total_frames']}")
    logger.info(f"Total departure events: {summary['total_departures']}")
    logger.info(f"  Left departures:  {summary['left_departures']}")
    logger.info(f"  Right departures: {summary['right_departures']}")
    if summary['events']:
        logger.info("Departure events:")
        for event in summary['events']:
            frame_time = event['frame'] / fps
            logger.info(
                f"  Frame {event['frame']} ({frame_time:.1f}s): "
                f"{event['direction']} departure (offset: {event['offset']:.3f})")
    logger.info("=" * 60)


def inference_callback(completion_info, bindings_list, input_batch,
                        output_queue):
    """Handle inference results and push to output queue."""
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


def infer(hailo_inference, input_queue, output_queue):
    """Main inference loop: pull from input queue, run async inference."""
    pending_jobs = collections.deque()

    while True:
        next_batch = input_queue.get()
        if not next_batch:
            break

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


def run_inference_pipeline(video_path, net_path, batch_size, output_dir,
                            ufld_processing, departure_detector,
                            total_frames, fps):
    """
    Run the lane departure warning pipeline: preprocess -> infer -> postprocess.
    """
    input_queue = mp.Queue(MAX_INPUT_QUEUE_SIZE)
    output_queue = mp.Queue(MAX_OUTPUT_QUEUE_SIZE)
    hailo_inference = HailoInfer(net_path, batch_size, output_type="FLOAT32")

    preprocessed_frame_height, preprocessed_frame_width, _ = (
        hailo_inference.get_input_shape())

    preprocess_thread = threading.Thread(
        target=preprocess_input,
        args=(video_path, input_queue, preprocessed_frame_width,
              preprocessed_frame_height, ufld_processing),
    )
    postprocess_thread = threading.Thread(
        target=postprocess_output,
        args=(output_queue, output_dir, ufld_processing,
              departure_detector, total_frames, fps),
    )
    infer_thread = threading.Thread(
        target=infer, args=(hailo_inference, input_queue, output_queue),
    )

    preprocess_thread.start()
    postprocess_thread.start()
    infer_thread.start()

    infer_thread.join()
    preprocess_thread.join()
    postprocess_thread.join()

    logger.success(
        f"Lane departure warning analysis complete! Results saved in {output_dir}")


def main():
    """Entry point for the lane departure warning application."""
    args = parser_init()
    init_logging(level=level_from_args(args))
    handle_and_resolve_args(args, APP_NAME)

    try:
        original_frame_width, original_frame_height, total_frames, fps = (
            get_video_info(args.input))
    except ValueError as e:
        logger.error(e)
        sys.exit(1)

    ufld_processing = UFLDProcessing(
        num_cell_row=100,
        num_cell_col=100,
        num_row=56,
        num_col=41,
        num_lanes=4,
        crop_ratio=0.8,
        original_frame_width=original_frame_width,
        original_frame_height=original_frame_height,
        total_frames=total_frames,
    )

    departure_detector = DepartureDetector(
        frame_width=original_frame_width,
        frame_height=original_frame_height,
        departure_threshold=args.departure_threshold,
        smoothing_window=args.smoothing_window,
    )

    run_inference_pipeline(
        args.input,
        args.hef_path,
        batch_size=args.batch_size,
        output_dir=args.output_dir,
        ufld_processing=ufld_processing,
        departure_detector=departure_detector,
        total_frames=total_frames,
        fps=fps,
    )


if __name__ == "__main__":
    main()
