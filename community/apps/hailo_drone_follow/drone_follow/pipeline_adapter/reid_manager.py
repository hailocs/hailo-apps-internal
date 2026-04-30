"""ReID-based re-identification manager for drone follow.

Maintains a gallery of embeddings for the currently followed person.
When the tracker loses the target, compares all visible detections
against the gallery to re-identify and resume following.

The Hailo VDevice for the ReID model is created lazily on first use
so that the detection pipeline's VDevice is always created first.
"""

import logging
import os
import threading
from dataclasses import dataclass
from typing import Optional

import numpy as np

LOGGER = logging.getLogger(__name__)


# Action constants returned by ReIDManager.update_gallery to describe what
# happened with a candidate in-track embedding. Strings (not enum) so the
# callback can string-compare without an extra import.
ACTION_BOOTSTRAP = "bootstrap"
ACTION_ADDED = "added"
ACTION_SKIPPED_DUPLICATE = "skipped_duplicate"
ACTION_REFRESHED = "refreshed"
ACTION_SKIPPED_DRIFT = "skipped_drift"
ACTION_NOOP = "noop"


@dataclass(frozen=True)
class GalleryUpdateResult:
    """Outcome of a single ReIDManager.update_gallery() call.

    similarity is -1.0 when no comparison was made (bootstrap, NOOP).
    reacquired_track_id is set only when action == ACTION_SKIPPED_DRIFT and
    the on-the-fly re-acquisition pass found a gallery match among the
    visible detections.
    """
    action: str
    similarity: float
    gallery_size: int
    reacquired_track_id: Optional[int] = None
    reacquire_attempted: bool = False

_buffer_utils = None

def get_frame_bgr(buffer, video_width, video_height):
    """Extract BGR frame from GStreamer buffer for ReID cropping.

    Only called when ReID needs a frame (gallery update or re-identification).
    """
    global _buffer_utils
    if _buffer_utils is None:
        from hailo_apps.python.core.common import buffer_utils
        _buffer_utils = buffer_utils
    try:
        import cv2
        frame_rgb = _buffer_utils.get_numpy_from_buffer(
            buffer, "RGB", video_width, video_height)
        if frame_rgb is not None:
            return cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
    except Exception as e:
        LOGGER.debug("[REID] Frame extraction failed: %s", e)
    return None


def _crop_person(
    frame_bgr: np.ndarray, hailo_bbox, video_width: int, video_height: int,
) -> Optional[np.ndarray]:
    """Crop a person from the frame using Hailo normalized bbox coordinates."""
    x1 = max(0, int(hailo_bbox.xmin() * video_width))
    y1 = max(0, int(hailo_bbox.ymin() * video_height))
    x2 = min(video_width, int((hailo_bbox.xmin() + hailo_bbox.width()) * video_width))
    y2 = min(video_height, int((hailo_bbox.ymin() + hailo_bbox.height()) * video_height))
    if x2 <= x1 or y2 <= y1:
        return None
    return frame_bgr[y1:y2, x1:x2]


class ReIDManager:
    """Manages ReID gallery and re-identification for a single followed target.

    Lifecycle:
        1. User clicks a person → on_target_selected() resets gallery
        2. Each frame while following → update_gallery() stores embeddings
           every ``update_interval`` frames
        3. Tracker loses target → try_reidentify() compares all visible
           persons against the gallery and returns the best match
    """

    def __init__(self, hef_path: str, update_interval: int = 30,
                 max_gallery_size: int = 10, reid_match_threshold: float = 0.6,
                 drift_threshold: float = 0.6,
                 duplicate_threshold: float = 0.9,
                 refresh_every: int = 5,
                 min_gallery_for_drift_check: int = 2):
        self._hef_path = hef_path
        self._max_gallery_size = max_gallery_size
        self._reid_match_threshold = reid_match_threshold
        self._update_interval = update_interval
        self._drift_threshold = drift_threshold
        self._duplicate_threshold = duplicate_threshold
        self._refresh_every = refresh_every
        # Drift check over a single seed embedding is too brittle (one bad
        # outlier kicks reacquire). Wait until we have at least this many.
        self._min_gallery_for_drift_check = min_gallery_for_drift_check
        # Counts consecutive duplicate-band decisions; used to throttle the
        # refresh-oldest mechanism so the gallery doesn't go stale on a long
        # clean follow.
        self._duplicate_streak = 0
        # Extractor created lazily so the detection pipeline's VDevice is
        # always initialized first (avoids segfault on early pipeline errors).
        self._extractor = None
        self._init_lock = threading.Lock()

        from reid_analysis.gallery_strategies import MultiEmbeddingStrategy
        self._MultiEmbeddingStrategy = MultiEmbeddingStrategy
        self._gallery = MultiEmbeddingStrategy(max_k=max_gallery_size)
        self._tracking_id = None
        self._original_id = None  # ID shown in UI — stays constant through re-identifications
        self._frame_counter = 0
        self._lock = threading.Lock()
        LOGGER.debug("[REID] Configured: model=%s, update_interval=%d, "
                    "max_gallery=%d, match_thresh=%.2f, drift_thresh=%.2f, "
                    "dup_thresh=%.2f, refresh_every=%d",
                    os.path.basename(hef_path), update_interval,
                    max_gallery_size, reid_match_threshold,
                    drift_threshold, duplicate_threshold, refresh_every)

    # ------------------------------------------------------------------
    # Lazy extractor init
    # ------------------------------------------------------------------

    def _ensure_extractor(self) -> bool:
        """Create the Hailo ReID extractor on first use."""
        if self._extractor is not None:
            return True
        with self._init_lock:
            if self._extractor is not None:
                return True
            try:
                from reid_analysis.reid_embedding_extractor import HailoReIDExtractor
                self._extractor = HailoReIDExtractor(self._hef_path)
                LOGGER.debug("[REID] Extractor loaded: %s (dim=%d)",
                            self._extractor.model_name, self._extractor.embedding_dim)
                return True
            except Exception as e:
                LOGGER.error("[REID] Failed to load extractor: %s", e)
                return False

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def has_gallery(self) -> bool:
        """True if at least one embedding is stored."""
        with self._lock:
            return self._gallery.size > 0

    @property
    def tracking_id(self) -> Optional[int]:
        return self._tracking_id

    @property
    def original_id(self) -> Optional[int]:
        """The ID the target had when the operator first selected it."""
        return self._original_id

    @property
    def gallery_size(self) -> int:
        """Number of embeddings currently stored for the active target."""
        with self._lock:
            if self._original_id is None:
                return 0
            return self._gallery.embedding_count(str(self._original_id))

    @property
    def max_gallery_size(self) -> int:
        return self._max_gallery_size

    # ------------------------------------------------------------------
    # Target lifecycle
    # ------------------------------------------------------------------

    def on_target_selected(self, track_id: int) -> None:
        """Called when operator selects a (possibly new) target. Resets gallery
        if the target changed."""
        if track_id == self._tracking_id:
            return
        with self._lock:
            self._gallery = self._MultiEmbeddingStrategy(max_k=self._max_gallery_size)
            self._tracking_id = track_id
            self._original_id = track_id
            self._frame_counter = 0
            self._duplicate_streak = 0
        LOGGER.info("[REID] New target ID %d — gallery reset", track_id)

    def should_update(self) -> bool:
        """Increment frame counter and return True when it's time to sample."""
        self._frame_counter += 1
        # Always capture the first frame, then every update_interval frames
        return self._frame_counter == 1 or self._frame_counter % self._update_interval == 0

    def update_gallery(self, frame_bgr: np.ndarray, hailo_bbox,
                       video_width: int, video_height: int,
                       *, person_by_id: Optional[dict] = None
                       ) -> GalleryUpdateResult:
        """Validate and store an embedding for the currently followed person.

        Drift-protected pipeline:
          - empty gallery       → bootstrap (always store)
          - gallery still small → store unconditionally (drift check is brittle
                                  with too few reference vectors)
          - sim < drift_thresh  → drift suspected; do NOT store. If
                                  ``person_by_id`` is provided, run the
                                  re-acquisition pass (same as try_reidentify)
                                  to find the right person among visible tracks.
          - sim > duplicate_thr → near-duplicate; skip add. Every Nth such
                                  decision in a row, replace the oldest
                                  vector instead so the gallery doesn't go
                                  stale on a long clean follow.
          - middle band         → store (or FIFO-replace when full).

        Returns a ``GalleryUpdateResult`` describing the action taken plus the
        re-acquired track id when drift fired.
        """
        if not self._ensure_extractor():
            return GalleryUpdateResult(ACTION_NOOP, -1.0, 0)

        crop = _crop_person(frame_bgr, hailo_bbox, video_width, video_height)
        if crop is None or crop.size == 0:
            with self._lock:
                size = self._gallery.embedding_count(str(self._original_id))
            return GalleryUpdateResult(ACTION_NOOP, -1.0, size)

        # Embedding extraction is a Hailo NPU call — must run outside the lock
        # so re-identification on a parallel call is never blocked behind it.
        try:
            emb = self._extractor.extract_embedding(crop)
        except Exception as e:
            LOGGER.warning("[REID] Gallery update extraction failed: %s", e)
            with self._lock:
                size = self._gallery.embedding_count(str(self._original_id))
            return GalleryUpdateResult(ACTION_NOOP, -1.0, size)

        name = str(self._original_id)
        sim = -1.0
        action = ACTION_NOOP
        size = 0

        with self._lock:
            if self._gallery.size == 0:
                self._gallery.add_person(name, emb)
                action = ACTION_BOOTSTRAP
                size = self._gallery.embedding_count(name)
            else:
                sim = self._gallery.max_similarity(name, emb)
                size_before = self._gallery.embedding_count(name)

                if size_before < self._min_gallery_for_drift_check:
                    # Bootstrap-protect: too few reference vectors for a
                    # reliable drift check — just append.
                    self._gallery.update(name, emb, self._frame_counter)
                    action = ACTION_ADDED
                    self._duplicate_streak = 0
                    size = self._gallery.embedding_count(name)
                elif sim < self._drift_threshold:
                    # Suspected drift — reacquire happens after lock release.
                    action = ACTION_SKIPPED_DRIFT
                    self._duplicate_streak = 0
                    size = size_before
                elif sim > self._duplicate_threshold:
                    self._duplicate_streak += 1
                    if self._duplicate_streak >= self._refresh_every:
                        self._gallery.replace_oldest(name, emb)
                        self._duplicate_streak = 0
                        action = ACTION_REFRESHED
                    else:
                        action = ACTION_SKIPPED_DUPLICATE
                    size = self._gallery.embedding_count(name)
                else:
                    self._gallery.update(name, emb, self._frame_counter)
                    action = ACTION_ADDED
                    self._duplicate_streak = 0
                    size = self._gallery.embedding_count(name)

        # Drift consequences run outside the lock — the reacquire pass calls
        # back into the gallery and would deadlock otherwise.
        reacquired = None
        reacquire_attempted = False
        if action == ACTION_SKIPPED_DRIFT and person_by_id:
            LOGGER.info(
                "[REID DRIFT] target=%s sim=%.3f < %.2f — reacquiring among %d visible",
                self._original_id, sim, self._drift_threshold, len(person_by_id),
            )
            reacquire_attempted = True
            reacquired = self._reacquire(
                frame_bgr, person_by_id, video_width, video_height,
                log_prefix="[REID DRIFT]",
            )

        # INFO logs — one line per call so the operator can see decisions live.
        if action == ACTION_BOOTSTRAP:
            LOGGER.info("[REID GALLERY] bootstrap stored for ID %s (1/%d)",
                        self._original_id, self._max_gallery_size)
        elif action == ACTION_ADDED:
            LOGGER.info("[REID GALLERY] added sim=%.3f size=%d/%d",
                        sim, size, self._max_gallery_size)
        elif action == ACTION_SKIPPED_DUPLICATE:
            LOGGER.info("[REID GALLERY] skip-similar sim=%.3f size=%d/%d streak=%d",
                        sim, size, self._max_gallery_size, self._duplicate_streak)
        elif action == ACTION_REFRESHED:
            LOGGER.info("[REID GALLERY] refreshed (replaced oldest) sim=%.3f size=%d/%d",
                        sim, size, self._max_gallery_size)
        elif action == ACTION_SKIPPED_DRIFT:
            if reacquired is not None and reacquired != self._tracking_id:
                LOGGER.info("[REID GALLERY] drift sim=%.3f -> reacquired as ID %d",
                            sim, reacquired)
            elif reacquired is not None:
                LOGGER.info("[REID GALLERY] drift sim=%.3f but reID confirms same ID %d (false drift)",
                            sim, reacquired)
            elif reacquire_attempted:
                LOGGER.info("[REID GALLERY] drift sim=%.3f -> reacquire failed; will hold/search",
                            sim)
            else:
                LOGGER.info("[REID GALLERY] drift sim=%.3f -> no visible candidates",
                            sim)

        return GalleryUpdateResult(
            action=action,
            similarity=sim,
            gallery_size=size,
            reacquired_track_id=reacquired,
            reacquire_attempted=reacquire_attempted,
        )

    # ------------------------------------------------------------------
    # Re-identification
    # ------------------------------------------------------------------

    def _reacquire(self, frame_bgr: np.ndarray, person_by_id: dict,
                   video_width: int, video_height: int,
                   *, log_prefix: str = "[REID]") -> Optional[int]:
        """Pure search loop: crop all visible persons, batch-extract, pick best
        gallery match above ``reid_match_threshold``.

        Shared between the "tracker lost target" path (try_reidentify) and the
        "drift suspected at gallery-update time" path. Does not mutate any
        ReIDManager state — caller decides what to do with the returned id.
        """
        with self._lock:
            if self._gallery.size == 0:
                return None
            gallery_count = self._gallery.embedding_count(str(self._original_id))

        if not person_by_id:
            return None

        LOGGER.debug("%s Searching for target ID %s among %d visible persons (gallery: %d embeddings)",
                     log_prefix, self._tracking_id, len(person_by_id), gallery_count)

        crops = []
        tids = []
        for tid, person in person_by_id.items():
            crop = _crop_person(frame_bgr, person.get_bbox(), video_width, video_height)
            if crop is not None and crop.size > 0:
                crops.append(crop)
                tids.append(tid)

        if not crops:
            return None

        try:
            embeddings = self._extractor.extract_embeddings_batch(crops)
        except Exception as e:
            LOGGER.warning("%s Batch extraction failed: %s", log_prefix, e)
            return None

        # First pass: score every candidate against the gallery (irrespective
        # of threshold). This gives us the absolute best similarity in the
        # frame, which we want in the operator-facing INFO log even when no
        # candidate crosses the match threshold.
        sims_log = []
        with self._lock:
            for tid, emb in zip(tids, embeddings):
                _, sim = self._gallery.match(emb, 0.0)
                sims_log.append((tid, sim))

        # Pick the highest-scoring candidate that also clears the threshold.
        best_tid, best_sim = None, -1.0
        for tid, sim in sims_log:
            if sim >= self._reid_match_threshold and sim > best_sim:
                best_tid, best_sim = tid, sim

        # Top score across all candidates (useful when no match crossed the
        # threshold — tells the operator how close we got).
        top_tid, top_sim = max(sims_log, key=lambda ts: ts[1])

        for tid, sim in sims_log:
            match_str = " << MATCH" if tid == best_tid else ""
            LOGGER.info("%s   ID %d  sim=%.3f  (threshold=%.2f)%s",
                         log_prefix, tid, sim, self._reid_match_threshold, match_str)

        if best_tid is not None:
            LOGGER.info("%s Re-identified target as track ID %d "
                        "(best sim=%.3f, candidates=%d, threshold=%.2f)",
                        log_prefix, best_tid, best_sim, len(sims_log),
                        self._reid_match_threshold)
        else:
            LOGGER.info("%s No match — best candidate ID %d sim=%.3f "
                        "(candidates=%d, threshold=%.2f)",
                        log_prefix, top_tid, top_sim, len(sims_log),
                        self._reid_match_threshold)
        return best_tid

    def try_reidentify(self, frame_bgr: np.ndarray, person_by_id: dict,
                       video_width: int, video_height: int) -> Optional[int]:
        """Try to find the lost target among visible persons.

        Thin wrapper around ``_reacquire`` that also handles lazy extractor init.
        Used by the callback when the tracker reports the target as lost.
        """
        if not self._ensure_extractor():
            return None
        return self._reacquire(frame_bgr, person_by_id, video_width, video_height,
                               log_prefix="[REID LOST]")

    def score_visible_persons(self, frame_bgr: np.ndarray, persons,
                              video_width: int, video_height: int):
        """Score raw (untracked) detections against the gallery.

        Used by the callback when persons are visible but the tracker activated
        zero tracks for them. The returned tuple is::

            (best_sim, best_person_or_None)

        ``best_person_or_None`` is non-None only when the best similarity
        crosses ``reid_match_threshold`` — the caller can then drive the
        controller from that detection's bbox even though no tracker id
        exists for it. Logs an INFO line either way so the operator sees the
        score even when no match is taken.
        """
        if not self._ensure_extractor():
            return -1.0, None
        with self._lock:
            if self._gallery.size == 0:
                return -1.0, None

        kept_persons = []
        crops = []
        for person in persons:
            crop = _crop_person(frame_bgr, person.get_bbox(), video_width, video_height)
            if crop is not None and crop.size > 0:
                crops.append(crop)
                kept_persons.append(person)

        if not crops:
            return -1.0, None

        try:
            embeddings = self._extractor.extract_embeddings_batch(crops)
        except Exception as e:
            LOGGER.warning("[REID SEARCH] Batch extraction failed: %s", e)
            return -1.0, None

        with self._lock:
            sims = [self._gallery.match(emb, 0.0)[1] for emb in embeddings]

        best_idx = int(np.argmax(sims))
        best_sim = float(sims[best_idx])
        best_person = kept_persons[best_idx] if best_sim >= self._reid_match_threshold else None

        if best_person is not None:
            LOGGER.info("[REID SEARCH] tracker has no tracks — raw-detection MATCH "
                        "sim=%.3f among %d visible (threshold=%.2f, gallery=%d/%d) — "
                        "driving controller from raw bbox",
                        best_sim, len(sims), self._reid_match_threshold,
                        self.gallery_size, self._max_gallery_size)
        else:
            LOGGER.info("[REID SEARCH] tracker has no tracks — best raw-detection "
                        "sim=%.3f among %d visible (threshold=%.2f, gallery=%d/%d)",
                        best_sim, len(sims), self._reid_match_threshold,
                        self.gallery_size, self._max_gallery_size)
        return best_sim, best_person

    def on_reidentified(self, new_track_id: int) -> None:
        """Update internal tracking ID after successful re-identification."""
        self._tracking_id = new_track_id
        # Reset frame counter so we immediately capture a fresh embedding
        self._frame_counter = 0
        # Streak tracking is per-target — drop it on a switch.
        self._duplicate_streak = 0
        LOGGER.info("[REID] Tracking resumed via ReID for ID %s", self._original_id)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Clear gallery and tracking state."""
        with self._lock:
            self._gallery = self._MultiEmbeddingStrategy(max_k=self._max_gallery_size)
            self._tracking_id = None
            self._original_id = None
            self._frame_counter = 0
            self._duplicate_streak = 0

    def release(self) -> None:
        """Release Hailo NPU resources."""
        if self._extractor is None:
            return
        try:
            self._extractor.release()
            LOGGER.debug("[REID] Extractor released")
        except Exception as e:
            LOGGER.warning("[REID] Failed to release extractor: %s", e)
