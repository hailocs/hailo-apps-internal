"""Vampire Mirror — a real-time mirror where vampires are invisible.

Uses instance segmentation with ByteTrack tracking to detect people.
The first person detected (track ID 1) is human and visible. All other
people are vampires: their pixels are replaced with the saved background
image, making them disappear from the mirror.
"""

import os
import signal

os.environ["GST_PLUGIN_FEATURE_RANK"] = "vaapidecodebin:NONE"

import gi

gi.require_version("Gst", "1.0")

import cv2
import hailo
import multiprocessing
import numpy as np
from gi.repository import Gst

from hailo_apps.python.core.common.buffer_utils import (
    get_caps_from_pad,
    get_numpy_from_buffer,
)
from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.common.parser import get_pipeline_parser
from hailo_apps.python.core.gstreamer.gstreamer_app import app_callback_class
from hailo_apps.python.pipeline_apps.instance_segmentation.instance_segmentation_pipeline import (
    GStreamerInstanceSegmentationApp,
)

logger = get_logger(__name__)

# Number of initial frames used to capture the background (averaged).
BACKGROUND_CAPTURE_FRAMES = 30


class VampireMirrorCallback(app_callback_class):
    """Per-frame state for the Vampire Mirror app."""

    def __init__(self):
        super().__init__()
        # Increase frame queue size to reduce drops during heavy processing.
        self.frame_queue = multiprocessing.Queue(maxsize=10)
        # Background image (RGB, same size as frame). None until captured.
        self.background: np.ndarray | None = None
        # Accumulator for averaging background frames.
        self._bg_accumulator: np.ndarray | None = None
        self._bg_frame_count: int = 0
        # Set of track IDs that are "human" (visible). By default, only
        # the first person detected is human.
        self.human_ids: set[int] = set()
        self._first_person_assigned: bool = False

    def set_frame(self, frame):
        """Drain stale frames and put the latest one, so display never lags."""
        while not self.frame_queue.empty():
            try:
                self.frame_queue.get_nowait()
            except Exception:
                break
        self.frame_queue.put(frame)


def app_callback(
    element: Gst.Element,
    buffer: Gst.Buffer,
    user_data: VampireMirrorCallback,
) -> Gst.FlowReturn:
    """Per-frame callback: capture background, then apply vampire logic."""
    if buffer is None:
        return Gst.FlowReturn.OK

    pad = element.get_static_pad("src")
    fmt, width, height = get_caps_from_pad(pad)

    if not (user_data.use_frame and fmt and width and height):
        return Gst.FlowReturn.OK

    # Get the current camera frame (RGB).
    frame = get_numpy_from_buffer(buffer, fmt, width, height)
    if frame is None:
        return Gst.FlowReturn.OK

    # ------------------------------------------------------------------
    # Phase 1: Background capture (first N frames)
    # ------------------------------------------------------------------
    if user_data._bg_frame_count < BACKGROUND_CAPTURE_FRAMES:
        if user_data._bg_accumulator is None:
            user_data._bg_accumulator = np.zeros(frame.shape, dtype=np.float64)
        user_data._bg_accumulator += frame.astype(np.float64)
        user_data._bg_frame_count += 1

        if user_data._bg_frame_count == BACKGROUND_CAPTURE_FRAMES:
            user_data.background = (
                user_data._bg_accumulator / BACKGROUND_CAPTURE_FRAMES
            ).astype(np.uint8)
            user_data._bg_accumulator = None  # free memory
            logger.info(
                "Background captured (averaged %d frames).", BACKGROUND_CAPTURE_FRAMES
            )

        # During capture, show frame with a countdown overlay.
        remaining = BACKGROUND_CAPTURE_FRAMES - user_data._bg_frame_count
        overlay = frame.copy()
        cv2.putText(
            overlay,
            f"Capturing background... {remaining}",
            (20, 50),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.2,
            (0, 255, 0),
            3,
        )
        overlay = cv2.cvtColor(overlay, cv2.COLOR_RGB2BGR)
        user_data.set_frame(overlay)
        return Gst.FlowReturn.OK

    # ------------------------------------------------------------------
    # Phase 2: Vampire logic — replace vampire pixels with background
    # ------------------------------------------------------------------
    background = user_data.background
    if background is None:
        # Should not happen after phase 1, but guard anyway.
        return Gst.FlowReturn.OK

    # Start with the live camera frame as the output.
    output = frame.copy()

    roi = hailo.get_roi_from_buffer(buffer)
    detections = roi.get_objects_typed(hailo.HAILO_DETECTION)

    for detection in detections:
        label = detection.get_label()
        if label != "person":
            continue

        # Get track ID.
        track_id = 0
        track = detection.get_objects_typed(hailo.HAILO_UNIQUE_ID)
        if len(track) == 1:
            track_id = track[0].get_id()

        # Auto-assign first person as human.
        if not user_data._first_person_assigned and track_id > 0:
            user_data.human_ids.add(track_id)
            user_data._first_person_assigned = True
            logger.info("Track ID %d assigned as HUMAN (visible).", track_id)

        is_vampire = track_id not in user_data.human_ids

        if not is_vampire:
            # Human: keep original camera pixels (already in output).
            # Remove any hailooverlay drawings for this person by doing nothing
            # extra — the output frame is the raw camera feed.
            continue

        # Vampire: replace their pixels with the background.
        masks = detection.get_objects_typed(hailo.HAILO_CONF_CLASS_MASK)
        if len(masks) == 0:
            # No mask available; fall back to bounding-box fill.
            bbox = detection.get_bbox()
            x_min = max(int(bbox.xmin() * width), 0)
            y_min = max(int(bbox.ymin() * height), 0)
            x_max = min(int((bbox.xmin() + bbox.width()) * width), width)
            y_max = min(int((bbox.ymin() + bbox.height()) * height), height)
            if x_max > x_min and y_max > y_min:
                output[y_min:y_max, x_min:x_max] = background[
                    y_min:y_max, x_min:x_max
                ]
            continue

        mask = masks[0]
        mask_h = mask.get_height()
        mask_w = mask.get_width()
        mask_data = np.array(mask.get_data()).reshape((mask_h, mask_w))

        bbox = detection.get_bbox()
        roi_x = int(bbox.xmin() * width)
        roi_y = int(bbox.ymin() * height)
        roi_w = int(bbox.width() * width)
        roi_h = int(bbox.height() * height)

        # Resize mask to ROI dimensions.
        if roi_w <= 0 or roi_h <= 0:
            continue
        resized_mask = cv2.resize(
            mask_data, (roi_w, roi_h), interpolation=cv2.INTER_LINEAR
        )

        # Clip ROI to frame bounds.
        x1 = max(roi_x, 0)
        y1 = max(roi_y, 0)
        x2 = min(roi_x + roi_w, width)
        y2 = min(roi_y + roi_h, height)

        if x2 <= x1 or y2 <= y1:
            continue

        # Adjust mask slice if ROI was clipped.
        mx1 = x1 - roi_x
        my1 = y1 - roi_y
        mx2 = mx1 + (x2 - x1)
        my2 = my1 + (y2 - y1)

        roi_mask = resized_mask[my1:my2, mx1:mx2]
        binary_mask = (roi_mask > 0.5).astype(np.uint8)
        # Dilate the mask to cover edge artifacts.
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
        binary_mask = cv2.dilate(binary_mask, kernel, iterations=2).astype(bool)

        # Replace vampire pixels with background.
        region_output = output[y1:y2, x1:x2]
        region_bg = background[y1:y2, x1:x2]
        region_output[binary_mask] = region_bg[binary_mask]

    output = cv2.cvtColor(output, cv2.COLOR_RGB2BGR)
    user_data.set_frame(output)
    return Gst.FlowReturn.OK


def _get_track_id(detection: hailo.HailoDetection) -> int:
    """Extract track ID from a detection, or 0 if unavailable."""
    track = detection.get_objects_typed(hailo.HAILO_UNIQUE_ID)
    if len(track) == 1:
        return track[0].get_id()
    return 0


class VampireMirrorApp(GStreamerInstanceSegmentationApp):
    """Vampire Mirror pipeline — instance segmentation + tracker + use_frame."""

    def __init__(self, app_callback_fn, user_data, parser=None):
        if parser is None:
            parser = get_pipeline_parser()
            parser.add_argument(
                "--human-ids",
                type=str,
                default="",
                help=(
                    "Comma-separated track IDs to treat as human (visible). "
                    "If empty, the first detected person is automatically human."
                ),
            )
        super().__init__(app_callback_fn, user_data, parser)

        # Force use_frame so the callback can access and modify frames.
        self.options_menu.use_frame = True
        user_data.use_frame = True

        # Parse --human-ids if provided.
        human_ids_str = getattr(self.options_menu, "human_ids", "")
        if human_ids_str:
            for id_str in human_ids_str.split(","):
                id_str = id_str.strip()
                if id_str.isdigit():
                    user_data.human_ids.add(int(id_str))
                    user_data._first_person_assigned = True
            if user_data.human_ids:
                logger.info("Pre-configured human IDs: %s", user_data.human_ids)


def main():
    """Entry point for the Vampire Mirror app."""
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    logger.info("Starting Vampire Mirror App...")
    user_data = VampireMirrorCallback()
    app = VampireMirrorApp(app_callback, user_data)
    app.run()


if __name__ == "__main__":
    main()
