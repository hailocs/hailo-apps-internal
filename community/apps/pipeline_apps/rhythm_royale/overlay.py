"""Overlay — pure-OpenCV drawing for Rhythm Royale.

All functions take an RGB frame and mutate it in place. They never read from
GStreamer or Hailo.
"""
from __future__ import annotations

import math
from typing import Dict, Optional, Tuple

import cv2
import numpy as np


SKELETON_PAIRS = [
    ("left_shoulder", "right_shoulder"),
    ("left_shoulder", "left_elbow"),
    ("right_shoulder", "right_elbow"),
    ("left_elbow", "left_wrist"),
    ("right_elbow", "right_wrist"),
    ("left_shoulder", "left_hip"),
    ("right_shoulder", "right_hip"),
    ("left_hip", "right_hip"),
    ("left_hip", "left_knee"),
    ("right_hip", "right_knee"),
    ("left_knee", "left_ankle"),
    ("right_knee", "right_ankle"),
]


def _score_color(score: float) -> Tuple[int, int, int]:
    """Red (low) -> yellow -> green (high). Returns RGB."""
    s = float(np.clip(score, 0.0, 1.0))
    if s < 0.5:
        t = s / 0.5
        return (255, int(255 * t), 0)
    t = (s - 0.5) / 0.5
    return (int(255 * (1 - t)), 255, 0)


def draw_skeleton(frame: np.ndarray,
                  kp: Dict[str, Tuple[float, float]],
                  color: Tuple[int, int, int]) -> None:
    for a, b in SKELETON_PAIRS:
        if a in kp and b in kp:
            pa = (int(kp[a][0]), int(kp[a][1]))
            pb = (int(kp[b][0]), int(kp[b][1]))
            cv2.line(frame, pa, pb, color, 2, cv2.LINE_AA)
    for _, (x, y) in kp.items():
        cv2.circle(frame, (int(x), int(y)), 3, color, -1, cv2.LINE_AA)


def draw_score_tag(frame: np.ndarray, kp: Dict[str, Tuple[float, float]],
                   track_id: int, score_value: float,
                   is_rockstar: bool) -> None:
    if "nose" not in kp:
        return
    x, y = kp["nose"]
    label_y = max(30, int(y) - 60)
    text = f"#{track_id}  {int(round(score_value * 100))}"
    color = _score_color(score_value)
    thickness = 3 if is_rockstar else 2
    font_scale = 1.0 if is_rockstar else 0.7
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)
    cv2.rectangle(frame,
                  (int(x) - tw // 2 - 6, label_y - th - 6),
                  (int(x) + tw // 2 + 6, label_y + 6),
                  (0, 0, 0), -1)
    cv2.putText(frame, text, (int(x) - tw // 2, label_y),
                cv2.FONT_HERSHEY_SIMPLEX, font_scale, color, thickness, cv2.LINE_AA)

    if is_rockstar:
        banner = "ROCKSTAR"
        (bw, bh), _ = cv2.getTextSize(banner, cv2.FONT_HERSHEY_SIMPLEX, 1.2, 3)
        by = max(60, label_y - 40)
        cv2.rectangle(frame,
                      (int(x) - bw // 2 - 8, by - bh - 6),
                      (int(x) + bw // 2 + 8, by + 6),
                      (40, 40, 40), -1)
        cv2.putText(frame, banner, (int(x) - bw // 2, by),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 215, 0), 3, cv2.LINE_AA)
        cx, cy = int(x), by - bh - 18
        _draw_crown(frame, cx, cy, size=24)


def _draw_crown(frame: np.ndarray, cx: int, cy: int, size: int = 24) -> None:
    color = (255, 215, 0)
    pts = np.array([
        [cx - size, cy + size // 2],
        [cx - size, cy - size // 2],
        [cx - size // 2, cy],
        [cx, cy - size],
        [cx + size // 2, cy],
        [cx + size, cy - size // 2],
        [cx + size, cy + size // 2],
    ], np.int32)
    cv2.fillPoly(frame, [pts], color, cv2.LINE_AA)


def draw_beat_pulse(frame: np.ndarray, f_beat_hz: Optional[float],
                    phase_rad: float, t_seconds: float,
                    confidence: float) -> None:
    h, w = frame.shape[:2]
    cx, cy = w // 2, 50
    if f_beat_hz is None:
        cv2.circle(frame, (cx, cy), 16, (80, 80, 80), 2, cv2.LINE_AA)
        cv2.putText(frame, "No beat", (cx - 60, 90),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (180, 180, 180), 2, cv2.LINE_AA)
        return
    pulse = 0.5 + 0.5 * math.cos(2 * math.pi * f_beat_hz * t_seconds - phase_rad)
    r = int(18 + 18 * pulse)
    cv2.circle(frame, (cx, cy), r, (0, 200, 255), -1, cv2.LINE_AA)
    cv2.circle(frame, (cx, cy), r, (255, 255, 255), 2, cv2.LINE_AA)
    bpm = f_beat_hz * 60.0
    cv2.putText(frame, f"{bpm:.0f} BPM  conf={confidence:.1f}",
                (cx - 90, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                (255, 255, 255), 2, cv2.LINE_AA)
