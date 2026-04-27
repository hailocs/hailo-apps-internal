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
from typing import Optional

import numpy as np

LOGGER = logging.getLogger(__name__)

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
                 max_gallery_size: int = 10, reid_match_threshold: float = 0.6):
        self._hef_path = hef_path
        self._max_gallery_size = max_gallery_size
        self._reid_match_threshold = reid_match_threshold
        self._update_interval = update_interval
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
                    "max_gallery=%d, threshold=%.2f",
                    os.path.basename(hef_path), update_interval,
                    max_gallery_size, reid_match_threshold)

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
        LOGGER.debug("[REID] New target ID %d — gallery reset", track_id)

    def should_update(self) -> bool:
        """Increment frame counter and return True when it's time to sample."""
        self._frame_counter += 1
        # Always capture the first frame, then every update_interval frames
        return self._frame_counter == 1 or self._frame_counter % self._update_interval == 0

    def update_gallery(self, frame_bgr: np.ndarray, hailo_bbox,
                       video_width: int, video_height: int) -> None:
        """Extract embedding from the followed person's crop and store it."""
        if not self._ensure_extractor():
            return
        crop = _crop_person(frame_bgr, hailo_bbox, video_width, video_height)
        if crop is None or crop.size == 0:
            return
        try:
            emb = self._extractor.extract_embedding(crop)
            name = str(self._original_id)
            with self._lock:
                if self._gallery.size == 0:
                    self._gallery.add_person(name, emb)
                    LOGGER.debug("[REID] Gallery: first embedding stored for ID %d", self._original_id)
                else:
                    count_before = self._gallery.embedding_count(name)
                    self._gallery.update(name, emb, self._frame_counter)
                    count = self._gallery.embedding_count(name)
                    if count_before >= self._max_gallery_size:
                        LOGGER.debug("[REID] Gallery: replaced oldest embedding for ID %d (%d/%d stored)",
                                    self._original_id, count, self._max_gallery_size)
                    else:
                        LOGGER.debug("[REID] Gallery: embedding added for ID %d (%d/%d stored)",
                                    self._original_id, count, self._max_gallery_size)
        except Exception as e:
            LOGGER.warning("[REID] Gallery update failed: %s", e)

    # ------------------------------------------------------------------
    # Re-identification
    # ------------------------------------------------------------------

    def try_reidentify(self, frame_bgr: np.ndarray, person_by_id: dict,
                       video_width: int, video_height: int) -> Optional[int]:
        """Try to find the lost target among visible persons.

        Args:
            frame_bgr: Current frame in BGR format.
            person_by_id: {track_id: hailo_detection} of visible persons.
            video_width, video_height: Frame dimensions for crop calculation.

        Returns:
            The track_id of the re-identified person, or None.
        """
        if not self._ensure_extractor():
            return None

        with self._lock:
            if self._gallery.size == 0:
                return None
            gallery_count = self._gallery.embedding_count(str(self._original_id))

        if not person_by_id:
            return None

        LOGGER.debug("[REID] Searching for lost target ID %d among %d visible persons (gallery: %d embeddings)",
                    self._tracking_id, len(person_by_id), gallery_count)

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
            LOGGER.warning("[REID] Batch extraction failed: %s", e)
            return None

        best_tid = None
        best_sim = -1.0
        sims_log = []
        with self._lock:
            for tid, emb in zip(tids, embeddings):
                _, sim = self._gallery.match(emb, 0.0)  # get similarity regardless of threshold
                sims_log.append((tid, sim))
                if sim >= self._reid_match_threshold and sim > best_sim:
                    best_sim = sim
                    best_tid = tid

        for tid, sim in sims_log:
            match_str = " << MATCH" if tid == best_tid else ""
            LOGGER.debug("[REID]   ID %d  sim=%.3f  (threshold=%.2f)%s",
                        tid, sim, self._reid_match_threshold, match_str)

        if best_tid is not None:
            LOGGER.debug("[REID] Re-identified target as track ID %d (sim=%.3f)", best_tid, best_sim)
        else:
            LOGGER.debug("[REID] No match found (best sim=%.3f, threshold=%.2f)",
                        max(s for _, s in sims_log) if sims_log else 0.0,
                        self._reid_match_threshold)
        return best_tid

    def on_reidentified(self, new_track_id: int) -> None:
        """Update internal tracking ID after successful re-identification."""
        self._tracking_id = new_track_id
        # Reset frame counter so we immediately capture a fresh embedding
        self._frame_counter = 0
        LOGGER.debug("[REID] Tracking resumed with new ID %d", new_track_id)

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

    def release(self) -> None:
        """Release Hailo NPU resources."""
        if self._extractor is None:
            return
        try:
            self._extractor.release()
            LOGGER.debug("[REID] Extractor released")
        except Exception as e:
            LOGGER.warning("[REID] Failed to release extractor: %s", e)
