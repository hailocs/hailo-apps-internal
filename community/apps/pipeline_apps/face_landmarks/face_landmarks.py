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

# MediaPipe face mesh region indices for drawing
FACE_OVAL = [
    10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288,
    397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136,
    172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109,
]
LEFT_EYE = [
    362, 382, 381, 380, 374, 373, 390, 249, 263, 466, 388, 387,
    386, 385, 384, 398,
]
RIGHT_EYE = [
    33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158,
    159, 160, 161, 246,
]
LIPS = [
    61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291,
    78, 191, 80, 81, 82, 13, 312, 311, 310, 415, 308,
    324, 318, 402, 317, 14, 87, 178, 88, 95,
]
LEFT_EYEBROW = [336, 296, 334, 293, 300, 276, 283, 282, 295, 285]
RIGHT_EYEBROW = [70, 63, 105, 66, 107, 55, 65, 52, 53, 46]

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

    def predict(self, face_crop_rgb: np.ndarray) -> tuple[np.ndarray, float]:
        """Run on a cropped face. Returns ((468,3) normalized, confidence)."""
        face_resized = cv2.resize(face_crop_rgb, (LANDMARKS_INPUT_SIZE, LANDMARKS_INPUT_SIZE))
        input_data = {self.input_vstream_info.name: np.expand_dims(face_resized, axis=0)}

        with self.network_group.activate(self.network_group_params):
            with InferVStreams(
                self.network_group,
                self.input_vstreams_params,
                self.output_vstreams_params,
            ) as pipeline:
                results = pipeline.infer(input_data)

        raw = results[self._landmarks_name].flatten()
        landmarks = raw.reshape(468, 3)
        landmarks[:, 0] /= LANDMARKS_INPUT_SIZE
        landmarks[:, 1] /= LANDMARKS_INPUT_SIZE

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


def _draw_region(frame, pixel_pts, indices, color, thickness=1, closed=True):
    """Draw a polyline connecting landmark indices."""
    valid = [i for i in indices if i < len(pixel_pts)]
    if len(valid) < 2:
        return
    pts = pixel_pts[valid].astype(np.int32)
    cv2.polylines(frame, [pts], closed, color, thickness, cv2.LINE_AA)


def _draw_landmarks_on_frame(frame, pixel_pts):
    """Draw color-coded face mesh regions from pixel-coordinate landmarks."""
    _draw_region(frame, pixel_pts, FACE_OVAL, COLOR_OVAL, 1, True)
    _draw_region(frame, pixel_pts, LEFT_EYE, COLOR_EYE, 1, True)
    _draw_region(frame, pixel_pts, RIGHT_EYE, COLOR_EYE, 1, True)
    _draw_region(frame, pixel_pts, LEFT_EYEBROW, COLOR_BROW, 1, False)
    _draw_region(frame, pixel_pts, RIGHT_EYEBROW, COLOR_BROW, 1, False)
    _draw_region(frame, pixel_pts, LIPS, COLOR_LIPS, 1, True)

    # Draw individual landmark dots (every 3rd for performance)
    num_pts = len(pixel_pts)
    for i in range(0, num_pts, 3):
        x, y = int(pixel_pts[i, 0]), int(pixel_pts[i, 1])
        cv2.circle(frame, (x, y), 1, COLOR_DEFAULT, -1)


def _landmarks_to_pixels_from_bbox(landmarks_norm, bbox, frame_w, frame_h):
    """Convert normalized [0,1] landmarks to pixel coords using SCRFD bbox."""
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
            # because hailoaggregator preserves HAILO_MATRIX but drops HAILO_LANDMARKS
            matrices = detection.get_objects_typed(hailo.HAILO_MATRIX)
            for matrix in matrices:
                data = np.array(matrix.get_data())
                if data.size >= 1404:
                    landmarks = data[:1404].reshape(468, 3)
                    pixel_pts = _landmarks_to_pixels_from_bbox(landmarks, bbox, width, height)
                    break
        else:
            # Python mode: run face_landmarks_lite via InferVStreams
            # Add 15% padding to face crop for better landmark accuracy
            landmark_model = user_data.landmark_model
            if landmark_model is not None:
                pad_w = int((x2 - x1) * 0.15)
                pad_h = int((y2 - y1) * 0.15)
                cx1 = max(x1 - pad_w, 0)
                cy1 = max(y1 - pad_h, 0)
                cx2 = min(x2 + pad_w, width)
                cy2 = min(y2 + pad_h, height)
                face_crop = frame[cy1:cy2, cx1:cx2]
                landmarks, confidence = landmark_model.predict(face_crop)
                if confidence >= 0.3:
                    # Remap from padded crop to original bbox
                    cw = cx2 - cx1
                    ch = cy2 - cy1
                    num = landmarks.shape[0]
                    pixel_pts = np.zeros((num, 2), dtype=np.float32)
                    pixel_pts[:, 0] = landmarks[:, 0] * cw + cx1
                    pixel_pts[:, 1] = landmarks[:, 1] * ch + cy1

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
