"""
Exercise repetition counter for the Hailo pose-estimation pipeline.

Counts exercise reps (squats, push-ups, pull-ups) by tracking the angle
at a key joint across frames with hysteresis thresholds.  Multi-person
tracking is provided by ByteTrack (already in the repo).

Standalone implementation – no torch / ultralytics dependency required.
Inspired by Ultralytics AIGym.

Usage (from pose_estimation.py):
    python pose_estimation.py --input video.mp4 ... --aigym squats
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import partial
from types import SimpleNamespace
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

# ---------------------------------------------------------------------------
# COCO-pose keypoint indices (17 keypoints)
# ---------------------------------------------------------------------------
# 0:nose  1:left_eye  2:right_eye  3:left_ear  4:right_ear
# 5:left_shoulder  6:right_shoulder  7:left_elbow  8:right_elbow
# 9:left_wrist  10:right_wrist  11:left_hip  12:right_hip
# 13:left_knee  14:right_knee  15:left_ankle  16:right_ankle
#
# Joint pairs for skeleton drawing (same order as pose_estimation_utils)
JOINT_PAIRS = [
    [0, 1], [1, 3], [0, 2], [2, 4],
    [5, 6], [5, 7], [7, 9], [6, 8], [8, 10],
    [5, 11], [6, 12], [11, 12],
    [11, 13], [12, 14], [13, 15], [14, 16],
]

# ---------------------------------------------------------------------------
# Exercise presets
# ---------------------------------------------------------------------------
EXERCISE_PRESETS: Dict[str, dict] = {
    "squats": {
        # hip → knee → ankle  (left and right)
        "kpts": [(11, 13, 15), (12, 14, 16)],
        "up_angle": 170.0,
        "down_angle": 140.0,
    },
    "pushups": {
        # shoulder → elbow → wrist
        "kpts": [(5, 7, 9), (6, 8, 10)],
        "up_angle": 170.0,
        "down_angle": 90.0,
    },
    "pullups": {
        # shoulder → elbow → wrist
        "kpts": [(5, 7, 9), (6, 8, 10)],
        "up_angle": 170.0,
        "down_angle": 90.0,
    },
}

# ---------------------------------------------------------------------------
# Colours (BGR)
# ---------------------------------------------------------------------------
COLOR_SKELETON = (255, 0, 255)   # magenta skeleton lines
COLOR_KEYPOINT = (0, 200, 200)   # cyan keypoint dots
COLOR_BBOX     = (255, 180, 0)   # light-blue bounding boxes
COLOR_TEXT_BG  = (40, 40, 40)    # dark background for text
COLOR_UP       = (0, 200, 0)     # green  – "up" state
COLOR_DOWN     = (0, 0, 220)     # red    – "down" state
COLOR_ANGLE    = (200, 200, 0)   # cyan   – angle arc indicator


# ===================================================================
# Geometry helpers
# ===================================================================

def compute_angle(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    """Return the angle (degrees) at vertex *b* formed by segments ba and bc."""
    ba = a - b
    bc = c - b
    cos_val = np.dot(ba, bc) / (np.linalg.norm(ba) * np.linalg.norm(bc) + 1e-9)
    return math.degrees(math.acos(np.clip(cos_val, -1.0, 1.0)))


def iou_matrix(boxes_a: np.ndarray, boxes_b: np.ndarray) -> np.ndarray:
    """
    Compute IoU between two sets of xyxy boxes.

    Args:
        boxes_a: (M, 4) array  [x1, y1, x2, y2]
        boxes_b: (N, 4) array  [x1, y1, x2, y2]

    Returns:
        (M, N) IoU matrix.
    """
    x1 = np.maximum(boxes_a[:, 0:1], boxes_b[:, 0:1].T)
    y1 = np.maximum(boxes_a[:, 1:2], boxes_b[:, 1:2].T)
    x2 = np.minimum(boxes_a[:, 2:3], boxes_b[:, 2:3].T)
    y2 = np.minimum(boxes_a[:, 3:4], boxes_b[:, 3:4].T)

    inter = np.maximum(x2 - x1, 0) * np.maximum(y2 - y1, 0)

    area_a = (boxes_a[:, 2] - boxes_a[:, 0]) * (boxes_a[:, 3] - boxes_a[:, 1])
    area_b = (boxes_b[:, 2] - boxes_b[:, 0]) * (boxes_b[:, 3] - boxes_b[:, 1])

    union = area_a[:, None] + area_b[None, :] - inter
    return inter / (union + 1e-9)


# ===================================================================
# Per-person exercise state
# ===================================================================

# How many consecutive frames a person can be missing before state is discarded.
_STALE_GRACE_FRAMES = 60


@dataclass
class PersonState:
    """Mutable exercise state for a single tracked person."""
    count: int = 0
    stage: str = ""       # "up" or "down"
    angle: float = 0.0    # current average joint angle
    missing_frames: int = 0  # frames since last seen (for grace-period cleanup)


# ===================================================================
# ExerciseCounter  –  pure logic, no drawing
# ===================================================================

class ExerciseCounter:
    """
    Angle-based hysteresis rep counter for multiple tracked persons.

    For each tracked person the counter watches the average angle at the
    configured joint triplets.  A rep is counted on the *down → up*
    transition (i.e. the person stands back up after squatting, or
    extends the arms after a push-up).
    """

    def __init__(
        self,
        exercise: str = "squats",
        up_angle: Optional[float] = None,
        down_angle: Optional[float] = None,
    ):
        if exercise not in EXERCISE_PRESETS:
            raise ValueError(
                f"Unknown exercise '{exercise}'. "
                f"Choose from: {list(EXERCISE_PRESETS.keys())}"
            )
        preset = EXERCISE_PRESETS[exercise]
        self.exercise = exercise
        self.kpt_triplets: List[Tuple[int, int, int]] = preset["kpts"]
        self.up_angle = up_angle if up_angle is not None else preset["up_angle"]
        self.down_angle = down_angle if down_angle is not None else preset["down_angle"]
        self.persons: Dict[int, PersonState] = {}

    # ---- core update --------------------------------------------------

    def update(
        self,
        track_id: int,
        keypoints: np.ndarray,
        joint_scores: np.ndarray,
        joint_threshold: float = 0.5,
    ) -> PersonState:
        """
        Update the rep count for *track_id* given current-frame keypoints.

        Args:
            track_id:  ByteTrack identifier.
            keypoints: (17, 2) array of (x, y) in original-image coords.
            joint_scores: (17,) confidence scores.
            joint_threshold: Minimum confidence to consider a keypoint valid.

        Returns:
            Updated ``PersonState`` for *track_id*.
        """
        if track_id not in self.persons:
            self.persons[track_id] = PersonState()
        state = self.persons[track_id]

        # Average the angle across the configured joint triplets
        angles: List[float] = []
        for i, j, k in self.kpt_triplets:
            if (joint_scores[i] >= joint_threshold
                    and joint_scores[j] >= joint_threshold
                    and joint_scores[k] >= joint_threshold):
                angles.append(
                    compute_angle(keypoints[i], keypoints[j], keypoints[k])
                )

        if not angles:
            return state

        state.angle = sum(angles) / len(angles)

        # Hysteresis counting: rep on  down → up  transition
        if state.angle >= self.up_angle:
            if state.stage == "down":
                state.count += 1
            state.stage = "up"
        elif state.angle <= self.down_angle:
            state.stage = "down"

        return state

    def cleanup_stale(self, active_ids: set[int]) -> None:
        """Drop state for tracks missing longer than the grace period."""
        for tid in list(self.persons):
            if tid in active_ids:
                self.persons[tid].missing_frames = 0
            else:
                self.persons[tid].missing_frames += 1
                if self.persons[tid].missing_frames > _STALE_GRACE_FRAMES:
                    del self.persons[tid]


# ===================================================================
# AIGymCallback  –  full pipeline callback (postproc → track → count → draw)
# ===================================================================

class AIGymCallback:
    """
    Drop-in replacement for ``PoseEstPostProcessing.inference_result_handler``.

    The ``visualize()`` loop in toolbox.py calls::

        frame_rgb = callback(original_frame_rgb, raw_inference_result)

    This class performs:
    1. Pose post-processing  (ONNX or HEF)
    2. ByteTrack multi-person tracking
    3. Exercise rep counting via :class:`ExerciseCounter`
    4. Annotated-frame rendering (skeleton + track-ID + rep count)
    """

    def __init__(
        self,
        pose_processor,              # PoseEstPostProcessing instance
        tracker,                     # BYTETracker instance
        exercise: str = "squats",
        model_height: int = 640,
        model_width: int = 640,
        class_num: int = 1,
        onnx_config=None,
        onnx_session=None,
        detection_threshold: float = 0.5,
        joint_threshold: float = 0.5,
    ):
        self.pp = pose_processor
        self.tracker = tracker
        self.counter = ExerciseCounter(exercise)
        self.exercise = exercise

        self.model_h = model_height
        self.model_w = model_width
        self.class_num = class_num
        self.onnx_config = onnx_config
        self.onnx_session = onnx_session
        self.det_thresh = detection_threshold
        self.joint_thresh = joint_threshold

    # ------------------------------------------------------------------
    # Callback entry point (matches PoseEstPostProcessing.inference_result_handler)
    # ------------------------------------------------------------------

    def __call__(
        self,
        image: np.ndarray,
        raw_detections: dict,
    ) -> np.ndarray:
        """
        Full AIGym pipeline step.

        Args:
            image: Original frame (RGB, HWC).
            raw_detections: Raw model output dict.

        Returns:
            Annotated frame (RGB, HWC).
        """
        # 1) Post-process  →  bboxes / keypoints / scores in model space
        if self.onnx_session is not None:
            results = self.pp.extract_pose_onnx(
                raw_detections, self.onnx_config, self.onnx_session,
                self.model_h, self.model_w,
            )
        else:
            results = self.pp.post_process(
                raw_detections, self.model_h, self.model_w, self.class_num,
            )

        bboxes = results["bboxes"]          # (1, N, 4)
        scores = results["scores"]          # (1, N, 1)
        keypoints = results["keypoints"]    # (1, N, 17, 2)
        joint_scores = results["joint_scores"]  # (1, N, 17, 1)

        assert bboxes.shape[0] == 1
        orig_h, orig_w = image.shape[:2]

        # 2) Map detections to original image coordinates and filter
        det_list: List[_Detection] = []
        for i in range(bboxes.shape[1]):
            sc = float(scores[0, i, 0])
            if sc < self.det_thresh:
                continue
            box_orig = self.pp.map_box_to_original_coords(
                bboxes[0, i], orig_w, orig_h, self.model_w, self.model_h,
            )
            kps = keypoints[0, i].reshape(17, 2).copy()
            kps = self.pp.map_keypoints_to_original_coords(
                kps, orig_w, orig_h, self.model_w, self.model_h,
            )
            js = joint_scores[0, i].flatten()  # (17,)
            det_list.append(_Detection(
                box=np.array(box_orig, dtype=np.float32),
                score=sc,
                keypoints=kps,
                joint_scores=js,
            ))

        # 3) ByteTrack update  →  active tracks
        if det_list:
            track_input = np.array(
                [[d.box[0], d.box[1], d.box[2], d.box[3], d.score] for d in det_list],
                dtype=np.float32,
            )
        else:
            track_input = np.empty((0, 5), dtype=np.float32)

        tracks = self.tracker.update(track_input)

        # 4) Match tracks → detections via IoU
        track_det_map = self._match_tracks_to_dets(tracks, det_list)

        # 5) Update exercise counter for each matched track
        active_ids: set[int] = set()
        annotated: List[Tuple] = []   # (track, det, person_state)

        for t_idx, track in enumerate(tracks):
            active_ids.add(track.track_id)
            if t_idx not in track_det_map:
                continue
            det = det_list[track_det_map[t_idx]]
            state = self.counter.update(
                track.track_id, det.keypoints, det.joint_scores,
                joint_threshold=self.joint_thresh,
            )
            annotated.append((track, det, state))

        self.counter.cleanup_stale(active_ids)

        # 6) Draw on image
        canvas = image.copy()
        self._draw(canvas, annotated)

        return canvas

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _match_tracks_to_dets(
        tracks,
        det_list: List,
        iou_thresh: float = 0.3,
    ) -> Dict[int, int]:
        """Greedy IoU matching of STrack outputs to input detections."""
        if not tracks or not det_list:
            return {}

        track_boxes = np.array([t.tlbr for t in tracks], dtype=np.float32)
        det_boxes = np.array([d.box for d in det_list], dtype=np.float32)

        ious = iou_matrix(track_boxes, det_boxes)

        matched: Dict[int, int] = {}
        used_dets: set[int] = set()
        # Sort by best IoU descending for greedy assignment
        flat = np.argsort(-ious, axis=None)
        for idx in flat:
            t_i, d_i = divmod(int(idx), len(det_list))
            if t_i in matched or d_i in used_dets:
                continue
            if ious[t_i, d_i] < iou_thresh:
                break   # remaining are worse
            matched[t_i] = d_i
            used_dets.add(d_i)
        return matched

    def _draw(
        self,
        canvas: np.ndarray,
        annotated: List[Tuple],
    ) -> None:
        """Draw skeletons, bounding boxes, track IDs, rep counts, and angles."""
        for track, det, state in annotated:
            kps = det.keypoints
            vis = det.joint_scores > self.joint_thresh

            # Skeleton -------------------------------------------------------
            for j0, j1 in JOINT_PAIRS:
                if vis[j0] and vis[j1]:
                    pt0 = (int(kps[j0, 0]), int(kps[j0, 1]))
                    pt1 = (int(kps[j1, 0]), int(kps[j1, 1]))
                    cv2.line(canvas, pt0, pt1, COLOR_SKELETON, 2)
            for idx in range(17):
                if vis[idx]:
                    pt = (int(kps[idx, 0]), int(kps[idx, 1]))
                    cv2.circle(canvas, pt, 4, COLOR_KEYPOINT, -1)

            # Bounding box ----------------------------------------------------
            x1, y1, x2, y2 = [int(v) for v in det.box]
            cv2.rectangle(canvas, (x1, y1), (x2, y2), COLOR_BBOX, 1)

            # Track-ID + rep count label (above bbox) -------------------------
            stage_color = COLOR_UP if state.stage == "up" else COLOR_DOWN
            label = f"#{track.track_id}  {self.exercise}: {state.count}"
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.65, 2)
            lx, ly = x1, max(y1 - 8, th + 4)
            cv2.rectangle(canvas, (lx - 1, ly - th - 4), (lx + tw + 4, ly + 4), COLOR_TEXT_BG, -1)
            cv2.putText(canvas, label, (lx + 2, ly), cv2.FONT_HERSHEY_SIMPLEX, 0.65, stage_color, 2)

            # Angle indicator near the middle joint ---------------------------
            if state.angle > 0:
                # Use the first valid triplet's middle joint as label anchor
                for i, j, k in self.counter.kpt_triplets:
                    if vis[j]:
                        ax, ay = int(kps[j, 0]) + 10, int(kps[j, 1])
                        angle_txt = f"{state.angle:.0f} deg"
                        cv2.putText(canvas, angle_txt, (ax, ay),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, COLOR_ANGLE, 1)
                        break


@dataclass
class _Detection:
    """Intermediate container for a single mapped detection."""
    box: np.ndarray           # (4,) xyxy in original image coords
    score: float
    keypoints: np.ndarray     # (17, 2) in original image coords
    joint_scores: np.ndarray  # (17,) confidence


# ===================================================================
# Factory helpers  –  called from pose_estimation.py
# ===================================================================

def make_tracker_args(
    track_thresh: float = 0.1,
    track_buffer: int = 30,
    match_thresh: float = 0.9,
    mot20: bool = False,
) -> SimpleNamespace:
    """Build the lightweight args namespace expected by BYTETracker."""
    return SimpleNamespace(
        track_thresh=track_thresh,
        track_buffer=track_buffer,
        match_thresh=match_thresh,
        mot20=mot20,
    )
