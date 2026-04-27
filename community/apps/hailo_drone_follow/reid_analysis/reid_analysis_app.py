#!/usr/bin/env python3
"""
ReID Video Analysis App
=======================
Uses GStreamerTilingApp (same as drone_follow) for person detection with
Hailo NPU tiling pipeline. Extracts ReID embeddings, matches against a
gallery using pluggable strategies, and logs every match decision for
offline evaluation.

Usage:
    source setup_env.sh
    python reid_analysis/reid_analysis_app.py \
        --input 12354541-hd_1280_720_25fps.mp4 \
        --tiles-x 2 --tiles-y 3 \
        --reid-model repvgg --reid-match-threshold 0.7 \
        --gallery-strategy first_only
"""

import atexit
import json
import os
import signal
import shutil
import threading
from pathlib import Path

import cv2
import hailo
import numpy as np

from hailo_apps.python.core.common.buffer_utils import get_caps_from_pad, get_numpy_from_buffer
from hailo_apps.python.core.common.core import get_pipeline_parser
from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.gstreamer.gstreamer_app import app_callback_class
from hailo_apps.python.pipeline_apps.tiling.tiling_pipeline import GStreamerTilingApp

from reid_analysis.gallery_strategies import STRATEGIES, create_strategy
from reid_analysis.reid_embedding_extractor import OSNetExtractor, RepVGG512Extractor

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# User data — shared between callback and main thread
# ---------------------------------------------------------------------------

class ReIDUserData(app_callback_class):
    def __init__(self, reid_extractor, gallery, output_dir, reid_match_threshold, match_log_path):
        super().__init__()
        self.reid_extractor = reid_extractor
        self.gallery = gallery
        self.reid_match_threshold = reid_match_threshold

        self.orig_dir = Path(output_dir) / "orig_person_images"
        self.match_dir = Path(output_dir) / "person_images"
        # Clean previous run results
        if self.orig_dir.exists():
            shutil.rmtree(self.orig_dir)
        if self.match_dir.exists():
            shutil.rmtree(self.match_dir)
        self.orig_dir.mkdir(parents=True, exist_ok=True)
        self.match_dir.mkdir(parents=True, exist_ok=True)

        self.total_crops = 0
        self._lock = threading.Lock()

        # Match log — JSONL file for offline evaluation
        self._log_file = open(match_log_path, "w")
        atexit.register(self.close_log)

    def log_match(self, entry: dict):
        self._log_file.write(json.dumps(entry) + "\n")

    def close_log(self):
        if self._log_file and not self._log_file.closed:
            self._log_file.close()


# ---------------------------------------------------------------------------
# Pipeline callback
# ---------------------------------------------------------------------------

def app_callback(element, buffer, user_data):
    if buffer is None:
        return

    frame_count = user_data.get_count()

    # Extract person detections from Hailo metadata
    roi = hailo.get_roi_from_buffer(buffer)
    detections = roi.get_objects_typed(hailo.HAILO_DETECTION)
    persons = [d for d in detections if d.get_label() == "person"]

    if not persons:
        return

    # Extract frame as numpy array
    pad = element.get_static_pad("src")
    fmt, width, height = get_caps_from_pad(pad)
    frame = get_numpy_from_buffer(buffer, fmt, width, height)
    if frame is None:
        return

    # Convert RGB to BGR for OpenCV
    if fmt == "RGB":
        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    else:
        frame_bgr = frame

    # Crop persons from frame using normalized bbox coordinates
    crops = []
    for person in persons:
        bbox = person.get_bbox()
        x1 = max(0, int(bbox.xmin() * width))
        y1 = max(0, int(bbox.ymin() * height))
        x2 = min(width, int((bbox.xmin() + bbox.width()) * width))
        y2 = min(height, int((bbox.ymin() + bbox.height()) * height))
        if x2 > x1 and y2 > y1:
            crops.append(frame_bgr[y1:y2, x1:x2].copy())

    if not crops:
        return

    # Extract ReID embeddings
    embeddings = user_data.reid_extractor.extract_embeddings_batch(crops)

    with user_data._lock:
        for j, (crop, emb) in enumerate(zip(crops, embeddings)):
            user_data.total_crops += 1
            gallery = user_data.gallery

            if gallery.size == 0:
                # First person ever
                name = f"person_{gallery.size}"
                gallery.add_person(name, emb)
                _save_new_person(user_data, name, crop, frame_count)
                user_data.log_match({
                    "frame": frame_count, "crop_idx": j,
                    "predicted_id": name, "similarity": 1.0, "is_new": True,
                })
                logger.debug("Frame %d: new %s (first detection)", frame_count, name)
            else:
                matched_name, best_sim = gallery.match(emb, user_data.reid_match_threshold)

                if matched_name is not None:
                    # Matched existing person
                    gallery.update(matched_name, emb, frame_count)
                    save_path = user_data.match_dir / matched_name / f"frame_{frame_count:04d}.jpg"
                    cv2.imwrite(str(save_path), crop)
                    user_data.log_match({
                        "frame": frame_count, "crop_idx": j,
                        "predicted_id": matched_name, "similarity": round(best_sim, 4),
                        "is_new": False,
                    })
                else:
                    # New person
                    name = f"person_{gallery.size}"
                    gallery.add_person(name, emb)
                    _save_new_person(user_data, name, crop, frame_count)
                    user_data.log_match({
                        "frame": frame_count, "crop_idx": j,
                        "predicted_id": name, "similarity": round(best_sim, 4),
                        "is_new": True,
                    })
                    logger.debug(
                        "Frame %d: new %s (best match %.3f < %.2f)",
                        frame_count, name, best_sim, user_data.reid_match_threshold,
                    )

    if frame_count % 100 == 0:
        logger.info("Frame %d processed, %d total crops", frame_count, user_data.total_crops)


def _save_new_person(user_data, name, crop, frame_count):
    """Save reference image and first crop for a new person."""
    cv2.imwrite(str(user_data.orig_dir / f"{name}.jpg"), crop)
    person_dir = user_data.match_dir / name
    person_dir.mkdir(exist_ok=True)
    cv2.imwrite(str(person_dir / f"frame_{frame_count:04d}.jpg"), crop)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = get_pipeline_parser()
    parser.add_argument("--reid-model", type=str, choices=["repvgg", "osnet"], default="repvgg",
                        help="ReID model to use")
    parser.add_argument("--reid-match-threshold", type=float, default=0.7,
                        help="Cosine similarity threshold for ReID matching")
    parser.add_argument("--output-dir", type=str,
                        default=os.path.dirname(os.path.abspath(__file__)),
                        help="Base output directory")
    parser.add_argument("--gallery-strategy", type=str, choices=list(STRATEGIES.keys()),
                        default="first_only", help="Gallery update strategy")
    parser.add_argument("--gallery-update-interval", type=int, default=10,
                        help="Update interval for update_every_n strategy")
    parser.add_argument("--gallery-max-size", type=int, default=10,
                        help="Max embeddings per person for multi_embedding strategy")

    args, _ = parser.parse_known_args()

    # Init ReID extractor
    logger.info("Loading ReID model: %s", args.reid_model)
    if args.reid_model == "repvgg":
        reid_extractor = RepVGG512Extractor()
    else:
        reid_extractor = OSNetExtractor()
    logger.info("ReID: %s, dim=%d", reid_extractor.model_name, reid_extractor.embedding_dim)

    # Init gallery strategy
    strategy_kwargs = {}
    if args.gallery_strategy == "update_every_n":
        strategy_kwargs["n"] = args.gallery_update_interval
    elif args.gallery_strategy == "multi_embedding":
        strategy_kwargs["max_k"] = args.gallery_max_size
    gallery = create_strategy(args.gallery_strategy, **strategy_kwargs)
    logger.info("Gallery strategy: %s", args.gallery_strategy)

    # Match log path
    output_dir = Path(args.output_dir)
    match_log_path = output_dir / "match_log.jsonl"

    # Create user data
    user_data = ReIDUserData(
        reid_extractor=reid_extractor,
        gallery=gallery,
        output_dir=args.output_dir,
        reid_match_threshold=args.reid_match_threshold,
        match_log_path=str(match_log_path),
    )

    # Subclass to stop on EOS instead of looping the video
    class ReIDTilingApp(GStreamerTilingApp):
        def on_eos(self):
            self.shutdown()

    # Create and run tiling pipeline app
    app = ReIDTilingApp(app_callback, user_data, parser=parser)

    # Signal handling — set flag only, cleanup happens in finally
    shutdown_requested = False

    def _signal_handler(sig, frame):
        nonlocal shutdown_requested
        if not shutdown_requested:
            logger.info("Signal received, shutting down...")
            shutdown_requested = True
            app.shutdown()

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    try:
        app.run()
    finally:
        user_data.close_log()
        reid_extractor.release()

    # Summary
    logger.info("Done!")
    logger.info("Total person crops saved: %d", user_data.total_crops)
    logger.info("Unique persons found: %d", gallery.size)
    logger.info("Match log: %s", match_log_path)
    logger.info("First-seen crops: %s/", user_data.orig_dir)
    for name in gallery.names:
        person_dir = user_data.match_dir / name
        n_crops = len(list(person_dir.glob("*.jpg")))
        logger.info("  %s: %d crops in %s/", name, n_crops, person_dir)


if __name__ == "__main__":
    main()
