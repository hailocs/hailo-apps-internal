#!/usr/bin/env python3
"""
Aerial Object Counter - Count and classify objects in aerial/drone images
using oriented (rotated) bounding boxes.

Based on the oriented_object_detection standalone app template.
Uses YOLO11s-OBB model for detecting objects with rotated bounding boxes,
then produces annotated images and a JSON count summary per class per image.

Run with:
    source setup_env.sh
    python -m community.apps.standalone_apps.aerial_object_counter.aerial_object_counter \
        --input /path/to/drone/images/
"""

import argparse
import json
import os
import queue
import threading
from functools import partial
from pathlib import Path

import cv2
import collections
import numpy as np

from hailo_apps.python.core.common.hailo_inference import HailoInfer
from hailo_apps.python.core.common.core import handle_and_resolve_args
from hailo_apps.python.core.common.toolbox import (
    InputContext,
    VisualizationSettings,
    init_input_source,
    get_labels,
    load_json_file,
    preprocess,
    FrameRateTracker,
)
from hailo_apps.python.core.common.defines import (
    MAX_INPUT_QUEUE_SIZE,
    MAX_OUTPUT_QUEUE_SIZE,
    MAX_ASYNC_INFER_JOBS,
)
from hailo_apps.python.core.common.defines import REPO_ROOT
from hailo_apps.python.core.common.parser import get_standalone_parser
from hailo_apps.python.core.common.hailo_logger import get_logger, init_logging, level_from_args
from hailo_apps.python.standalone_apps.oriented_object_detection.oriented_object_detection_post_process import (
    obb_postprocess,
)


# APP_NAME is intentionally "oriented_object_detection": this is load-bearing for
# HEF resolution. handle_and_resolve_args() looks up the resource/model config under
# this name, and this app reuses the OBB model + config from that app.
APP_NAME = "oriented_object_detection"
logger = get_logger(__name__)

# config.json lives alongside the oriented_object_detection package, not this app.
# That package has no __init__.py (it is a namespace package), so resolve its
# directory via __path__ rather than __file__ (which would be None).
import hailo_apps.python.standalone_apps.oriented_object_detection as _obb_pkg
OBB_CONFIG_PATH = str(Path(list(_obb_pkg.__path__)[0]).resolve() / "config.json")


def parse_args() -> argparse.Namespace:
    """Initialize argument parser for the aerial object counter."""
    parser = get_standalone_parser()
    parser.description = "Count and classify objects in aerial/drone images using oriented bounding boxes."
    parser.add_argument(
        "--labels",
        "-l",
        type=str,
        default=str(REPO_ROOT / "local_resources" / "dota.txt"),
        help=(
            "Path to a text file containing class labels, one per line. "
            "Default uses DOTA labels (plane, ship, harbor, etc.)."
        ),
    )
    parser.add_argument(
        "--json-output",
        type=str,
        default=None,
        help=(
            "Path to write JSON count summary. "
            "If not specified, defaults to <output_dir>/count_summary.json."
        ),
    )
    parser.add_argument(
        "--score-threshold",
        type=float,
        default=None,
        help="Override the detection score threshold from config.json.",
    )

    args = parser.parse_args()
    return args


def oriented_object_detection_preprocess(image: np.ndarray, model_w: int, model_h: int, config_data: dict) -> np.ndarray:
    """Letterbox resize with (114,114,114) padding for OBB model input."""
    h0, w0 = image.shape[:2]
    new_w, new_h = model_w, model_h
    r = min(new_w / w0, new_h / h0)
    new_unpad = (int(round(w0 * r)), int(round(h0 * r)))
    dw = (new_w - new_unpad[0]) / 2
    dh = (new_h - new_unpad[1]) / 2

    top = int(round(dh - 0.1))
    bottom = int(round(dh + 0.1))
    left = int(round(dw - 0.1))
    right = int(round(dw + 0.1))

    if new_unpad[1] + top + bottom != new_h:
        bottom = new_h - new_unpad[1] - top
    if new_unpad[0] + left + right != new_w:
        right = new_w - new_unpad[0] - left

    color = (114, 114, 114)
    resized = cv2.resize(image, new_unpad, interpolation=cv2.INTER_LINEAR)
    padded_image = cv2.copyMakeBorder(resized, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color)
    return padded_image


class CountingVisualizer:
    """
    Custom visualizer that counts detections per class per image
    and writes annotated images + JSON summary.
    """

    def __init__(self, labels, config_data, output_dir, json_output_path=None):
        self.labels = labels
        self.config_data = config_data
        self.output_dir = output_dir
        self.json_output_path = json_output_path or os.path.join(output_dir, "count_summary.json")
        self.image_results = []
        self.image_index = 0
        self.lock = threading.Lock()

    def process_frame(self, original_frame, infer_results):
        """Process a single frame: run postprocessing, count, annotate, and store results."""
        from community.apps.standalone_apps.aerial_object_counter.aerial_object_counter_post_process import (
            obb_postprocess,
            draw_counting_overlay,
        )

        kept_boxes, kept_classes, kept_scores = obb_postprocess(
            original_frame, infer_results, self.config_data
        )

        # Count detections per class
        class_counts = {}
        for cls_id in kept_classes:
            label = self.labels[cls_id] if cls_id < len(self.labels) else f"class_{cls_id}"
            class_counts[label] = class_counts.get(label, 0) + 1

        total_count = len(kept_boxes)

        # Draw annotated image with rotated bboxes and count overlay
        annotated = draw_counting_overlay(
            original_frame.copy(), kept_boxes, kept_classes, kept_scores,
            self.labels, class_counts, total_count
        )

        with self.lock:
            self.image_index += 1
            image_name = f"image_{self.image_index:04d}.jpg"

            self.image_results.append({
                "image": image_name,
                "total_objects": total_count,
                "counts_per_class": class_counts,
            })

        return annotated

    def write_json_summary(self):
        """Write the accumulated count summary to a JSON file."""
        # Compute global totals
        global_counts = {}
        global_total = 0
        for entry in self.image_results:
            global_total += entry["total_objects"]
            for cls_name, count in entry["counts_per_class"].items():
                global_counts[cls_name] = global_counts.get(cls_name, 0) + count

        summary = {
            "total_images": len(self.image_results),
            "total_objects": global_total,
            "global_counts_per_class": global_counts,
            "per_image": self.image_results,
        }

        os.makedirs(os.path.dirname(self.json_output_path) or ".", exist_ok=True)
        with open(self.json_output_path, "w") as f:
            json.dump(summary, f, indent=2)

        logger.info(f"Count summary written to: {self.json_output_path}")
        logger.info(f"Total objects detected across {len(self.image_results)} images: {global_total}")
        for cls_name, count in sorted(global_counts.items(), key=lambda x: -x[1]):
            logger.info(f"  {cls_name}: {count}")


def counting_visualize(output_queue, save_output, output_dir,
                       counting_viz, fps_tracker, output_resolution,
                       stop_event, no_display):
    """
    Custom visualization loop that uses CountingVisualizer
    instead of the default postprocess callback.
    """
    while True:
        item = output_queue.get()
        if item is None:
            break
        if stop_event.is_set():
            continue

        original_frame, infer_results = item
        annotated = counting_viz.process_frame(original_frame, infer_results)

        if fps_tracker is not None:
            fps_tracker.tick()

        # Save annotated image
        if save_output:
            os.makedirs(output_dir, exist_ok=True)
            out_path = os.path.join(output_dir, f"annotated_{counting_viz.image_index:04d}.jpg")
            cv2.imwrite(out_path, annotated)

        if not no_display:
            if output_resolution:
                w, h = output_resolution
                annotated = cv2.resize(annotated, (int(w), int(h)))
            cv2.imshow("Aerial Object Counter", annotated)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q') or key == 27:
                stop_event.set()
                break

    if not no_display:
        cv2.destroyAllWindows()


def run_inference_pipeline(
    net,
    labels_file,
    input_context: InputContext,
    visualization_settings: VisualizationSettings,
    json_output_path=None,
    score_threshold=None,
    show_fps=False,
) -> None:
    """Run the aerial object counting inference pipeline."""

    labels = get_labels(labels_file)

    # Load config from the oriented_object_detection package (HEF + tensor mapping).
    config_data = load_json_file(OBB_CONFIG_PATH)

    # Override score threshold if specified
    if score_threshold is not None:
        config_data.setdefault("oriented_postprocess", {})["scores_th"] = score_threshold

    stop_event = threading.Event()
    fps_tracker = None
    if show_fps:
        fps_tracker = FrameRateTracker()

    input_queue = queue.Queue(MAX_INPUT_QUEUE_SIZE)
    output_queue = queue.Queue(MAX_OUTPUT_QUEUE_SIZE)

    preprocess_callback_fn = partial(
        oriented_object_detection_preprocess,
        config_data=config_data,
    )

    hailo_inference = HailoInfer(net, input_context.batch_size, input_type="UINT8", output_type="FLOAT32")
    height, width, _ = hailo_inference.get_input_shape()

    counting_viz = CountingVisualizer(
        labels, config_data, visualization_settings.output_dir, json_output_path
    )

    preprocess_thread = threading.Thread(
        target=preprocess,
        args=(
            input_context,
            input_queue,
            width,
            height,
            preprocess_callback_fn,
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
        counting_visualize(
            output_queue,
            visualization_settings.save_stream_output,
            visualization_settings.output_dir,
            counting_viz,
            fps_tracker,
            visualization_settings.output_resolution,
            stop_event,
            visualization_settings.no_display,
        )
    except KeyboardInterrupt:
        logger.info("Interrupted (Ctrl+C). Shutting down...")
        stop_event.set()
    finally:
        stop_event.set()
        preprocess_thread.join()
        infer_thread.join()

    if show_fps:
        logger.info(fps_tracker.frame_rate_summary())

    # Write the JSON count summary
    counting_viz.write_json_summary()

    logger.success("Processing completed successfully.")
    if visualization_settings.save_stream_output or input_context.has_images:
        logger.info(f"Saved annotated outputs to '{visualization_settings.output_dir}'.")


def infer(hailo_inference, input_queue, output_queue, stop_event):
    """
    Main inference loop that pulls data from the input queue, runs asynchronous
    inference, and pushes results to the output queue.
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


def main() -> None:
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
        labels_file=args.labels,
        input_context=input_context,
        visualization_settings=visualization_settings,
        json_output_path=args.json_output,
        score_threshold=args.score_threshold,
        show_fps=args.show_fps,
    )


if __name__ == "__main__":
    main()
