"""Vampire Mirror v2 — face-recognition-powered invisible vampires.

A real-time mirror where enrolled "vampires" are invisible. Uses instance
segmentation for pixel-accurate person masks and a dynamic background that
continuously adapts. The display is a portrait center crop from a wider
landscape capture, providing a buffer zone for identifying people before
they enter the visible mirror area.

Face recognition is not yet wired — all persons are currently visible.

Usage:
    python community/apps/pipeline_apps/vampire_mirror/vampire_mirror.py --input usb --width 1280 --height 720
"""

import os
import signal
import sys

# Ensure repo root is on sys.path so `community.*` imports work when
# the script is executed directly (e.g. `python vampire_mirror.py`).
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

os.environ["GST_PLUGIN_FEATURE_RANK"] = "vaapidecodebin:NONE"

import cv2
import hailo
import multiprocessing
import numpy as np

from hailo_apps.python.core.common.buffer_utils import (
    get_caps_from_pad,
    get_numpy_from_buffer,
)
from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.gstreamer.gstreamer_app import app_callback_class

from community.apps.pipeline_apps.vampire_mirror.vampire_mirror_pipeline import VampireMirrorPipeline
from community.apps.pipeline_apps.vampire_mirror.frame_geometry import FrameGeometry
from community.apps.pipeline_apps.vampire_mirror.background_manager import BackgroundManager
from community.apps.pipeline_apps.vampire_mirror.vampire_engine import VampireEngine, TrackState

logger = get_logger(__name__)


class VampireMirrorCallback(app_callback_class):
    """Per-frame state for Vampire Mirror v2."""

    def __init__(self):
        super().__init__()
        self.frame_queue = multiprocessing.Queue(maxsize=5)

        # Modules — initialized after pipeline construction
        self.frame_geometry: FrameGeometry | None = None
        self.bg_manager: BackgroundManager | None = None
        self.engine: VampireEngine | None = None

        # Pipeline options — set by main() after pipeline construction
        self.mirror_ratio_str: str = "9:16"

    def set_frame(self, frame: np.ndarray):
        """Replace queued frame with latest (drop stale)."""
        while not self.frame_queue.empty():
            try:
                self.frame_queue.get_nowait()
            except Exception:
                break
        self.frame_queue.put(frame)


def _get_track_id(detection) -> int:
    """Extract ByteTrack ID from a detection."""
    tracks = detection.get_objects_typed(hailo.HAILO_UNIQUE_ID)
    return tracks[0].get_id() if len(tracks) == 1 else 0


def app_callback(element, buffer, user_data: VampireMirrorCallback):
    """Per-frame callback."""
    if buffer is None:
        return 1  # Gst.FlowReturn.OK

    pad = element.get_static_pad("src")
    fmt, width, height = get_caps_from_pad(pad)
    if not (user_data.use_frame and fmt and width and height):
        return 1

    frame = get_numpy_from_buffer(buffer, fmt, width, height)
    if frame is None:
        return 1

    bg_manager = user_data.bg_manager
    engine = user_data.engine
    geometry = user_data.frame_geometry

    # --- Deferred geometry init (need actual frame dimensions) ---
    if geometry is None:
        ratio_parts = user_data.mirror_ratio_str.split(":")
        mirror_ratio = (int(ratio_parts[0]), int(ratio_parts[1]))
        geometry = FrameGeometry(width, height, mirror_ratio=mirror_ratio)
        user_data.frame_geometry = geometry
        logger.info(
            "FrameGeometry: frame=%dx%d, mirror=%dx%d, crop_x=%d..%d",
            width, height, geometry.mirror_width, geometry.mirror_height,
            geometry.crop_x1, geometry.crop_x2,
        )

    # --- Phase 1: Background capture ---
    if not bg_manager.is_ready:
        remaining = bg_manager.frames_remaining
        bg_manager.update(frame)
        overlay = frame.copy()
        cv2.putText(
            overlay, f"Capturing background... {remaining}",
            (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2,
        )
        cropped = geometry.center_crop(overlay)
        user_data.set_frame(cv2.cvtColor(cropped, cv2.COLOR_RGB2BGR))
        return 1

    # --- Phase 2: Vampire logic ---
    background = bg_manager.background.astype(np.uint8)  # float32 → uint8
    output = frame.copy()
    combined_vampire_mask = np.zeros((height, width), dtype=bool)

    roi = hailo.get_roi_from_buffer(buffer)
    detections = roi.get_objects_typed(hailo.HAILO_DETECTION)

    for detection in detections:
        if detection.get_label() != "person":
            continue

        track_id = _get_track_id(detection)
        if track_id == 0:
            continue

        bbox = detection.get_bbox()
        # Convert normalized bbox to pixel coords for is_in_mirror
        px_xmin = bbox.xmin() * width
        px_width = bbox.width() * width
        in_mirror = geometry.is_in_mirror(px_xmin, px_width, width)

        # Face recognition placeholder: always None for now
        face_match = None
        face_detected = False

        state = engine.decide(
            track_id=track_id,
            in_mirror=in_mirror,
            face_match=face_match,
            face_detected=face_detected,
        )

        if state != TrackState.VAMPIRE:
            continue

        # --- Replace vampire pixels with background ---
        px1 = max(int(bbox.xmin() * width), 0)
        py1 = max(int(bbox.ymin() * height), 0)
        px2 = min(int((bbox.xmin() + bbox.width()) * width), width)
        py2 = min(int((bbox.ymin() + bbox.height()) * height), height)

        masks = detection.get_objects_typed(hailo.HAILO_CONF_CLASS_MASK)
        if len(masks) == 0:
            # Fallback: fill bounding box
            if px2 > px1 and py2 > py1:
                output[py1:py2, px1:px2] = background[py1:py2, px1:px2]
                combined_vampire_mask[py1:py2, px1:px2] = True
            continue

        mask = masks[0]
        mask_data = np.array(mask.get_data()).reshape(mask.get_height(), mask.get_width())

        roi_w = px2 - px1
        roi_h = py2 - py1
        if roi_w <= 0 or roi_h <= 0:
            continue

        resized_mask = cv2.resize(mask_data, (roi_w, roi_h), interpolation=cv2.INTER_LINEAR)

        # Clip to frame bounds
        x1 = max(px1, 0)
        y1 = max(py1, 0)
        x2 = min(px1 + roi_w, width)
        y2 = min(py1 + roi_h, height)
        if x2 <= x1 or y2 <= y1:
            continue

        mx1 = x1 - px1
        my1 = y1 - py1
        mx2 = mx1 + (x2 - x1)
        my2 = my1 + (y2 - y1)

        roi_mask = resized_mask[my1:my2, mx1:mx2]
        binary_mask = (roi_mask > 0.5).astype(np.uint8)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
        binary_mask = cv2.dilate(binary_mask, kernel, iterations=2).astype(bool)

        output[y1:y2, x1:x2][binary_mask] = background[y1:y2, x1:x2][binary_mask]
        combined_vampire_mask[y1:y2, x1:x2] |= binary_mask

    # --- Update dynamic background ---
    vampire_mask = combined_vampire_mask if combined_vampire_mask.any() else None
    bg_manager.update(frame, vampire_mask=vampire_mask)

    # --- Center crop and display ---
    cropped = geometry.center_crop(output)
    user_data.set_frame(cv2.cvtColor(cropped, cv2.COLOR_RGB2BGR))
    return 1


def main():
    """Entry point for Vampire Mirror v2."""
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    logger.info("Starting Vampire Mirror v2...")

    user_data = VampireMirrorCallback()
    app = VampireMirrorPipeline(app_callback, user_data)
    opts = app.options_menu

    # Store options for deferred init
    user_data.mirror_ratio_str = opts.mirror_ratio

    # Initialize modules
    user_data.bg_manager = BackgroundManager(
        capture_frames=opts.bg_capture_frames,
        alpha=opts.bg_alpha,
    )
    user_data.engine = VampireEngine()

    logger.info(
        "Config: mirror_ratio=%s, bg_alpha=%.3f, bg_capture_frames=%d",
        opts.mirror_ratio, opts.bg_alpha, opts.bg_capture_frames,
    )

    app.run()


if __name__ == "__main__":
    main()
