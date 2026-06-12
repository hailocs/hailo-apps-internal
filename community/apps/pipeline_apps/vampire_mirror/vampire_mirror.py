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
import numpy as np

# Precomputed once — used for every per-detection mask dilation.
_DILATION_KERNEL = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))

from hailo_apps.python.core.common.buffer_utils import (
    get_caps_from_pad,
    get_numpy_from_buffer,
)
from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.gstreamer.gstreamer_app import app_callback_class

from community.apps.pipeline_apps.vampire_mirror.vampire_mirror_pipeline import VampireMirrorPipeline
from community.apps.pipeline_apps.vampire_mirror.frame_geometry import FrameGeometry, detect_vertical_padding
from community.apps.pipeline_apps.vampire_mirror.background_manager import BackgroundManager
from community.apps.pipeline_apps.vampire_mirror.vampire_engine import VampireEngine, TrackState

logger = get_logger(__name__)


class VampireMirrorCallback(app_callback_class):
    """Per-frame state for Vampire Mirror v2."""

    def __init__(self):
        super().__init__()

        # Modules — initialized after pipeline construction
        self.frame_geometry: FrameGeometry | None = None
        self.bg_manager: BackgroundManager | None = None
        # Forward-reference (import deferred to main() conditional on --bg-process).
        self.bg_service: "BackgroundService | None" = None
        self.engine: VampireEngine | None = None

        # Pipeline options — set by main() after pipeline construction
        self.mirror_ratio_str: str = "9:16"


def _get_track_id(detection) -> int:
    """Extract ByteTrack ID from a detection."""
    tracks = detection.get_objects_typed(hailo.HAILO_UNIQUE_ID)
    return tracks[0].get_id() if len(tracks) == 1 else 0


def _build_person_mask(detections, width: int, height: int) -> np.ndarray | None:
    """Union of all person segmentation masks in pixel space. Returns None if no persons."""
    out = None
    for det in detections:
        if det.get_label() != "person":
            continue
        masks = det.get_objects_typed(hailo.HAILO_CONF_CLASS_MASK)
        if not masks:
            continue
        bbox = det.get_bbox()
        px1 = max(int(bbox.xmin() * width), 0)
        py1 = max(int(bbox.ymin() * height), 0)
        px2 = min(int((bbox.xmin() + bbox.width()) * width), width)
        py2 = min(int((bbox.ymin() + bbox.height()) * height), height)
        if px2 <= px1 or py2 <= py1:
            continue
        mask = masks[0]
        mask_data = np.array(mask.get_data()).reshape(mask.get_height(), mask.get_width())
        resized = cv2.resize(mask_data, (px2 - px1, py2 - py1), interpolation=cv2.INTER_LINEAR)
        binary = cv2.dilate((resized > 0.5).astype(np.uint8), _DILATION_KERNEL, iterations=2).astype(bool)
        if out is None:
            out = np.zeros((height, width), dtype=bool)
        out[py1:py2, px1:px2] |= binary
    return out


def app_callback(element, buffer, user_data: VampireMirrorCallback):
    """Per-frame callback.

    Responsibilities (Task 9+):
      - Build the union person_mask and submit it to the background service so
        the EMA adapts only to non-person pixels.
      - Run VampireEngine.decide() per tracked person.
      - Attach a HailoClassification(type="vampire") tag to detections that
        should be invisibilised.  The C++ hailovampire_overlay element reads
        these tags and paints the corresponding pixels from the shared-memory
        background buffer.

    The frame is NOT modified by this callback — drawing happens in C++.
    """
    if buffer is None:
        return 1  # Gst.FlowReturn.OK

    pad = element.get_static_pad("src")
    fmt, width, height = get_caps_from_pad(pad)
    if not (user_data.use_frame and fmt and width and height):
        return 1

    frame = get_numpy_from_buffer(buffer, fmt, width, height)
    if frame is None:
        return 1

    bg_service = getattr(user_data, "bg_service", None)
    bg_manager = user_data.bg_manager
    engine = user_data.engine
    geometry = user_data.frame_geometry

    # --- Deferred geometry init (need actual frame dimensions) ---
    if geometry is None:
        ratio_parts = user_data.mirror_ratio_str.split(":")
        mirror_ratio = (int(ratio_parts[0]), int(ratio_parts[1]))
        vertical_pad = detect_vertical_padding(frame)
        geometry = FrameGeometry(
            width, height,
            mirror_ratio=mirror_ratio,
            vertical_pad=vertical_pad,
            vertical_margin=5,
        )
        user_data.frame_geometry = geometry
        logger.info(
            "FrameGeometry: frame=%dx%d, pad=%d, mirror=%dx%d, "
            "crop_x=%d..%d, crop_y=%d..%d",
            width, height, vertical_pad,
            geometry.mirror_width, geometry.mirror_height,
            geometry.crop_x1, geometry.crop_x2,
            geometry.crop_y1, geometry.crop_y2,
        )

    roi = hailo.get_roi_from_buffer(buffer)
    all_detections = roi.get_objects_typed(hailo.HAILO_DETECTION)

    # Vampire mirror is a person-only app: drop every non-person detection from
    # the ROI before any downstream logic runs. This guarantees the C++ overlay
    # (hailovampire_overlay), the bbox/segmentation overlay (hailooverlay), and
    # the bg-update mask never accidentally treat a chair/cup/etc. as a person.
    detections = []
    for det in all_detections:
        if det.get_label() == "person":
            detections.append(det)
        else:
            roi.remove_object(det)

    person_mask = _build_person_mask(detections, width, height)

    # --- Service path (preferred) ---
    if bg_service is not None:
        bg_service.submit_frame(frame, person_mask=person_mask)
        if not bg_service.is_ready():
            # During capture phase: skip vampire tagging.  The C++ overlay
            # won't see any vampire classifications so it renders the original
            # frame unchanged — which is correct while the background is being
            # captured.
            return 1
    else:
        # --- Legacy in-process path ---
        if not bg_manager.is_ready:
            bg_manager.update(frame)
            return 1
        # Update background after processing (non-vampire pixels only)
        bg_manager.update(frame, person_mask=person_mask)

    # --- Per-detection: decide state and tag vampires ---
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

        # Tag for the C++ overlay element. class_id=0, label="", confidence=0
        # because the C++ side only checks the classification *type* string.
        vampire_cls = hailo.HailoClassification("vampire", 0, "", 0.0)
        detection.add_object(vampire_cls)

    # Frame is unchanged by the callback. The C++ overlay paints vampire
    # pixels; the display sink shows whatever the C++ element outputs.
    return 1


def main():
    """Entry point for Vampire Mirror v2."""
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    logger.info("Starting Vampire Mirror v2...")

    user_data = VampireMirrorCallback()

    # Construct the pipeline (deferred: create_pipeline() is NOT called yet
    # because VampireMirrorPipeline.__init__ sets _defer_pipeline_creation=True).
    app = VampireMirrorPipeline(app_callback, user_data)
    opts = app.options_menu

    # Store options for deferred init
    user_data.mirror_ratio_str = opts.mirror_ratio

    # Resolve width/height with same defaults as pipeline
    bg_width = opts.width if opts.width else 1280
    bg_height = opts.height if opts.height else 720

    # Initialize background module
    if opts.bg_process:
        # Late import: only pull in multiprocessing machinery when --bg-process is on.
        from community.apps.pipeline_apps.vampire_mirror.bg_service import BackgroundService
        bg_service = BackgroundService(
            width=bg_width,
            height=bg_height,
            channels=3,
            capture_frames=opts.bg_capture_frames,
            alpha=opts.bg_alpha,
        )
        bg_service.start()
        user_data.bg_service = bg_service
        user_data.bg_manager = None

        # Plumb shm names into the pipeline string (consumed by get_pipeline_string).
        app.vampire_bg_shm_a = f"{bg_service.shm_prefix}bg_a"
        app.vampire_bg_shm_b = f"{bg_service.shm_prefix}bg_b"
        app.vampire_bg_shm_idx = f"{bg_service.shm_prefix}idx"
        app.vampire_bg_w = bg_width
        app.vampire_bg_h = bg_height
    else:
        user_data.bg_service = None
        user_data.bg_manager = BackgroundManager(
            capture_frames=opts.bg_capture_frames,
            alpha=opts.bg_alpha,
        )
    user_data.engine = VampireEngine()

    logger.info(
        "Config: mirror_ratio=%s, bg_alpha=%.3f, bg_capture_frames=%d, bg_process=%s",
        opts.mirror_ratio, opts.bg_alpha, opts.bg_capture_frames, opts.bg_process,
    )

    # Now that shm attrs are set, build the GStreamer pipeline.
    app.create_pipeline()

    try:
        app.run()
    finally:
        if user_data.bg_service is not None:
            user_data.bg_service.stop()


if __name__ == "__main__":
    main()
