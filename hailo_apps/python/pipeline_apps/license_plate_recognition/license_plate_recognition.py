# Standard library imports
import os
import sys
import re

# Third-party imports
import gi

gi.require_version("Gst", "1.0")

import hailo

# Local application-specific imports
from hailo_apps.python.pipeline_apps.license_plate_recognition.license_plate_recognition_pipeline import (
    GStreamerLPRApp,
)
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


class user_app_callback_class(app_callback_class):
    def __init__(self):
        super().__init__()

        # Per-track state
        self.found_lp_tracks: set[int] = set()
        self.plate_texts: dict[int, tuple[str, float]] = {}  # track_id -> (plate_text, ocr_confidence)
        self.vehicle_tracks: dict[int, dict] = {}

    def reset_state(self) -> None:
        """Reset per-run state when the pipeline restarts (e.g., video loops)."""
        self.found_lp_tracks.clear()
        self.plate_texts.clear()
        self.vehicle_tracks.clear()


def _iter_classifications(roi):
    """Iterate through all classifications in the ROI hierarchy.
    
    The LPR hierarchy is:
      ROI → Vehicle Detection → License Plate Detection → Classification (OCR result)
    
    This function yields (parent_detection, classification, vehicle_track_id) tuples at all levels.
    vehicle_track_id is the track ID of the parent vehicle (if available).
    """
    if roi is None:
        return

    # Top-level detections (vehicles)
    detections = roi.get_objects_typed(hailo.HAILO_DETECTION)
    for det in detections:
        # Get vehicle track ID
        vehicle_track_id = None
        if (det.get_label() or "") == "vehicle":
            uid = det.get_objects_typed(hailo.HAILO_UNIQUE_ID)
            if uid:
                vehicle_track_id = uid[0].get_id()
        
        # Classifications directly on vehicle detection
        for cls in det.get_objects_typed(hailo.HAILO_CLASSIFICATION):
            yield det, cls, vehicle_track_id
        
        # Nested detections (license plates inside vehicles)
        nested_detections = det.get_objects_typed(hailo.HAILO_DETECTION)
        for nested_det in nested_detections:
            # Classifications on nested detection (OCR results on license plates)
            for cls in nested_det.get_objects_typed(hailo.HAILO_CLASSIFICATION):
                # Pass the parent vehicle's track ID
                yield nested_det, cls, vehicle_track_id

    # Classifications directly on ROI
    for cls in roi.get_objects_typed(hailo.HAILO_CLASSIFICATION):
        yield None, cls, None


def _parse_bool_env(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "y", "on")


def _no_skip_enabled() -> bool:
    return _parse_bool_env("HAILO_LPR_NO_SKIP", False)


def _parse_int_env(name: str, default: int) -> int:
    val = os.getenv(name)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        return default


def _normalize_ocr_label(raw_label: str) -> str:
    # Always keep alphanumeric, uppercase
    return re.sub(r"[^0-9A-Za-z]", "", raw_label).upper()


# Words to ignore (false positives from signs)
IGNORED_TEXTS = {"TAXI", "BUS", "STOP", "EXIT"}


def _is_plate_valid(normalized_label: str, min_len: int, max_len: int) -> bool:
    """Check if a license plate text is valid.

    Args:
        normalized_label: The normalized plate text
        min_len: Minimum acceptable length
        max_len: Maximum acceptable length

    Returns:
        True if the plate is considered valid, False otherwise
    """
    # Filter common false positives
    if normalized_label in IGNORED_TEXTS:
        return False

    # Basic length check
    if not (min_len <= len(normalized_label) <= max_len):
        return False

    return True


def app_callback(element, buffer, user_data):
    frame_count = user_data.get_count() if hasattr(user_data, "get_count") else "n/a"
    lpr_dbg("callback: ENTER frame=%s", getattr(user_data, "get_count", lambda: "n/a")())
    if buffer is None:
        lpr_dbg("callback: buffer is None => EXIT")
        return

    roi = hailo.get_roi_from_buffer(buffer)
    if roi is None:
        lpr_dbg("callback: roi is None => EXIT")
        return

    # Tracks that already have an accepted LP — skip re-processing
    in_memory_found = getattr(user_data, "found_lp_tracks", set())
    skip_tracks_enabled = not _no_skip_enabled()
    if skip_tracks_enabled:
        skip_lp_tracks = set(in_memory_found)
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

    # DEBUG: Print frame summary (opt-in via HAILO_LPR_DEBUG)
    if lpr_debug_enabled():
        vehicle_tracks = [t for t, _ in vehicles]
        print(
            f"[DEBUG] Frame {frame_count}: vehicles={len(vehicles)} (tracks={vehicle_tracks}), "
            f"plates={len(plates)}, nested_plates={sum(len(v) for v in nested_plates_by_track.values())}"
        )

        # DEBUG: Show all classifications found (including non-OCR)
        for det, cls, veh_track in all_classifications:
            cls_type = cls.get_classification_type() if hasattr(cls, 'get_classification_type') else ""
            label = cls.get_label() or ""
            conf = cls.get_confidence() if hasattr(cls, 'get_confidence') else 0.0
            det_label = det.get_label() if det else "no_det"
            print(
                f"[DEBUG]   Classification: type='{cls_type}' label='{label}' "
                f"conf={conf:.3f} det='{det_label}' vehicle_track={veh_track}"
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

    # Process OCR results
    min_len = max(1, _parse_int_env("HAILO_LPR_MIN_LEN", 4))  # Default min 4 chars
    max_len = max(min_len, _parse_int_env("HAILO_LPR_MAX_LEN", 10))  # Default max 10 chars

    accepted_ocr = 0
    best_by_track: dict[int | None, dict] = {}
    for det, cls, veh_track in all_classifications:
        cls_type = cls.get_classification_type() if hasattr(cls, 'get_classification_type') else ""
        label = cls.get_label()
        if not label:
            continue
        
        # Only process OCR results (text_region classification type)
        if cls_type != "text_region":
            continue

        raw_label = label.strip()
        normalized_label = _normalize_ocr_label(raw_label)
        confidence = cls.get_confidence()
        track_id = None
        plate_det_conf = None
        if det is not None:
            uid = det.get_objects_typed(hailo.HAILO_UNIQUE_ID)
            if uid:
                track_id = uid[0].get_id()
            # Get license plate detection confidence
            plate_det_conf = det.get_confidence() if hasattr(det, 'get_confidence') else None
        if track_id is not None and track_id in skip_lp_tracks:
            continue
        # Length check - silently skip if too short/long
        if not (min_len <= len(normalized_label) <= max_len):
            continue
        existing = best_by_track.get(track_id)
        if existing is None or len(normalized_label) > len(existing["label"]):
            best_by_track[track_id] = {
                "label": normalized_label,
                "confidence": float(confidence),
                "track_id": track_id,
                "det": det,
                "plate_det_conf": plate_det_conf,
            }
            lpr_dbg(
                "callback: candidate track=%s raw='%s' norm='%s' conf=%.3f len=%d",
                track_id if track_id is not None else "None",
                raw_label,
                normalized_label,
                float(confidence),
                len(normalized_label),
            )

    for candidate in best_by_track.values():
        normalized_label = candidate["label"]
        confidence = candidate["confidence"]
        track_id = candidate["track_id"]
        det = candidate["det"]
        plate_det_conf = candidate.get("plate_det_conf")

        if track_id is not None and track_id in skip_lp_tracks:
            continue

        # Validate the plate before processing
        is_valid = _is_plate_valid(
            normalized_label=normalized_label,
            min_len=min_len,
            max_len=max_len,
        )
        
        if not is_valid:
            continue

        # Clean output: LP Det Conf | Plate | OCR Conf
        plate_det_pct = f"{plate_det_conf * 100:.0f}%" if plate_det_conf is not None else "N/A"
        ocr_pct = f"{confidence * 100:.0f}%"
        
        print(
            f"LP {track_id:>2} | Det Conf.: {plate_det_pct} | OCR Conf.: {ocr_pct} | Plate: '{normalized_label}'"
        )
        lpr_dbg(
            "callback: accepted track=%s plate='%s' conf=%.3f",
            track_id if track_id is not None else "None",
            normalized_label,
            float(confidence),
        )
        accepted_ocr += 1

        if track_id is not None:
            user_data.found_lp_tracks.add(track_id)
            user_data.plate_texts[track_id] = (normalized_label, confidence)
            skip_lp_tracks.add(track_id)
            if track_id in user_data.vehicle_tracks:
                user_data.vehicle_tracks[track_id]["found_lp"] = True

    lpr_dbg("callback: accepted_ocr=%d", accepted_ocr)

    # ── Overlay: show only recognised plates as "PLATE_TEXT  XX%" ──
    # Remove every detection from the ROI, then add back a single clean
    # detection per recognised plate (plate text as label, OCR confidence).
    plate_by_track = getattr(user_data, "plate_texts", {})

    for det in list(roi.get_objects_typed(hailo.HAILO_DETECTION)):
        uid = det.get_objects_typed(hailo.HAILO_UNIQUE_ID)
        tid = uid[0].get_id() if uid else None

        # Remove the original detection no matter what
        roi.remove_object(det)

        # For recognised plates, add a clean replacement
        if tid is not None and tid in plate_by_track:
            plate_text, ocr_conf = plate_by_track[tid]
            new_det = hailo.HailoDetection(det.get_bbox(), f"LP {tid}: {plate_text}", ocr_conf)
            roi.add_object(new_det)

    return


def main():
    hailo_logger.info("Starting Hailo LPR App...")
    user_data = None
    try:
        user_data = user_app_callback_class()
        app = GStreamerLPRApp(app_callback, user_data)
        app.run()
    except KeyboardInterrupt:
        hailo_logger.info("Interrupted by user")
        print("\nInterrupted by user")
    except Exception as e:
        hailo_logger.error(f"Error in main: {e}", exc_info=True)
        print(f"Error: {e}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()