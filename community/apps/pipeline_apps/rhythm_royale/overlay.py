"""Overlay — pure-OpenCV widgets for Rhythm Royale.

All draw functions operate on RGB frames in place. No GStreamer / Hailo
dependencies — anything pose- or beat-shaped goes in as plain data.

Widgets:
  - draw_skeleton: keypoints + bones, with optional per-kp confidence gate
    and per-kp color (used by the "per-keypoint glow" debug view).
  - draw_score_tag / _draw_crown: per-dancer score number + ROCKSTAR banner.
  - draw_beat_pulse: small badge with BPM + confidence + a pulsing dot.
  - draw_beat_tape: scrolling envelope strip with detected beat pulses
    overlaid as vertical lines. The visual truth probe — your ear vs the
    algorithm's "where the beats are".
  - draw_harmonic_ladder: 3 micro-bars per dancer for r ∈ {½, 1, 2} showing
    which harmonic they're locked to.
  - draw_phase_clock: rotating unit-circle view — beat phase = hand, each
    dancer's motion phase = a dot. Locked dancers cluster on the beat.
"""
from __future__ import annotations

import math
from typing import Dict, Iterable, Optional, Sequence, Tuple

import cv2
import numpy as np

from community.apps.pipeline_apps.rhythm_royale.beat_extractor import (
    BeatEnvelope, BeatState,
)
from community.apps.pipeline_apps.rhythm_royale.motion_analyzer import (
    HARMONICS, PerKpResult, TrackScore,
)


# Bones drawn between raw Hailo keypoint names (not the analyzer's signal names).
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
    """Red (low) → yellow → green (high). Returns RGB."""
    s = float(np.clip(score, 0.0, 1.0))
    if s < 0.5:
        t = s / 0.5
        return (255, int(255 * t), 0)
    t = (s - 0.5) / 0.5
    return (int(255 * (1 - t)), 255, 0)


def draw_skeleton(frame: np.ndarray,
                  kp: Dict[str, Tuple[float, float]],
                  color: Tuple[int, int, int],
                  kp_conf: Optional[Dict[str, float]] = None,
                  kp_colors: Optional[Dict[str, Tuple[int, int, int]]] = None,
                  conf_min: float = 0.3) -> None:
    """Draw bones and keypoint dots.

    - kp_conf: per-kp confidence; keypoints below conf_min are omitted from
      both the bones (any bone with an unseen endpoint is skipped) and the
      dot draw.
    - kp_colors: per-kp dot colors. When supplied, each kp's dot uses its
      specific color (the per-keypoint glow view); bones still use `color`.
    """
    def visible(name: str) -> bool:
        if name not in kp:
            return False
        if kp_conf is None:
            return True
        return kp_conf.get(name, 1.0) >= conf_min

    for a, b in SKELETON_PAIRS:
        if visible(a) and visible(b):
            pa = (int(kp[a][0]), int(kp[a][1]))
            pb = (int(kp[b][0]), int(kp[b][1]))
            cv2.line(frame, pa, pb, color, 2, cv2.LINE_AA)
    for name, (x, y) in kp.items():
        if not visible(name):
            continue
        dot_color = (kp_colors or {}).get(name, color)
        cv2.circle(frame, (int(x), int(y)), 4, dot_color, -1, cv2.LINE_AA)


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


# ---------------------------------------------------------------------------
# New v2 debug widgets


def draw_beat_tape(frame: np.ndarray,
                   envelope: Optional[BeatEnvelope],
                   beat: Optional[BeatState],
                   t_now: float,
                   y_top: int = 110,
                   height: int = 60) -> None:
    """Horizontal strip near the top of the frame showing the band-passed
    audio envelope, with detected beat pulses overlaid as vertical lines.

    The envelope is what the algorithm "sees" of the music. If the bright
    vertical pulse lines coincide with the kicks you hear, the beat is real.
    If they drift, the algorithm has locked onto noise.
    """
    h, w = frame.shape[:2]
    x0, x1 = 8, w - 8
    y_bot = y_top + height
    rect_color = (40, 40, 50)
    cv2.rectangle(frame, (x0, y_top), (x1, y_bot), rect_color, -1)
    cv2.rectangle(frame, (x0, y_top), (x1, y_bot), (180, 180, 180), 1)
    if envelope is None or len(envelope.samples) < 2:
        cv2.putText(frame, "no envelope",
                    (x0 + 8, y_top + height // 2 + 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (140, 140, 140), 1, cv2.LINE_AA)
        return

    samples = envelope.samples
    n = len(samples)
    # Normalize for display.
    peak = float(np.max(np.abs(samples))) + 1e-9
    mid_y = (y_top + y_bot) // 2
    half = (height - 4) // 2
    pts = np.empty((n, 2), dtype=np.int32)
    for i, v in enumerate(samples):
        px = int(x0 + (x1 - x0) * (i / (n - 1)))
        py = int(mid_y - (v / peak) * half)
        pts[i] = (px, py)
    cv2.polylines(frame, [pts], isClosed=False, color=(220, 220, 220),
                  thickness=1, lineType=cv2.LINE_AA)

    if beat is None or beat.f_beat_hz <= 0:
        return

    # Predicted beat times in absolute seconds: beat peaks where
    # cos(2π f t + phase_abs) = +1 → t_k = (2π k - phase_abs) / (2π f)
    f = beat.f_beat_hz
    phi = beat.phase_abs_rad
    t_window_start = envelope.t_start
    t_window_end = t_window_start + (n / envelope.eff_sr)
    # Show envelope window + a 1-s lookahead as future predictions.
    t_view_end = t_window_end + 1.0
    # Range of integer k values to cover the view.
    k_lo = math.floor((t_window_start * 2 * math.pi * f + phi) / (2 * math.pi))
    k_hi = math.ceil((t_view_end * 2 * math.pi * f + phi) / (2 * math.pi))
    for k in range(k_lo, k_hi + 1):
        t_beat = (2 * math.pi * k - phi) / (2 * math.pi * f)
        # Map t_beat to x in the strip: t_window_start -> x0, t_window_end -> x1.
        if t_beat < t_window_start:
            continue
        if t_beat > t_view_end:
            continue
        # Tape is in window time; future beats spill past x1 if we don't
        # scale the t→x map to view_end. Use t_view_end as right edge.
        x = int(x0 + (x1 - x0) * (t_beat - t_window_start) /
                (t_view_end - t_window_start))
        future = t_beat > t_window_end
        c = (60, 160, 220) if future else (0, 220, 255)
        thick = 1 if future else 2
        cv2.line(frame, (x, y_top + 2), (x, y_bot - 2), c, thick, cv2.LINE_AA)

    # "Now" marker — where the window ends.
    now_x = int(x0 + (x1 - x0) * (t_window_end - t_window_start) /
                (t_view_end - t_window_start))
    cv2.line(frame, (now_x, y_top), (now_x, y_bot), (255, 80, 80), 1, cv2.LINE_AA)


def draw_harmonic_ladder(frame: np.ndarray,
                         kp: Dict[str, Tuple[float, float]],
                         track_score: TrackScore,
                         anchor_kp: str = "nose") -> None:
    """3 micro-bars labeled '½ · 1 · 2' next to the score tag. Each bar's
    height is the mean of that harmonic's freq_match across the dancer's
    scored keypoints. The chosen r* is highlighted.
    """
    if anchor_kp not in kp:
        return
    base_x = int(kp[anchor_kp][0]) + 60
    base_y = max(20, int(kp[anchor_kp][1]) - 80)
    bar_w = 12
    bar_h = 32
    gap = 4

    # Mean across kps for each harmonic.
    rs = [r for r, _ in HARMONICS]
    means: Dict[float, float] = {r: 0.0 for r in rs}
    counts: Dict[float, int] = {r: 0 for r in rs}
    chosen: Dict[float, int] = {r: 0 for r in rs}
    for result in track_score.per_kp.values():
        for r in rs:
            means[r] += result.harmonic_freq_matches.get(r, 0.0)
            counts[r] += 1
        chosen[result.r_star] = chosen.get(result.r_star, 0) + 1
    for r in rs:
        if counts[r]:
            means[r] /= counts[r]

    r_star = max(chosen, key=lambda k: chosen[k]) if chosen else 1.0
    labels = {0.5: "1/2", 1.0: "1", 2.0: "2"}
    for i, r in enumerate(rs):
        x = base_x + i * (bar_w + gap)
        m = float(np.clip(means[r], 0.0, 1.0))
        h = int(bar_h * m)
        # Bar background
        cv2.rectangle(frame, (x, base_y),
                      (x + bar_w, base_y + bar_h), (40, 40, 40), -1)
        cv2.rectangle(frame, (x, base_y + bar_h - h),
                      (x + bar_w, base_y + bar_h),
                      (0, 200, 255) if r == r_star else (170, 170, 170), -1)
        cv2.rectangle(frame, (x, base_y),
                      (x + bar_w, base_y + bar_h), (220, 220, 220), 1)
        cv2.putText(frame, labels[r], (x - 1, base_y + bar_h + 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (200, 200, 200), 1, cv2.LINE_AA)


def draw_phase_clock(frame: np.ndarray,
                     beat: Optional[BeatState],
                     scored: Sequence[Tuple[int, TrackScore]],
                     t_now: float,
                     dancer_colors: Optional[Dict[int, Tuple[int, int, int]]] = None,
                     radius: int = 50) -> None:
    """Unit circle, top-right. The clock hand rotates at f_beat with phase
    locked to the music's absolute phase. Each dancer's motion phase is a
    colored dot, rotating at r*·f_beat. A dancer locked to the beat sits
    on the hand; one out of phase orbits at a different rate.
    """
    h, w = frame.shape[:2]
    cx, cy = w - radius - 24, radius + 24
    cv2.circle(frame, (cx, cy), radius, (40, 40, 50), -1, cv2.LINE_AA)
    cv2.circle(frame, (cx, cy), radius, (200, 200, 200), 1, cv2.LINE_AA)
    cv2.putText(frame, "phase", (cx - radius + 6, cy - radius - 6),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (180, 180, 180), 1, cv2.LINE_AA)

    if beat is None:
        return

    # Beat phase at t_now: phi_now = 2π f t_now + phi_abs (mod 2π)
    phi_beat = 2 * math.pi * beat.f_beat_hz * t_now + beat.phase_abs_rad
    hx = cx + int(math.cos(phi_beat) * (radius - 6))
    hy = cy - int(math.sin(phi_beat) * (radius - 6))
    cv2.line(frame, (cx, cy), (hx, hy), (0, 220, 255), 2, cv2.LINE_AA)
    cv2.circle(frame, (hx, hy), 4, (0, 220, 255), -1, cv2.LINE_AA)

    for tid, score in scored:
        # Use the dominant (highest-weighted) per-kp result for the phase.
        if not score.per_kp:
            continue
        # Pick the kp with the highest kp_score for a single dot per dancer.
        best_name, best_res = max(
            score.per_kp.items(), key=lambda kv: kv[1].kp_score,
        )
        phi_motion = (
            best_res.r_star * (2 * math.pi * beat.f_beat_hz * t_now)
            + best_res.phase_motion_abs_rad
        )
        # For visual comparability with the hand, plot the motion phase
        # *as seen against the fundamental*: divide by r* so r=2 dancers
        # still appear at the equivalent fundamental phase angle.
        phi_motion = phi_motion / max(best_res.r_star, 0.5)
        mx = cx + int(math.cos(phi_motion) * (radius - 14))
        my = cy - int(math.sin(phi_motion) * (radius - 14))
        color = (dancer_colors or {}).get(tid, (240, 240, 240))
        cv2.circle(frame, (mx, my), 5, color, -1, cv2.LINE_AA)
        cv2.circle(frame, (mx, my), 5, (40, 40, 40), 1, cv2.LINE_AA)


def per_kp_glow_colors(per_kp: Dict[str, PerKpResult]) -> Dict[str, Tuple[int, int, int]]:
    """Map analyzer-signal names to RGB colors based on each signal's score.

    Returns colors keyed by the RAW kp names that should glow, so the caller
    can splat them into draw_skeleton's kp_colors. Midpoint signals
    (shoulders_mid, hips_mid) color BOTH source keypoints.
    """
    from community.apps.pipeline_apps.rhythm_royale.motion_analyzer import (
        SIGNAL_SOURCES,
    )
    out: Dict[str, Tuple[int, int, int]] = {}
    for signal_name, result in per_kp.items():
        color = _score_color(result.kp_score)
        for src in SIGNAL_SOURCES.get(signal_name, ()):
            out[src] = color
    return out
