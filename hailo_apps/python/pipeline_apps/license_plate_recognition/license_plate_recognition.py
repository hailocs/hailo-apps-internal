# Standard library imports
import os
import sys
import re
import json
import time
import threading
import shutil
from datetime import datetime

# Third-party imports
import gi

gi.require_version("Gst", "1.0")

import hailo
try:
    from hailo import HailoTracker
except Exception:  # pragma: no cover
    HailoTracker = None

# Local application-specific imports
from hailo_apps.python.pipeline_apps.license_plate_recognition.license_plate_recognition_pipeline import (
    GStreamerLPRApp,
)
from hailo_apps.python.core.common.db_handler import LPRDatabaseHandler
from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.gstreamer.gstreamer_app import app_callback_class

hailo_logger = get_logger(__name__)


def lpr_debug_enabled() -> bool:
    val = os.getenv("HAILO_LPR_DEBUG")
    if val is None:
        return False
    return val.strip().lower() not in ("0", "false", "no", "off")


def lpr_dbg(msg: str, *args) -> None:
    if not lpr_debug_enabled():
        return
    text = msg % args if args else msg
    print(f"[lpr_py] {text}")


def init_lpr_db():
    """Initialize the LPR DB + JSON mirror once at app start."""
    lpr_db_dir = os.path.join(os.path.dirname(__file__), "lpr_database")
    os.makedirs(lpr_db_dir, exist_ok=True)
    lpr_db_json = os.path.join(lpr_db_dir, "lpr_tracks.jsonl")
    # Clean previous run artifacts (files only)
    for stale_path in (
        os.path.join(lpr_db_dir, "lpr.db"),
        lpr_db_json,
    ):
        try:
            if os.path.isfile(stale_path):
                os.remove(stale_path)
            elif os.path.isdir(stale_path):
                # Remove directory and its contents to ensure clean start
                shutil.rmtree(stale_path, ignore_errors=False)
        except Exception as exc:  # pragma: no cover - defensive
            hailo_logger.warning("Failed to remove stale LPR DB path %s: %s", stale_path, exc)
    try:
        handler = LPRDatabaseHandler(
            db_name="lpr.db",
            table_name="lpr_tracks",
            database_dir=lpr_db_dir,
            json_export_path=lpr_db_json,
        )
        hailo_logger.info("LPR DB initialized at %s (JSON: %s)", lpr_db_dir, lpr_db_json)
        return handler, lpr_db_json
    except Exception as exc:  # pragma: no cover - defensive logging
        hailo_logger.error("Failed to init LPR DB: %s", exc)
        return None, None


class user_app_callback_class(app_callback_class):
    def __init__(self, lpr_db=None, lpr_db_json=None):
        super().__init__()
        self.output_file = "ocr_results.txt"
        self.save_ocr_results = True  # Enable/disable OCR result saving
        self.disable_found_lp_gate = False

        # LPR DB + JSON mirror (for C++ consumption)
        self.lpr_db = lpr_db
        self.lpr_db_json = lpr_db_json
        self.lpr_tracks_state: dict[int, dict] = {}
        self._jsonl_tailer_thread = None
        self._jsonl_tailer_stop = False
        if self.lpr_db_json:
            self._start_jsonl_tailer()

        # Per-track state
        self.found_lp_tracks: set[int] = set()
        self.vehicle_tracks: dict[int, dict] = {}
        self.ocr_results: dict[int, list] = {}  # track_id -> list of (plate_text, confidence, frame_num, timestamp)
        self._start_time = datetime.now()
        
        # Initialize OCR results file with header
        if self.save_ocr_results:
            with open(self.output_file, "w", encoding="utf-8") as f:
                f.write(f"# LPR OCR Results - Started at {self._start_time.isoformat()}\n")
                f.write("# Format: Frame | Timestamp | Track_ID | Plate_Text | Confidence\n")
                f.write("-" * 80 + "\n")

    def write_ocr_text(self, text: str, confidence: float | None = None, track_id: int | None = None) -> None:
        if not self.save_ocr_results:
            return
            
        frame_num = self.get_count()
        elapsed = (datetime.now() - self._start_time).total_seconds()
        timestamp = f"{elapsed:.2f}s"
        track_str = str(track_id) if track_id is not None else "N/A"
        conf_str = f"{confidence:.2f}" if confidence is not None else "N/A"
        
        # Store in memory for potential later use
        if track_id is not None:
            if track_id not in self.ocr_results:
                self.ocr_results[track_id] = []
            self.ocr_results[track_id].append((text, confidence, frame_num, elapsed))
        
        # Write to file
        with open(self.output_file, "a", encoding="utf-8") as f:
            f.write(f"Frame {frame_num:6d} | {timestamp:>8s} | Track {track_str:>4s} | {text:<20s} | Conf: {conf_str}\n")

    def _start_jsonl_tailer(self) -> None:
        if not self.lpr_db_json:
            return

        def tailer():
            position = 0
            while not getattr(self, "_jsonl_tailer_stop", False):
                try:
                    with open(self.lpr_db_json, "r", encoding="utf-8") as f:
                        f.seek(position)
                        for line in f:
                            position = f.tell()
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                event = json.loads(line)
                                self._apply_jsonl_event(event)
                            except Exception as exc:  # pragma: no cover
                                hailo_logger.debug("Failed to parse LPR JSONL line: %s", exc)
                    time.sleep(0.2)
                except FileNotFoundError:
                    time.sleep(0.5)
                except Exception as exc:  # pragma: no cover
                    hailo_logger.debug("LPR JSONL tailer error: %s", exc)
                    time.sleep(0.5)

        self._jsonl_tailer_thread = threading.Thread(target=tailer, daemon=True)
        self._jsonl_tailer_thread.start()

    def _apply_jsonl_event(self, event: dict) -> None:
        evt = event.get("event")
        if evt not in {"upsert", "delete", "clear"}:
            return
        if evt == "clear":
            self.lpr_tracks_state.clear()
            return
        track_id = event.get("track_id")
        if track_id is None:
            return
        try:
            track_id_int = int(track_id)
        except (TypeError, ValueError):
            return

        if evt == "delete":
            self.lpr_tracks_state.pop(track_id_int, None)
            return

        has_lpr = bool(event.get("has_lpr", False))
        lpr_result = event.get("lpr_result") or ""
        ts = event.get("timestamp", 0)

        self.lpr_tracks_state[track_id_int] = {
            "has_lpr": has_lpr,
            "lpr_result": lpr_result,
            "timestamp": ts,
        }

        # Optionally mirror into LanceDB without re-emitting JSON
        if self.lpr_db:
            try:
                self.lpr_db.upsert_track(
                    track_id=track_id_int,
                    has_lpr=has_lpr,
                    lpr_result=lpr_result,
                    emit_json=False,
                )
            except Exception as exc:  # pragma: no cover
                hailo_logger.debug("Failed to mirror JSONL event to LanceDB: %s", exc)

    def record_track_seen(self, track_id: int) -> None:
        """Ensure track exists in LPR DB with has_lpr flag False."""
        if not hasattr(self, "lpr_db") or self.lpr_db is None:
            return
        try:
            self.lpr_db.upsert_track(track_id=track_id, has_lpr=False)
        except Exception as exc:  # pragma: no cover - keep callback resilient
            hailo_logger.debug("LPR DB upsert failed for track %s: %s", track_id, exc)

    def record_plate_result(self, track_id: int, plate_text: str) -> None:
        """Persist an accepted plate result to LPR DB + JSON mirror."""
        if track_id is None:
            return
        if not hasattr(self, "lpr_db") or self.lpr_db is None:
            return
        try:
            self.lpr_db.mark_plate_found(track_id=track_id, lpr_result=plate_text)
        except Exception as exc:  # pragma: no cover - keep callback resilient
            hailo_logger.debug("LPR DB mark_plate_found failed for track %s: %s", track_id, exc)

    def reset_state(self) -> None:
        """Reset per-run state when the pipeline restarts (e.g., video loops)."""
        self.found_lp_tracks.clear()
        self.vehicle_tracks.clear()
        self.ocr_results.clear()
        self._start_time = datetime.now()



def _iter_classifications(roi):
    """Iterate through all classifications in the ROI hierarchy.
    
    The LPR hierarchy is:
      ROI → Vehicle Detection → License Plate Detection → Classification (OCR result)
    
    This function yields (parent_detection, classification) tuples at all levels.
    """
    if roi is None:
        return

    # Top-level detections (vehicles)
    detections = roi.get_objects_typed(hailo.HAILO_DETECTION)
    for det in detections:
        # Classifications directly on vehicle detection
        for cls in det.get_objects_typed(hailo.HAILO_CLASSIFICATION):
            yield det, cls
        
        # Nested detections (license plates inside vehicles)
        nested_detections = det.get_objects_typed(hailo.HAILO_DETECTION)
        for nested_det in nested_detections:
            # Classifications on nested detection (OCR results on license plates)
            for cls in nested_det.get_objects_typed(hailo.HAILO_CLASSIFICATION):
                yield nested_det, cls

    # Classifications directly on ROI
    for cls in roi.get_objects_typed(hailo.HAILO_CLASSIFICATION):
        yield None, cls


def _parse_bool_env(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "y", "on")


def _no_skip_enabled() -> bool:
    return _parse_bool_env("HAILO_LPR_NO_SKIP", False)


def _should_hide_lp_overlay() -> bool:
    """Check if LP overlay should be hidden (only draw vehicles, not license plates)."""
    return _parse_bool_env("HAILO_LPR_HIDE_LP", False)


def _should_update_track_labels() -> bool:
    """Check if track labels should be updated when a valid plate is found."""
    return _parse_bool_env("HAILO_LPR_UPDATE_LABELS", True)


def _parse_int_env(name: str, default: int) -> int:
    val = os.getenv(name)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        return default


def _parse_int_set_env(name: str, default: set[int]) -> set[int]:
    val = os.getenv(name)
    if not val:
        return default
    out: set[int] = set()
    for token in val.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            out.add(int(token))
        except ValueError:
            continue
    return out or default


def _normalize_ocr_label(raw_label: str, allow_alpha: bool) -> str:
    if allow_alpha:
        return re.sub(r"[^0-9A-Za-z]", "", raw_label).upper()
    return re.sub(r"\D", "", raw_label)


def _is_plate_valid(normalized_label: str, min_len: int, max_len: int, preferred_lens: set[int], 
                     allow_alpha: bool, country: str, confidence: float) -> bool:
    """Check if a license plate is valid based on length, format, and country-specific rules.
    
    Args:
        normalized_label: The normalized plate text
        min_len: Minimum acceptable length
        max_len: Maximum acceptable length
        preferred_lens: Set of preferred lengths (e.g., {7, 8})
        allow_alpha: Whether alphabetic characters are allowed
        country: Country code (e.g., "IL", "US", "EU")
        confidence: OCR confidence score
        
    Returns:
        True if the plate is considered valid, False otherwise
    """
    # Basic length check
    if not (min_len <= len(normalized_label) <= max_len):
        return False
    
    # Country-specific validation
    if country == "IL" or country == "IS":
        # Israel: digits only, 7-8 digits
        if not normalized_label.isdigit():
            return False
        if len(normalized_label) not in {7, 8}:
            return False
    elif country == "US":
        # US: alphanumeric, length 5-8
        if len(normalized_label) < 5 or len(normalized_label) > 8:
            return False
    elif country == "EU":
        # EU: alphanumeric, length 5-8, must include at least one letter and one digit
        if len(normalized_label) < 5 or len(normalized_label) > 8:
            return False
        has_letter = any(c.isalpha() for c in normalized_label)
        has_digit = any(c.isdigit() for c in normalized_label)
        if not (has_letter and has_digit):
            return False
    
    # Check if length is in preferred set (bonus validation)
    if preferred_lens and len(normalized_label) not in preferred_lens:
        # Still valid, but not preferred - you might want to be stricter here
        pass
    
    # Additional validation: check for obviously invalid patterns
    # Reject if all characters are the same (e.g., "1111111")
    if len(set(normalized_label)) == 1:
        return False
    
    # Reject if too many repeated characters (e.g., "1111222")
    if len(normalized_label) > 4:
        char_counts = {}
        for char in normalized_label:
            char_counts[char] = char_counts.get(char, 0) + 1
        max_repeat = max(char_counts.values())
        if max_repeat > len(normalized_label) * 0.6:  # More than 60% same character
            return False
    
    return True


def app_callback(element, buffer, user_data):
    frame_count = user_data.get_count() if hasattr(user_data, "get_count") else "n/a"
    lpr_dbg("callback: ENTER frame=%s", getattr(user_data, "get_count", lambda: "n/a")())
    frame_tag = f"Frame {frame_count} " if (lpr_debug_enabled() or _no_skip_enabled()) else ""
    if buffer is None:
        lpr_dbg("callback: buffer is None => EXIT")
        return

    roi = hailo.get_roi_from_buffer(buffer)
    if roi is None:
        lpr_dbg("callback: roi is None => EXIT")
        return

    # Tracks that already have an accepted LP (either from this run or from DB mirror)
    try:
        db_tracks_with_lp = {
            tid
            for tid, info in getattr(user_data, "lpr_tracks_state", {}).items()
            if info.get("has_lpr") and info.get("lpr_result")
        }
    except Exception:
        db_tracks_with_lp = set()
    in_memory_found = getattr(user_data, "found_lp_tracks", set())
    skip_tracks_enabled = not _no_skip_enabled()
    if skip_tracks_enabled:
        skip_lp_tracks = set(in_memory_found) | db_tracks_with_lp
        if skip_lp_tracks:
            lpr_dbg("callback: skip_lp_tracks (already have LP)=%s", sorted(skip_lp_tracks))
    else:
        skip_lp_tracks = set()
        lpr_dbg("callback: skip disabled (HAILO_LPR_NO_SKIP=1)")

    # Track vehicles and mark found_lp per tracker ID.
    detections = roi.get_objects_typed(hailo.HAILO_DETECTION)
    vehicles = []
    plates = []
    nested_plates_by_track: dict[int, list] = {}
    for det in detections:
        label = det.get_label() or ""
        if label == "vehicle":
            uid = det.get_objects_typed(hailo.HAILO_UNIQUE_ID)
            track_id = uid[0].get_id() if uid else 0
            vehicles.append((track_id, det))
        elif label == "license_plate":
            plates.append(det)

    # Plates can be nested under vehicle detections depending on the cropper/aggregator
    for _, vdet in vehicles:
        uid = vdet.get_objects_typed(hailo.HAILO_UNIQUE_ID)
        track_id = uid[0].get_id() if uid else 0
        for nested in vdet.get_objects_typed(hailo.HAILO_DETECTION):
            if (nested.get_label() or "") == "license_plate":
                nested_plates_by_track.setdefault(track_id, []).append(nested)
                plates.append(nested)
    
    # Collect all classifications for debugging and processing
    all_classifications = list(_iter_classifications(roi))
    ocr_results = [(det, cls) for det, cls in all_classifications 
                   if (cls.get_classification_type() if hasattr(cls, 'get_classification_type') else "") == "text_region"]
    
    # DEBUG: Print frame summary (opt-in via HAILO_LPR_DEBUG)
    if lpr_debug_enabled():
        vehicle_tracks = [t for t, _ in vehicles]
        print(
            f"[DEBUG] Frame {frame_count}: vehicles={len(vehicles)} (tracks={vehicle_tracks}), "
            f"plates={len(plates)}, nested_plates={sum(len(v) for v in nested_plates_by_track.values())}, "
            f"OCR_results={len(ocr_results)}"
        )

        # DEBUG: Show all classifications found (including non-OCR)
        for det, cls in all_classifications:
            cls_type = cls.get_classification_type() if hasattr(cls, 'get_classification_type') else ""
            label = cls.get_label() or ""
            conf = cls.get_confidence() if hasattr(cls, 'get_confidence') else 0.0
            det_label = det.get_label() if det else "no_det"
            track_id = None
            if det:
                uid = det.get_objects_typed(hailo.HAILO_UNIQUE_ID)
                if uid:
                    track_id = uid[0].get_id()
            print(
                f"[DEBUG]   Classification: type='{cls_type}' label='{label}' "
                f"conf={conf:.3f} det='{det_label}' track={track_id}"
            )
    
    lpr_dbg(
        "callback: detections=%d vehicles=%d plates=%d nested_tracks=%d",
        len(detections),
        len(vehicles),
        len(plates),
        len(nested_plates_by_track),
    )

    # Build a quick index from plate -> best-matching vehicle (center-in-bbox)
    newly_found_tracks: set[int] = set()
    # Prefer direct association when plates are nested under a vehicle detection.
    if nested_plates_by_track:
        for track_id, plate_list in nested_plates_by_track.items():
            if track_id in skip_lp_tracks:
                continue
            if not plate_list:
                continue
            newly_found_tracks.add(track_id)

    elif vehicles and plates:
        for plate in plates:
            pb = plate.get_bbox()
            pcx = (pb.xmin() + pb.xmax()) / 2.0
            pcy = (pb.ymin() + pb.ymax()) / 2.0
            best_track = None
            best_area = None
            for track_id, vdet in vehicles:
                vb = vdet.get_bbox()
                if vb.xmin() <= pcx <= vb.xmax() and vb.ymin() <= pcy <= vb.ymax():
                    area = vb.width() * vb.height()
                    if best_area is None or area < best_area:
                        best_area = area
                        best_track = track_id
            if best_track is None:
                continue
            if best_track in skip_lp_tracks:
                continue
            newly_found_tracks.add(best_track)

    if newly_found_tracks:
        lpr_dbg("callback: newly_found_tracks=%s", sorted(newly_found_tracks))
        for track_id in newly_found_tracks:
            try:
                user_data.record_track_seen(track_id)
            except Exception:
                hailo_logger.debug("Failed to record track %s in LPR DB", track_id)

    # Update per-track vehicle info
    for track_id, vdet in vehicles:
        vb = vdet.get_bbox()
        conf = vdet.get_confidence()
        found = (track_id in getattr(user_data, "found_lp_tracks", set())) or (track_id in newly_found_tracks)
        user_data.vehicle_tracks[track_id] = {
            "bbox": (vb.xmin(), vb.ymin(), vb.xmax(), vb.ymax()),
            "confidence": float(conf),
            "last_seen_frame": int(user_data.get_count()),
            "found_lp": bool(found),
        }

    # Process OCR results - iterate through all classifications to find text_region (OCR results)
    country_env = os.getenv("HAILO_LPR_COUNTRY")
    country = country_env.strip().upper() if country_env else "IL"
    min_len_env = os.getenv("HAILO_LPR_MIN_LEN")
    max_len_env = os.getenv("HAILO_LPR_MAX_LEN")
    preferred_env = os.getenv("HAILO_LPR_PREFERRED_LENS")
    allow_alpha_env = os.getenv("HAILO_LPR_ALLOW_ALPHA")

    min_len = max(1, _parse_int_env("HAILO_LPR_MIN_LEN", 3))
    max_len = max(min_len, _parse_int_env("HAILO_LPR_MAX_LEN", 10))
    preferred_lens = _parse_int_set_env("HAILO_LPR_PREFERRED_LENS", {7, 8})
    allow_alpha = _parse_bool_env("HAILO_LPR_ALLOW_ALPHA", False)

    if country in {"IL", "IS"}:
        if min_len_env is None and max_len_env is None:
            min_len = 7
            max_len = 8
        if preferred_env is None:
            preferred_lens = {7, 8}
        if allow_alpha_env is None:
            allow_alpha = False
    
    vehicles_by_track = {track_id: vdet for track_id, vdet in vehicles}
    try:
        tracker = HailoTracker.get_instance() if HailoTracker is not None else None
        tracker_names = tracker.get_trackers_list() if tracker is not None else []
        tracker_name = tracker_names[0] if tracker_names else None
    except Exception:
        tracker = None
        tracker_name = None

    accepted_ocr = 0
    best_by_track: dict[int | None, dict] = {}
    for det, cls in all_classifications:
        cls_type = cls.get_classification_type() if hasattr(cls, 'get_classification_type') else ""
        label = cls.get_label()
        if not label:
            continue
        
        # Only process OCR results (text_region classification type)
        if cls_type != "text_region":
            continue

        raw_label = label.strip()
        normalized_label = _normalize_ocr_label(raw_label, allow_alpha)
        digits_label = re.sub(r"\D", "", raw_label)
        simple_ok = len(digits_label) in {7, 8}
        confidence = cls.get_confidence()
        track_id = None
        if det is not None:
            uid = det.get_objects_typed(hailo.HAILO_UNIQUE_ID)
            if uid:
                track_id = uid[0].get_id()
        track_str = f"Track {track_id}" if track_id is not None else "No Track"
        if track_id is not None and track_id in skip_lp_tracks:
            continue
        print(
            f"[LPR] {frame_tag}OCR Raw: '{label}' (digits='{digits_label}' simple_ok={int(simple_ok)}) "
            f"(Confidence: {confidence:.2f}, {track_str})"
        )
        if not (min_len <= len(normalized_label) <= max_len):
            print(
                f"[LPR] {frame_tag}OCR Reject (len): norm='{normalized_label}' "
                f"len={len(normalized_label)} range=[{min_len},{max_len}] "
                f"(Confidence: {confidence:.2f}, {track_str})"
            )
            continue
        score = (len(normalized_label) in preferred_lens, len(normalized_label))
        existing = best_by_track.get(track_id)
        if existing is None or score > existing["score"]:
            best_by_track[track_id] = {
                "score": score,
                "label": normalized_label,
                "confidence": float(confidence),
                "track_id": track_id,
                "det": det,
            }
            lpr_dbg(
                "callback: candidate track=%s raw='%s' norm='%s' conf=%.3f score=%s",
                track_id if track_id is not None else "None",
                raw_label,
                normalized_label,
                float(confidence),
                score,
            )

    for candidate in best_by_track.values():
        normalized_label = candidate["label"]
        confidence = candidate["confidence"]
        track_id = candidate["track_id"]
        det = candidate["det"]
        track_str = f"Track {track_id}" if track_id is not None else "No Track"

        if track_id is not None and track_id in skip_lp_tracks:
            continue

        # Validate the plate before processing
        is_valid = _is_plate_valid(
            normalized_label=normalized_label,
            min_len=min_len,
            max_len=max_len,
            preferred_lens=preferred_lens,
            allow_alpha=allow_alpha,
            country=country,
            confidence=confidence
        )
        
        if not is_valid:
            print(
                f"[LPR] {frame_tag}OCR Reject (validation): norm='{normalized_label}' "
                f"(Confidence: {confidence:.2f}, {track_str})"
            )
            continue

        # Print to console
        print(
            f"[LPR] {frame_tag}OCR Result (VALID): '{normalized_label}' "
            f"(Confidence: {confidence:.2f}, {track_str})"
        )
        lpr_dbg(
            "callback: accepted track=%s plate='%s' conf=%.3f",
            track_id if track_id is not None else "None",
            normalized_label,
            float(confidence),
        )
        accepted_ocr += 1
        try:
            user_data.record_plate_result(track_id=track_id, plate_text=normalized_label)
        except Exception:
            hailo_logger.debug("Failed to persist LPR result for track %s", track_id)

        if track_id is not None:
            user_data.found_lp_tracks.add(track_id)
            skip_lp_tracks.add(track_id)
            if track_id in user_data.vehicle_tracks:
                user_data.vehicle_tracks[track_id]["found_lp"] = True

        # Attach the accepted plate text to the detection and tracker.
        if det is not None:
            try:
                existing_cls = det.get_objects_typed(hailo.HAILO_CLASSIFICATION)
                for ec in existing_cls:
                    if ec.get_classification_type() == "found_lp":
                        det.remove_object(ec)
                plate_cls = hailo.HailoClassification(type="found_lp", label=normalized_label, confidence=float(confidence))
                det.add_object(plate_cls)
                
                # Optionally change the detection label to indicate it has a valid plate
                if _should_update_track_labels():
                    try:
                        current_label = det.get_label()
                        if current_label == "license_plate":
                            # Change label to indicate validated plate (optional)
                            # You can customize this label as needed
                            det.set_label(f"license_plate_validated")
                        elif current_label and "license_plate" in current_label.lower():
                            # Already has some plate-related label, update it
                            det.set_label(f"license_plate_validated")
                    except Exception:
                        # set_label might not be available in Python API, skip silently
                        lpr_dbg("callback: set_label not available for detection, skipping label update")
                        pass
                
                if tracker and tracker_name and track_id is not None:
                    try:
                        tracker.remove_classifications_from_track(tracker_name, track_id, "found_lp")
                        tracker.add_object_to_track(tracker_name, track_id, plate_cls)
                    except Exception:
                        pass
            except Exception:
                pass

        # Replace the "yes/100%" overlay with the actual plate text when vehicles exist.
        if track_id is not None and track_id in vehicles_by_track:
            vdet = vehicles_by_track[track_id]
            try:
                existing_cls = vdet.get_objects_typed(hailo.HAILO_CLASSIFICATION)
                for ec in existing_cls:
                    if ec.get_classification_type() == "found_lp":
                        vdet.remove_object(ec)
                vehicle_cls = hailo.HailoClassification(type="found_lp", label=normalized_label, confidence=float(confidence))
                vdet.add_object(vehicle_cls)
                
                # Always print what OCR is added to vehicle classification
                print(
                    f"[LPR_PYTHON] {frame_tag}Added classification to vehicle: type='found_lp' OCR='{normalized_label}' "
                    f"confidence={confidence:.2f} track_id={track_id}"
                )
                
                # Optionally change the vehicle detection label to indicate it has a validated plate
                if _should_update_track_labels():
                    try:
                        current_label = vdet.get_label()
                        if current_label == "vehicle":
                            # Change label to indicate vehicle with validated plate
                            # You can customize this label as needed (e.g., "vehicle_with_plate", "vehicle_lpr")
                            vdet.set_label("vehicle_with_plate")
                    except Exception:
                        # set_label might not be available in Python API, skip silently
                        lpr_dbg("callback: set_label not available for vehicle detection, skipping label update")
                        pass
            except Exception:
                pass

            if not getattr(user_data, "disable_found_lp_gate", False):
                existing_types = {
                    c.get_classification_type() for c in vdet.get_objects_typed(hailo.HAILO_CLASSIFICATION)
                }
                if "text_region" not in existing_types:
                    gate_cls = hailo.HailoClassification(type="text_region", label="", confidence=1.0)
                    vdet.add_object(gate_cls)
                    if tracker and tracker_name and track_id is not None:
                        try:
                            tracker.remove_classifications_from_track(tracker_name, track_id, "text_region")
                            tracker.add_object_to_track(tracker_name, track_id, gate_cls)
                        except Exception:
                            pass
        
        # Save to file
        try:
            user_data.write_ocr_text(normalized_label, confidence, track_id)
        except Exception as e:
            hailo_logger.debug(f"Failed writing OCR text: {e}")

    lpr_dbg("callback: accepted_ocr=%d", accepted_ocr)

    # If HAILO_LPR_HIDE_LP is set, remove license plate detections from ROI
    # so they won't be drawn by hailooverlay (only vehicles will be visible)
    if _should_hide_lp_overlay():
        # Remove top-level license plate detections
        for det in list(roi.get_objects_typed(hailo.HAILO_DETECTION)):
            if (det.get_label() or "") == "license_plate":
                roi.remove_object(det)

        # Remove nested license plate detections from vehicles
        for det in roi.get_objects_typed(hailo.HAILO_DETECTION):
            if (det.get_label() or "") == "vehicle":
                for nested in list(det.get_objects_typed(hailo.HAILO_DETECTION)):
                    if (nested.get_label() or "") == "license_plate":
                        det.remove_object(nested)

    return


def print_ocr_summary(user_data):
    """Print a summary of all OCR results at the end of the run."""
    if os.getenv("HAILO_LPR_SILENT", "0").lower() not in ("", "0", "false", "no"):
        return
    if not hasattr(user_data, 'ocr_results') or not user_data.ocr_results:
        print("\n" + "=" * 60)
        print("LPR Summary: No license plates detected")
        print("=" * 60)
        return
    
    print("\n" + "=" * 60)
    print("LPR Summary - Detected License Plates")
    print("=" * 60)
    
    total_detections = 0
    unique_plates = set()
    
    for track_id, results in user_data.ocr_results.items():
        if results:
            # Get the most confident result for this track
            best_result = max(results, key=lambda x: x[1] if x[1] else 0)
            plate_text, confidence, frame_num, elapsed = best_result
            unique_plates.add(plate_text)
            total_detections += len(results)
            print(f"  Track {track_id:4d}: {plate_text:<15s} (Best conf: {confidence:.2f}, First seen: frame {frame_num})")
    
    print("-" * 60)
    print(f"Total unique tracks with LP: {len(user_data.ocr_results)}")
    print(f"Total unique plate texts:    {len(unique_plates)}")
    print(f"Total OCR detections:        {total_detections}")
    print(f"Results saved to:            {user_data.output_file}")
    print("=" * 60)
    
    # Also append summary to the output file
    if user_data.save_ocr_results:
        with open(user_data.output_file, "a", encoding="utf-8") as f:
            f.write("\n" + "-" * 80 + "\n")
            f.write(f"# Summary - {datetime.now().isoformat()}\n")
            f.write(f"# Unique tracks with LP: {len(user_data.ocr_results)}\n")
            f.write(f"# Unique plate texts: {len(unique_plates)}\n")
            f.write(f"# Total OCR detections: {total_detections}\n")
            if unique_plates:
                f.write(f"# Unique plates: {', '.join(sorted(unique_plates))}\n")


def main():
    hailo_logger.info("Starting Hailo LPR App...")
    user_data = None
    try:
        lpr_db, lpr_db_json = init_lpr_db()
        user_data = user_app_callback_class(lpr_db=lpr_db, lpr_db_json=lpr_db_json)
        app = GStreamerLPRApp(app_callback, user_data)
        app.run()
    except KeyboardInterrupt:
        hailo_logger.info("Interrupted by user")
        print("\nInterrupted by user")
    except Exception as e:
        hailo_logger.error(f"Error in main: {e}", exc_info=True)
        print(f"Error: {e}", file=sys.stderr)
        raise
    finally:
        # Print summary on exit
        if user_data is not None:
            print_ocr_summary(user_data)


if __name__ == "__main__":
    main()
