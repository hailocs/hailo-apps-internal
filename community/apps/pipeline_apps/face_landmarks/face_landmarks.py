"""Face Landmarks Detection — 468-point face mesh on Hailo.

Two pipeline modes:
  --pipeline-mode gstreamer (default): Full GStreamer cascade. Both SCRFD and
      face_landmarks_lite run as hailonet elements. Landmarks arrive as
      HAILO_LANDMARKS metadata — maximum throughput, minimum CPU.
  --pipeline-mode python: SCRFD in GStreamer, face_landmarks_lite via InferVStreams
      in the Python callback. More flexible for custom processing.

Usage:
    python -m community.apps.pipeline_apps.face_landmarks.face_landmarks
    python -m community.apps.pipeline_apps.face_landmarks.face_landmarks --input usb
    python -m community.apps.pipeline_apps.face_landmarks.face_landmarks --pipeline-mode python
"""

import math
import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

os.environ["GST_PLUGIN_FEATURE_RANK"] = "vaapidecodebin:NONE"

import signal
import multiprocessing

import cv2
import hailo
import numpy as np
from hailo_platform import (
    HEF,
    VDevice,
    InferVStreams,
    InputVStreamParams,
    OutputVStreamParams,
    FormatType,
)

from hailo_apps.python.core.common.buffer_utils import get_caps_from_pad, get_numpy_from_buffer
from hailo_apps.python.core.common.defines import SHARED_VDEVICE_GROUP_ID
from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.gstreamer.gstreamer_app import app_callback_class

from community.apps.pipeline_apps.face_landmarks.face_landmarks_pipeline import (
    GStreamerFaceLandmarksApp,
)

logger = get_logger(__name__)

# Face mesh input resolution
LANDMARKS_INPUT_SIZE = 192

# MediaPipe face mesh region indices for drawing.
# Each region is a list of CONTOURS; each contour is an ordered list of indices.
# Closed-loop contours (face oval, eyes) draw as polygons; open contours
# (eyebrow top/bottom edges, lip outer/inner) draw as polylines.

# Face oval: single closed contour
FACE_OVAL_CONTOURS = [[
    10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288,
    397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136,
    172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109,
]]

# Eyes: single closed contour each
LEFT_EYE_CONTOURS = [[
    362, 382, 381, 380, 374, 373, 390, 249, 263, 466, 388, 387,
    386, 385, 384, 398,
]]
RIGHT_EYE_CONTOURS = [[
    33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158,
    159, 160, 161, 246,
]]

# Eyebrows: two separate open chains (top edge + bottom edge) per brow.
# MediaPipe defines them as edge pairs that form two parallel chains.
LEFT_EYEBROW_CONTOURS = [
    [276, 283, 282, 295, 285],   # bottom edge
    [300, 293, 334, 296, 336],   # top edge
]
RIGHT_EYEBROW_CONTOURS = [
    [46, 53, 52, 65, 55],        # bottom edge
    [70, 63, 105, 66, 107],      # top edge
]

# Lips: four separate closed-loop contours (outer upper, outer lower,
# inner upper, inner lower). Must be drawn separately to avoid cross-connections.
LIPS_CONTOURS = [
    # Outer upper lip (from left corner, over the top, to right corner)
    [61, 185, 40, 39, 37, 0, 267, 269, 270, 409, 291],
    # Outer lower lip (from left corner, under the bottom, to right corner)
    [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291],
    # Inner upper lip
    [78, 191, 80, 81, 82, 13, 312, 311, 310, 415, 308],
    # Inner lower lip
    [78, 95, 88, 178, 87, 14, 317, 402, 318, 324, 308],
]

# Drawing colors (BGR for OpenCV)
COLOR_OVAL = (0, 255, 0)
COLOR_EYE = (255, 200, 0)
COLOR_LIPS = (0, 0, 255)
COLOR_BROW = (200, 200, 0)
COLOR_DEFAULT = (200, 200, 200)


# ---------------------------------------------------------------------------
# InferVStreams landmark model (python mode only)
# ---------------------------------------------------------------------------

class FaceLandmarkInference:
    """face_landmarks_lite via HailoRT InferVStreams (python mode)."""

    def __init__(self, hef_path: str) -> None:
        self.hef = HEF(hef_path)

        params = VDevice.create_params()
        params.group_id = SHARED_VDEVICE_GROUP_ID
        self.vdevice = VDevice(params)

        self.network_group = self.vdevice.configure(self.hef)[0]
        self.network_group_params = self.network_group.create_params()

        self.input_vstreams_params = InputVStreamParams.make(
            self.network_group, format_type=FormatType.UINT8,
        )
        self.output_vstreams_params = OutputVStreamParams.make(
            self.network_group, format_type=FormatType.FLOAT32,
        )

        self.input_vstream_info = self.hef.get_input_vstream_infos()[0]
        self.output_vstream_infos = self.hef.get_output_vstream_infos()

        self._landmarks_name = None
        self._confidence_name = None
        for info in self.output_vstream_infos:
            total = int(np.prod(info.shape))
            if total == 1404:
                self._landmarks_name = info.name
            elif total == 1:
                self._confidence_name = info.name

        logger.info(
            "FaceLandmarkInference: landmarks=%s, confidence=%s",
            self._landmarks_name, self._confidence_name,
        )

    def predict(self, face_rgb_192: np.ndarray) -> tuple[np.ndarray, float]:
        """Run on a 192x192 RGB uint8 crop.

        Returns:
            landmarks: (468, 3) float32 in 192x192 pixel space (raw model output).
            confidence: sigmoid of presence score.
        """
        if face_rgb_192.shape[:2] != (LANDMARKS_INPUT_SIZE, LANDMARKS_INPUT_SIZE):
            face_rgb_192 = cv2.resize(face_rgb_192, (LANDMARKS_INPUT_SIZE, LANDMARKS_INPUT_SIZE))
        input_data = {self.input_vstream_info.name: np.expand_dims(face_rgb_192, axis=0)}

        with self.network_group.activate(self.network_group_params):
            with InferVStreams(
                self.network_group,
                self.input_vstreams_params,
                self.output_vstreams_params,
            ) as pipeline:
                results = pipeline.infer(input_data)

        landmarks = results[self._landmarks_name].flatten().reshape(468, 3)

        confidence = 1.0
        if self._confidence_name is not None:
            c = results[self._confidence_name].flatten()[0]
            confidence = float(1.0 / (1.0 + np.exp(-c)))

        return landmarks, confidence


# ---------------------------------------------------------------------------
# Callback class
# ---------------------------------------------------------------------------

class FaceLandmarksCallback(app_callback_class):
    """Per-frame state for face landmarks detection."""

    def __init__(self):
        super().__init__()
        self.frame_queue = multiprocessing.Queue(maxsize=5)
        self.landmark_model: FaceLandmarkInference | None = None
        self.pipeline_mode: str = "gstreamer"

    def setup_python_mode(self, hef_path: str) -> None:
        """Load face_landmarks_lite via InferVStreams (python mode only)."""
        self.landmark_model = FaceLandmarkInference(hef_path)
        logger.info("Face landmark model loaded on Hailo (InferVStreams).")

    def set_frame(self, frame: np.ndarray) -> None:
        """Replace queued frame with latest (drop stale)."""
        while not self.frame_queue.empty():
            try:
                self.frame_queue.get_nowait()
            except Exception:
                break
        self.frame_queue.put(frame)


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------

def _get_track_id(detection) -> int:
    tracks = detection.get_objects_typed(hailo.HAILO_UNIQUE_ID)
    return tracks[0].get_id() if len(tracks) == 1 else 0


def _draw_contours(frame, pixel_pts, contours, color, thickness=1, closed=True):
    """Draw one or more polylines for a face region.

    Args:
        contours: List of contours, each contour is an ordered list of landmark indices.
        closed: If True, each contour is drawn as a closed polygon.
    """
    for indices in contours:
        valid = [i for i in indices if i < len(pixel_pts)]
        if len(valid) < 2:
            continue
        pts = pixel_pts[valid].astype(np.int32)
        cv2.polylines(frame, [pts], closed, color, thickness, cv2.LINE_AA)


def _draw_landmarks_on_frame(frame, pixel_pts):
    """Draw color-coded face mesh regions from pixel-coordinate landmarks."""
    # Closed-loop contours
    _draw_contours(frame, pixel_pts, FACE_OVAL_CONTOURS, COLOR_OVAL, 1, closed=True)
    _draw_contours(frame, pixel_pts, LEFT_EYE_CONTOURS, COLOR_EYE, 1, closed=True)
    _draw_contours(frame, pixel_pts, RIGHT_EYE_CONTOURS, COLOR_EYE, 1, closed=True)
    _draw_contours(frame, pixel_pts, LIPS_CONTOURS, COLOR_LIPS, 1, closed=True)
    # Open contours (eyebrow top/bottom edges)
    _draw_contours(frame, pixel_pts, LEFT_EYEBROW_CONTOURS, COLOR_BROW, 1, closed=False)
    _draw_contours(frame, pixel_pts, RIGHT_EYEBROW_CONTOURS, COLOR_BROW, 1, closed=False)

    # Draw individual landmark dots (every 3rd for performance)
    num_pts = len(pixel_pts)
    for i in range(0, num_pts, 3):
        x, y = int(pixel_pts[i, 0]), int(pixel_pts[i, 1])
        cv2.circle(frame, (x, y), 1, COLOR_DEFAULT, -1)


# Cropper expansion parameters — must match vms_croppers.cpp `face_recognition` function:
#   FACE_ATTRIBUTES_CROP_SCALE_FACTOR = 1.58
#   FACE_ATTRIBUTES_CROP_HIGHT_OFFSET_FACTOR = 0.10
# The hailocropper expands the face bbox by 1.58x (with a 10% vertical offset up)
# before feeding to face_landmarks_lite. Landmarks come back in [0,1] of this
# EXPANDED bbox, so we must reproduce the same transform here.
_CROP_SCALE = 1.58
_CROP_HEIGHT_OFFSET = 0.10


def _expanded_bbox_pixels(bbox, frame_w: int, frame_h: int):
    """Reproduce the vms_croppers `algorithm_face_crop` expansion in pixel coords.

    Returns (x, y, w, h) of the expanded bbox in pixels — the same region the
    cropper sends to face_landmarks_lite.
    """
    # bbox values are normalized [0,1] relative to the frame
    bw_px = bbox.width() * frame_w
    bh_px = bbox.height() * frame_h
    old_size = (bw_px + bh_px) / 2.0

    center_x = (2 * bbox.xmin() + bbox.width()) / 2.0
    center_y = (2 * bbox.ymin() + bbox.height()) / 2.0 \
        - (old_size / frame_h) * _CROP_HEIGHT_OFFSET

    size = old_size * _CROP_SCALE
    w_norm = size / frame_w
    h_norm = size / frame_h

    x_norm = max(0.0, min(center_x - w_norm / 2.0, 1.0))
    y_norm = max(0.0, min(center_y - h_norm / 2.0, 1.0))
    w_norm = max(0.0, min(w_norm, 1.0 - x_norm))
    h_norm = max(0.0, min(h_norm, 1.0 - y_norm))

    return (x_norm * frame_w, y_norm * frame_h, w_norm * frame_w, h_norm * frame_h)


def _landmarks_to_pixels_from_bbox(landmarks_norm, bbox, frame_w, frame_h, expanded=False):
    """Convert normalized [0,1] landmarks to pixel coords.

    Args:
        landmarks_norm: (N, 2+) array with x,y in [0,1].
        bbox: HailoBBox from the face detection (normalized frame coords).
        frame_w, frame_h: full frame pixel dimensions.
        expanded: If True, interpret landmarks as being normalized to the
            1.58x expanded bbox used by the vms_croppers cascade. Set this
            for HailoMatrix-stored landmarks from the GStreamer cascade.
            If False, landmarks are normalized to the given bbox directly.
    """
    if expanded:
        bx, by, bw, bh = _expanded_bbox_pixels(bbox, frame_w, frame_h)
    else:
        bx = bbox.xmin() * frame_w
        by = bbox.ymin() * frame_h
        bw = bbox.width() * frame_w
        bh = bbox.height() * frame_h

    num = landmarks_norm.shape[0]
    pixel_pts = np.zeros((num, 2), dtype=np.float32)
    pixel_pts[:, 0] = landmarks_norm[:, 0] * bw + bx
    pixel_pts[:, 1] = landmarks_norm[:, 1] * bh + by
    return pixel_pts


def _landmarks_to_pixels_from_hailo(points, bbox, frame_w, frame_h):
    """Convert HailoPoint landmarks to pixel coords."""
    bx = bbox.xmin() * frame_w
    by = bbox.ymin() * frame_h
    bw = bbox.width() * frame_w
    bh = bbox.height() * frame_h

    pixel_pts = np.array(
        [(p.x() * bw + bx, p.y() * bh + by) for p in points],
        dtype=np.float32,
    )
    return pixel_pts


# ---------------------------------------------------------------------------
# Rotation-aligned crop (MediaPipe-style) for python mode
# ---------------------------------------------------------------------------
# SCRFD keypoint indices: 0=right_eye, 1=left_eye, 2=nose, 3=right_mouth, 4=left_mouth

def _build_mesh_warp_matrix(
    right_eye_px: tuple[float, float],
    left_eye_px: tuple[float, float],
    bbox_px: tuple[float, float, float, float],
    scale: float = 1.5,
) -> np.ndarray:
    """Build a 2x3 affine matrix that maps the frame to a 192x192 upright face crop.

    Same math as face_landmarks_standalone.py:
        1. Compute rotation from the eye-to-eye vector (image y-down convention).
        2. Center the crop on a blend of bbox center + eye midpoint.
        3. Rotate + scale so `max(bbox_w, bbox_h) * scale` maps to 192.
    """
    rex, rey = right_eye_px
    lex, ley = left_eye_px

    # Image-space angle of the eye vector from horizontal
    angle_image = math.atan2(ley - rey, lex - rex)
    # Rotate by -angle_image to make eyes horizontal
    rotation = -angle_image

    x1, y1, x2, y2 = bbox_px
    bbox_cx = (x1 + x2) / 2.0
    bbox_cy = (y1 + y2) / 2.0
    eye_cx = (rex + lex) / 2.0
    eye_cy = (rey + ley) / 2.0
    # Blend toward the eyes to put more forehead in the crop
    cx = 0.5 * bbox_cx + 0.5 * eye_cx
    cy = 0.5 * bbox_cy + 0.5 * eye_cy

    size = max(x2 - x1, y2 - y1) * scale

    cos_r = math.cos(rotation)
    sin_r = math.sin(rotation)
    s = LANDMARKS_INPUT_SIZE / size

    return np.array([
        [s * cos_r, -s * sin_r, -s * cos_r * cx + s * sin_r * cy + LANDMARKS_INPUT_SIZE / 2],
        [s * sin_r,  s * cos_r, -s * sin_r * cx - s * cos_r * cy + LANDMARKS_INPUT_SIZE / 2],
    ], dtype=np.float32)


def _warp_face_to_192(frame_rgb: np.ndarray, M: np.ndarray) -> np.ndarray:
    return cv2.warpAffine(
        frame_rgb, M,
        (LANDMARKS_INPUT_SIZE, LANDMARKS_INPUT_SIZE),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0),
    )


def _landmarks_192_to_frame(landmarks_192: np.ndarray, M: np.ndarray) -> np.ndarray:
    """Project (468, 2+) landmarks from the 192x192 aligned space back to frame pixels."""
    M_inv = cv2.invertAffineTransform(M)
    xy = landmarks_192[:, :2].astype(np.float32)
    ones = np.ones((xy.shape[0], 1), dtype=np.float32)
    return (np.concatenate([xy, ones], axis=1) @ M_inv.T).astype(np.float32)


def _scrfd_eye_keypoints_px(detection, frame_w: int, frame_h: int):
    """Extract right_eye, left_eye pixel coords from SCRFD's HAILO_LANDMARKS.

    Returns (right_eye_px, left_eye_px) or None if not available.
    SCRFD landmark indices: 0=right_eye, 1=left_eye.
    """
    landmarks_list = detection.get_objects_typed(hailo.HAILO_LANDMARKS)
    if not landmarks_list:
        return None
    pts = landmarks_list[0].get_points()
    if len(pts) < 2:
        return None
    bbox = detection.get_bbox()
    bw = bbox.width() * frame_w
    bh = bbox.height() * frame_h
    bx = bbox.xmin() * frame_w
    by = bbox.ymin() * frame_h
    right_eye = (pts[0].x() * bw + bx, pts[0].y() * bh + by)
    left_eye  = (pts[1].x() * bw + bx, pts[1].y() * bh + by)
    return right_eye, left_eye


# ---------------------------------------------------------------------------
# Callback — handles both gstreamer and python modes
# ---------------------------------------------------------------------------

def app_callback(element, buffer, user_data: FaceLandmarksCallback):
    """Per-frame callback."""
    if buffer is None:
        return 1

    pad = element.get_static_pad("src")
    fmt, width, height = get_caps_from_pad(pad)
    if not (user_data.use_frame and fmt and width and height):
        return 1

    frame = get_numpy_from_buffer(buffer, fmt, width, height)
    if frame is None:
        return 1

    roi = hailo.get_roi_from_buffer(buffer)
    detections = roi.get_objects_typed(hailo.HAILO_DETECTION)

    for detection in detections:
        if detection.get_label() != "face":
            continue

        track_id = _get_track_id(detection)
        bbox = detection.get_bbox()

        x1 = max(int(bbox.xmin() * width), 0)
        y1 = max(int(bbox.ymin() * height), 0)
        x2 = min(int((bbox.xmin() + bbox.width()) * width), width)
        y2 = min(int((bbox.ymin() + bbox.height()) * height), height)

        if x2 - x1 < 20 or y2 - y1 < 20:
            continue

        pixel_pts = None

        if user_data.pipeline_mode == "gstreamer":
            # GStreamer mode: landmarks stored as HAILO_MATRIX (1404 floats)
            # because hailoaggregator preserves HAILO_MATRIX but drops HAILO_LANDMARKS.
            # The cropper expands the bbox by 1.58x before feeding the model,
            # so landmarks are normalized to that expanded region.
            matrices = detection.get_objects_typed(hailo.HAILO_MATRIX)
            for matrix in matrices:
                data = np.array(matrix.get_data())
                if data.size >= 1404:
                    landmarks = data[:1404].reshape(468, 3)
                    pixel_pts = _landmarks_to_pixels_from_bbox(
                        landmarks, bbox, width, height, expanded=True,
                    )
                    break
        else:
            # Python mode: rotation-aligned crop + face_landmarks_lite via InferVStreams
            # (same approach as face_landmarks_standalone.py)
            landmark_model = user_data.landmark_model
            eyes = _scrfd_eye_keypoints_px(detection, width, height)
            if landmark_model is not None and eyes is not None:
                right_eye_px, left_eye_px = eyes
                bbox_px = (x1, y1, x2, y2)
                M = _build_mesh_warp_matrix(
                    right_eye_px, left_eye_px, bbox_px, scale=1.5,
                )
                # Warp the face region from RGB frame to 192x192 upright
                face_192_rgb = _warp_face_to_192(frame, M)
                landmarks_192, confidence = landmark_model.predict(face_192_rgb)
                if confidence >= 0.3:
                    # Project landmarks from 192x192 aligned space back to frame pixels
                    pixel_pts = _landmarks_192_to_frame(landmarks_192, M)

        if pixel_pts is not None:
            _draw_landmarks_on_frame(frame, pixel_pts)

        # Draw face bbox + track ID
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 1)
        if track_id > 0:
            cv2.putText(
                frame, f"ID:{track_id}", (x1, y1 - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1,
            )

    user_data.set_frame(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
    return 1


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    """Entry point for face landmarks detection."""
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    logger.info("Starting Face Landmarks Detection...")

    user_data = FaceLandmarksCallback()
    app = GStreamerFaceLandmarksApp(app_callback, user_data)

    user_data.pipeline_mode = app.pipeline_mode

    # Python mode: load face_landmarks_lite via InferVStreams
    if app.pipeline_mode == "python":
        user_data.setup_python_mode(app.hef_path_landmarks)

    logger.info("Pipeline mode: %s — Running...", app.pipeline_mode)
    app.run()


if __name__ == "__main__":
    main()
