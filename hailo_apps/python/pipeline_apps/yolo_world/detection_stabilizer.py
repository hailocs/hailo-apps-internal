"""Temporal detection stabilizer for YOLO World.

Per-frame zero-shot detections are noisy: a class whose score hovers around the
threshold pops in and out, producing a fidgety overlay. This lightweight,
class-aware tracker smooths that out with three mechanisms:

1. **Hysteresis** — a track must reach `confirm_thr` (and `min_hits`) to start
   showing, but is sustained while it stays above the lower `sustain_thr`. The
   gap between the two thresholds is the anti-flicker margin.
2. **Coasting (relaxation)** — once confirmed, a track keeps being emitted for
   up to `coast_frames` frames after it stops matching a detection, so a few
   dropped frames don't blink the box off.
3. **EMA smoothing** — box and score are exponentially averaged across frames,
   removing per-frame jitter.

Association is greedy by class + IoU. Call `reset()` when the prompt set changes
(class ids change meaning). Pure Python/NumPy-free; trivially unit-testable.
"""


# Tuned defaults (verified on Hailo-10H: ~75% fewer on/off flips vs raw).
# Kept as named constants rather than CLI flags to keep the app's API small —
# tweak here if a scene needs more/less persistence or smoothing.
# Frames a confirmed track persists after it drops (~0.4 s @ 20 FPS). Tradeoff:
# higher = fewer flicker transitions when an object briefly disappears, but the
# box visibly "ghosts" for longer after the object truly leaves frame. 8 keeps
# ghosting tight; for scenes where objects momentarily occlude, bump to ~16.
DEFAULT_COAST_FRAMES = 8
DEFAULT_MIN_HITS = 2            # detections needed before a track is shown (suppresses 1-frame flashes)
DEFAULT_BOX_ALPHA = 0.5         # EMA weight on the new box (1.0 = no smoothing)
DEFAULT_SCORE_ALPHA = 0.5       # EMA weight on the new score
DEFAULT_ASSOC_IOU = 0.3         # min IoU (same class) to associate a detection to a track
SUSTAIN_FRACTION = 0.5          # sustain (low) threshold = SUSTAIN_FRACTION * confirm threshold
SUSTAIN_FLOOR = 0.1            # never let the sustain threshold drop below this


def derive_sustain_threshold(confirm_thr):
    """Low hysteresis threshold derived from the confirm threshold."""
    return max(SUSTAIN_FLOOR, SUSTAIN_FRACTION * confirm_thr)


def _iou(a, b):
    x1 = max(a[0], b[0]); y1 = max(a[1], b[1])
    x2 = min(a[2], b[2]); y2 = min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (area_a + area_b - inter + 1e-9)


class DetectionStabilizer:
    def __init__(self, confirm_thr=0.3, sustain_thr=None, coast_frames=DEFAULT_COAST_FRAMES,
                 min_hits=DEFAULT_MIN_HITS, assoc_iou=DEFAULT_ASSOC_IOU,
                 box_alpha=DEFAULT_BOX_ALPHA, score_alpha=DEFAULT_SCORE_ALPHA):
        self.confirm_thr = confirm_thr
        # Default the sustain (low) threshold to half the confirm threshold.
        self.sustain_thr = derive_sustain_threshold(confirm_thr) if sustain_thr is None else sustain_thr
        self.coast_frames = coast_frames
        self.min_hits = min_hits
        self.assoc_iou = assoc_iou
        self.box_alpha = box_alpha      # weight on the new box (higher = more responsive)
        self.score_alpha = score_alpha
        self._tracks = []
        self._next_id = 0

    def reset(self):
        self._tracks = []
        self._next_id = 0

    def update(self, detections):
        """Advance one frame.

        Args:
            detections: list of {"bbox":[x1,y1,x2,y2], "class_id":int, "score":float},
                already filtered at `sustain_thr` (the low threshold).

        Returns:
            Stabilized list of {"bbox", "class_id", "score", "track_id"} —
            confirmed tracks that are either matched this frame or coasting.
        """
        for t in self._tracks:
            t["matched"] = False
        used = set()

        # Greedy association, strongest detections first.
        for d in sorted(detections, key=lambda d: -d["score"]):
            best, best_iou = None, self.assoc_iou
            for t in self._tracks:
                if t["id"] in used or t["class_id"] != d["class_id"]:
                    continue
                i = _iou(t["bbox"], d["bbox"])
                if i >= best_iou:
                    best_iou, best = i, t
            if best is not None:
                a = self.box_alpha
                best["bbox"] = [a * nd + (1 - a) * od for nd, od in zip(d["bbox"], best["bbox"])]
                sa = self.score_alpha
                best["score"] = sa * d["score"] + (1 - sa) * best["score"]
                best["peak"] = max(best["peak"], d["score"])
                best["misses"] = 0
                best["hits"] += 1
                best["matched"] = True
                used.add(best["id"])
            else:
                self._tracks.append({
                    "id": self._next_id, "class_id": d["class_id"],
                    "bbox": list(d["bbox"]), "score": d["score"], "peak": d["score"],
                    "misses": 0, "hits": 1, "matched": True,
                })
                used.add(self._next_id)
                self._next_id += 1

        # Age unmatched tracks; drop those past the coast window.
        alive = []
        for t in self._tracks:
            if not t["matched"]:
                t["misses"] += 1
            if t["misses"] <= self.coast_frames:
                alive.append(t)
        self._tracks = alive

        # Emit confirmed tracks (matched this frame or still coasting).
        out = []
        for t in self._tracks:
            if t["peak"] >= self.confirm_thr and t["hits"] >= self.min_hits:
                out.append({
                    "bbox": list(t["bbox"]),
                    "class_id": t["class_id"],
                    "score": float(t["score"]),
                    "track_id": t["id"],
                })
        return out
