"""Standalone face landmarks demo — SCRFD + face_landmarks_lite, both on Hailo.

Reference implementation mirroring MediaPipe's face mesh pipeline:

    1. SCRFD (Hailo)            → bbox + 5 keypoints (right_eye, left_eye, nose, mouth corners)
    2. Rotation alignment       → compute angle from eye keypoints, warp crop to 192×192 upright
    3. face_landmarks_lite      → 468 landmarks in aligned 192×192 space
    4. Inverse transform        → landmarks back to original image coords
    5. MediaPipe drawing_utils  → visualize with edge-pair drawing

This is the gold-standard reference: both models on Hailo, rotation-aligned
crop like MediaPipe, MediaPipe-style drawing. If this looks right, any
asymmetry in the GStreamer cascade is a pipeline/transform issue.

Usage:
    python -m community.apps.pipeline_apps.face_landmarks.face_landmarks_standalone --image IMG
    python -m community.apps.pipeline_apps.face_landmarks.face_landmarks_standalone --video VIDEO
    python -m community.apps.pipeline_apps.face_landmarks.face_landmarks_standalone --camera 0
"""

from __future__ import annotations

import argparse
import math
import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import cv2
import numpy as np

from mediapipe.tasks.python.components.containers import landmark as mp_landmark
from mediapipe.tasks.python.vision import (
    FaceLandmarksConnections,
    drawing_styles,
    drawing_utils,
)
from hailo_platform import (
    HEF,
    VDevice,
    InferVStreams,
    InputVStreamParams,
    OutputVStreamParams,
    FormatType,
)

from hailo_apps.python.core.common.defines import SHARED_VDEVICE_GROUP_ID
from hailo_apps.python.core.common.hailo_logger import get_logger
from community.apps.pipeline_apps.face_landmarks.hailo_scrfd import HailoScrfd

logger = get_logger(__name__)

LANDMARKS_INPUT_SIZE = 192
NUM_LANDMARKS = 468

# SCRFD keypoint indices
KP_RIGHT_EYE = 0
KP_LEFT_EYE = 1
KP_NOSE = 2
KP_RIGHT_MOUTH = 3
KP_LEFT_MOUTH = 4


# ---------------------------------------------------------------------------
# Hailo face_landmarks_lite wrapper (same as before)
# ---------------------------------------------------------------------------

class HailoFaceLandmarks:
    """face_landmarks_lite inference via HailoRT InferVStreams."""

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

        self.input_name = self.hef.get_input_vstream_infos()[0].name
        self.output_infos = self.hef.get_output_vstream_infos()

        self._landmarks_name = None
        self._confidence_name = None
        for info in self.output_infos:
            total = int(np.prod(info.shape))
            if total == NUM_LANDMARKS * 3:
                self._landmarks_name = info.name
            elif total == 1:
                self._confidence_name = info.name

    def predict(self, face_rgb_192: np.ndarray) -> tuple[np.ndarray, float]:
        """Run inference on a 192×192 RGB uint8 crop.

        Returns:
            landmarks: (468, 3) — (x, y, z) in 192×192 aligned pixel space.
            confidence: face presence score in [0, 1].
        """
        assert face_rgb_192.shape == (LANDMARKS_INPUT_SIZE, LANDMARKS_INPUT_SIZE, 3)
        input_data = {self.input_name: np.expand_dims(face_rgb_192, axis=0)}

        with self.network_group.activate(self.network_group_params):
            with InferVStreams(
                self.network_group,
                self.input_vstreams_params,
                self.output_vstreams_params,
            ) as pipeline:
                results = pipeline.infer(input_data)

        landmarks = results[self._landmarks_name].flatten().reshape(NUM_LANDMARKS, 3)
        confidence = 1.0
        if self._confidence_name is not None:
            raw = results[self._confidence_name].flatten()[0]
            confidence = float(1.0 / (1.0 + np.exp(-raw)))
        return landmarks, confidence


# ---------------------------------------------------------------------------
# Rotation-aligned crop (MediaPipe's approach)
# ---------------------------------------------------------------------------

def build_face_mesh_transform(
    keypoints: np.ndarray,
    bbox: tuple[float, float, float, float],
    scale: float = 1.5,
) -> np.ndarray:
    """Build a 2×3 affine matrix that maps a rotated square around the face
    to a 192×192 canonical space with eyes horizontal.

    Args:
        keypoints: (5, 2) array of SCRFD keypoints in image pixel coordinates.
        bbox: (x1, y1, x2, y2) face bbox in image pixel coordinates.
        scale: Bbox expansion factor (1.5 matches MediaPipe face mesh default).

    Returns:
        M: (2, 3) affine matrix for cv2.warpAffine to warp the face region to 192×192.
    """
    right_eye = keypoints[KP_RIGHT_EYE]
    left_eye = keypoints[KP_LEFT_EYE]

    # Eye-to-eye vector in image coords (y grows down).
    dx = left_eye[0] - right_eye[0]
    dy = left_eye[1] - right_eye[1]
    # Image-space angle of the eye vector from horizontal.
    angle_image = math.atan2(dy, dx)
    # To make the eye vector horizontal we rotate the image by `-angle_image`.
    rotation = -angle_image  # radians, image-space convention

    # Center of the crop — midpoint of the two eyes works well, but MediaPipe
    # uses the detection's bbox center. The eye midpoint is more stable under
    # head tilt; we use the bbox center adjusted toward the eyes.
    x1, y1, x2, y2 = bbox
    bbox_cx = (x1 + x2) / 2
    bbox_cy = (y1 + y2) / 2
    eye_cx = (right_eye[0] + left_eye[0]) / 2
    eye_cy = (right_eye[1] + left_eye[1]) / 2
    # Blend: lean toward the eyes to get more forehead than chin in the crop.
    cx = 0.5 * bbox_cx + 0.5 * eye_cx
    cy = 0.5 * bbox_cy + 0.5 * eye_cy

    # Crop size — square, based on the bbox dimensions.
    bw = x2 - x1
    bh = y2 - y1
    size = max(bw, bh) * scale

    # Build 2×3 affine matrix that:
    #   1. translates so `(cx, cy)` is at origin
    #   2. rotates by `rotation` (in image-space convention, brings the face upright)
    #   3. scales so `size` maps to 192
    #   4. translates so origin is at (96, 96) of the output
    cos_r = math.cos(rotation)
    sin_r = math.sin(rotation)
    s = LANDMARKS_INPUT_SIZE / size

    # Composed: [x'; y'] = s * R(rotation) * ([x; y] - [cx; cy]) + [96; 96]
    # Rotation matrix in image space (same form as math space):
    #   [ cos -sin ]
    #   [ sin  cos ]
    M = np.array([
        [s * cos_r, -s * sin_r, -s * cos_r * cx + s * sin_r * cy + LANDMARKS_INPUT_SIZE / 2],
        [s * sin_r,  s * cos_r, -s * sin_r * cx - s * cos_r * cy + LANDMARKS_INPUT_SIZE / 2],
    ], dtype=np.float32)
    return M


def warp_face_to_192(image_bgr: np.ndarray, M: np.ndarray) -> np.ndarray:
    """Warp the face region to a 192×192 upright BGR crop."""
    return cv2.warpAffine(
        image_bgr, M,
        (LANDMARKS_INPUT_SIZE, LANDMARKS_INPUT_SIZE),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0),
    )


def landmarks_aligned_to_image(
    landmarks_aligned: np.ndarray,
    M: np.ndarray,
) -> np.ndarray:
    """Project (468, 2+) landmarks from 192×192 aligned space back to the original image.

    Args:
        landmarks_aligned: (N, 2 or 3) landmarks in 192×192 pixel space.
        M: The 2×3 affine matrix used to warp the image to 192×192.

    Returns:
        (N, 2) pixel coordinates in the original image.
    """
    # Homogeneous inverse transform
    M_inv = cv2.invertAffineTransform(M)  # (2, 3)
    xy = landmarks_aligned[:, :2].astype(np.float32)
    ones = np.ones((xy.shape[0], 1), dtype=np.float32)
    homo = np.concatenate([xy, ones], axis=1)  # (N, 3)
    return (homo @ M_inv.T).astype(np.float32)  # (N, 2)


# ---------------------------------------------------------------------------
# MediaPipe-style drawing
# ---------------------------------------------------------------------------

def pixels_to_normalized_landmarks(
    pixel_pts: np.ndarray, frame_w: int, frame_h: int,
    z_values: np.ndarray | None = None,
) -> list[mp_landmark.NormalizedLandmark]:
    """Convert (N, 2) pixel coords to MediaPipe's NormalizedLandmark list."""
    lm_list = []
    for i in range(pixel_pts.shape[0]):
        lm_list.append(mp_landmark.NormalizedLandmark(
            x=float(pixel_pts[i, 0] / frame_w),
            y=float(pixel_pts[i, 1] / frame_h),
            z=float(z_values[i] if z_values is not None else 0.0),
        ))
    return lm_list


def draw_face_mesh(
    image_bgr: np.ndarray,
    normalized_landmarks,
    draw_tesselation: bool = False,
) -> None:
    """Draw contours + optional tesselation using MediaPipe's drawing_utils."""
    if draw_tesselation:
        drawing_utils.draw_landmarks(
            image=image_bgr,
            landmark_list=normalized_landmarks,
            connections=FaceLandmarksConnections.FACE_LANDMARKS_TESSELATION,
            landmark_drawing_spec=None,
            connection_drawing_spec=drawing_styles.get_default_face_mesh_tesselation_style(),
        )
    drawing_utils.draw_landmarks(
        image=image_bgr,
        landmark_list=normalized_landmarks,
        connections=FaceLandmarksConnections.FACE_LANDMARKS_CONTOURS,
        landmark_drawing_spec=None,
        connection_drawing_spec=drawing_styles.get_default_face_mesh_contours_style(),
    )


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------

def process_frame(
    frame_bgr: np.ndarray,
    detector: HailoScrfd,
    landmarker: HailoFaceLandmarks,
    draw_tesselation: bool = False,
    crop_scale: float = 1.5,
    show_debug: bool = True,
) -> np.ndarray:
    """Detect + landmark + draw on a BGR frame. Returns annotated frame."""
    h, w = frame_bgr.shape[:2]
    detections = detector.detect(frame_bgr)

    for det in detections:
        bbox = det["bbox"]  # (x1, y1, x2, y2)
        keypoints = np.asarray(det["keypoints"], dtype=np.float32)  # (5, 2)

        # Build the rotation-aligned affine transform (MediaPipe-style)
        M = build_face_mesh_transform(keypoints, bbox, scale=crop_scale)

        # Warp the face region to 192×192 upright
        face_192_bgr = warp_face_to_192(frame_bgr, M)
        face_192_rgb = cv2.cvtColor(face_192_bgr, cv2.COLOR_BGR2RGB)

        landmarks_aligned, confidence = landmarker.predict(face_192_rgb)
        if confidence < 0.3:
            continue

        # Landmarks are in 192×192 aligned pixel space. Project back to image coords.
        landmarks_pixel = landmarks_aligned_to_image(landmarks_aligned, M)

        # Convert to MediaPipe NormalizedLandmark list for drawing
        norm_landmarks = pixels_to_normalized_landmarks(
            landmarks_pixel, w, h, z_values=landmarks_aligned[:, 2],
        )
        draw_face_mesh(frame_bgr, norm_landmarks, draw_tesselation=draw_tesselation)

        if show_debug:
            # Draw bbox (green) and keypoints (multi-color)
            x1, y1, x2, y2 = [int(v) for v in bbox]
            cv2.rectangle(frame_bgr, (x1, y1), (x2, y2), (0, 255, 0), 1)
            cv2.putText(
                frame_bgr, f"{det['score']:.2f}",
                (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1,
            )
            kp_colors = [(0, 0, 255), (0, 255, 0), (255, 0, 0), (0, 255, 255), (255, 0, 255)]
            for i, (kx, ky) in enumerate(keypoints):
                cv2.circle(frame_bgr, (int(kx), int(ky)), 3, kp_colors[i], -1)

    return frame_bgr


def main():
    parser = argparse.ArgumentParser(
        description="Standalone face landmarks — SCRFD + face_landmarks_lite on Hailo + rotation alignment.",
    )
    src = parser.add_mutually_exclusive_group()
    src.add_argument("--video", help="Video file path")
    src.add_argument("--image", help="Image file path (saves annotated result)")
    src.add_argument("--camera", type=int, help="Camera index (e.g. 0)")
    parser.add_argument("--arch", default="hailo8", help="Hailo architecture")
    parser.add_argument("--output", help="Save output to file (image mode)")
    parser.add_argument(
        "--tesselation", action="store_true",
        help="Draw dense triangular tesselation (2556 edges).",
    )
    parser.add_argument(
        "--crop-scale", type=float, default=1.5,
        help="Bbox expansion factor for the face crop (default: 1.5, MediaPipe default).",
    )
    parser.add_argument(
        "--no-debug", action="store_true",
        help="Hide bbox and keypoints (show landmarks only).",
    )
    args = parser.parse_args()

    resources = os.environ.get("HAILO_RESOURCES_PATH", "/usr/local/hailo/resources")
    scrfd_hef = os.path.join(resources, "models", args.arch, "scrfd_10g.hef")
    mesh_hef = os.path.join(resources, "models", args.arch, "face_landmarks_lite.hef")
    for path in (scrfd_hef, mesh_hef):
        if not os.path.isfile(path):
            logger.error("HEF not found: %s", path)
            sys.exit(1)

    logger.info("Loading SCRFD...")
    detector = HailoScrfd(scrfd_hef)
    logger.info("Loading face_landmarks_lite...")
    landmarker = HailoFaceLandmarks(mesh_hef)

    if args.image:
        frame = cv2.imread(args.image)
        if frame is None:
            logger.error("Could not read %s", args.image)
            sys.exit(1)
        out = process_frame(
            frame, detector, landmarker,
            draw_tesselation=args.tesselation,
            crop_scale=args.crop_scale,
            show_debug=not args.no_debug,
        )
        out_path = args.output or args.image.rsplit(".", 1)[0] + "_annotated.jpg"
        cv2.imwrite(out_path, out)
        logger.info("Saved: %s", out_path)
        return

    if args.video:
        cap = cv2.VideoCapture(args.video)
    elif args.camera is not None:
        cap = cv2.VideoCapture(args.camera)
    else:
        default_video = "/usr/local/hailo/resources/videos/face_recognition.mp4"
        if not os.path.isfile(default_video):
            logger.error("No input. Use --video, --image, or --camera.")
            sys.exit(1)
        cap = cv2.VideoCapture(default_video)

    if not cap.isOpened():
        logger.error("Could not open video source")
        sys.exit(1)

    logger.info("Press 'q' to quit.")
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        out = process_frame(
            frame, detector, landmarker,
            draw_tesselation=args.tesselation,
            crop_scale=args.crop_scale,
            show_debug=not args.no_debug,
        )
        cv2.imshow("Face Landmarks (SCRFD + face_landmarks_lite on Hailo)", out)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
