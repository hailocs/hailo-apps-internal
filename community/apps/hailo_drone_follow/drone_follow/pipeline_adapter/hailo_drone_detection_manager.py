"""Hailo tiling pipeline adapter — all Hailo/GStreamer imports are confined here.

Translates Hailo detection objects into the pure Detection domain type.
No other module needs to import hailo or gi.repository.
"""

import argparse
import json
import logging
import os
import subprocess
import threading
import time
from datetime import datetime
from typing import Optional

import hailo
import numpy as np

from drone_follow.follow_api.types import Detection
from drone_follow.perf_tracker import PerfTracker

from .byte_tracker import iou_batch
from .tracker import MetricsTracker
from .tracker_factory import create_tracker
from .reid_manager import get_frame_bgr

LOGGER = logging.getLogger(__name__)

_EMPTY_DET_ARRAY = np.empty((0, 5), dtype=np.float32)


_gst_module = None


def _get_gst():
    """Import and cache GStreamer bindings (deferred to avoid import at module level)."""
    global _gst_module
    if _gst_module is None:
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
        _gst_module = Gst
    return _gst_module


# ---------------------------------------------------------------------------
# Callback helpers
# ---------------------------------------------------------------------------

def _build_det_info(person, track_id=None):
    """Build a UI detection dict from a Hailo detection object."""
    pbbox = person.get_bbox()
    det_info = {
        "label": "person",
        "confidence": round(person.get_confidence(), 3),
        "bbox": {
            "x": round(pbbox.xmin(), 4),
            "y": round(pbbox.ymin(), 4),
            "w": round(pbbox.width(), 4),
            "h": round(pbbox.height(), 4),
        },
    }
    if track_id is not None:
        det_info["id"] = track_id
    return det_info


def _update_ui(ui_state, persons, person_to_id, following_id, paused=False):
    """Push detection metadata to the web UI if enabled."""
    if ui_state is None:
        return
    all_dets = [_build_det_info(p, person_to_id.get(id(p))) for p in persons]
    ui_state.update_detections(all_dets, following_id, paused=paused)


def _run_tracker(tracker, persons):
    """Run tracker and return (available_ids, person_by_id, person_to_id).

    person_by_id:  {track_id -> person detection}
    person_to_id:  {id(person) -> track_id}  (reverse lookup)
    """
    available_ids = set()
    person_by_id = {}

    SCALE = 1000.0
    det_array = np.empty((len(persons), 5), dtype=np.float32)
    for i, person in enumerate(persons):
        bbox = person.get_bbox()
        det_array[i, 0] = bbox.xmin() * SCALE
        det_array[i, 1] = bbox.ymin() * SCALE
        det_array[i, 2] = (bbox.xmin() + bbox.width()) * SCALE
        det_array[i, 3] = (bbox.ymin() + bbox.height()) * SCALE
        det_array[i, 4] = person.get_confidence()

    all_tracks = tracker.update(det_array)

    for t in all_tracks:
        if t.is_activated and 0 <= t.input_index < len(persons):
            available_ids.add(t.track_id)
            person_by_id[t.track_id] = persons[t.input_index]
        elif t.is_activated:
            available_ids.add(t.track_id)

    person_to_id = {id(p): tid for tid, p in person_by_id.items()}
    return available_ids, person_by_id, person_to_id


def _find_biggest_person(person_by_id):
    """Return (track_id, person) for the person with the largest bbox area, or (None, None)."""
    best_id, best_person, best_area = None, None, -1.0
    for tid, person in person_by_id.items():
        bbox = person.get_bbox()
        area = bbox.width() * bbox.height()
        if area > best_area:
            best_id, best_person, best_area = tid, person, area
    return best_id, best_person


_SOT_IOU_THRESH = 0.3


def _run_sot(persons, last_bbox):
    """Lightweight single-object tracking: IOU match against last known bbox.

    Returns (matched_person, new_bbox_scaled) or (None, None) if lost.
    last_bbox is [x1, y1, x2, y2] in SCALE (1000) coordinates.
    """
    SCALE = 1000.0
    n = len(persons)
    det_bboxes = np.empty((n, 4), dtype=np.float32)
    for i, person in enumerate(persons):
        bbox = person.get_bbox()
        det_bboxes[i, 0] = bbox.xmin() * SCALE
        det_bboxes[i, 1] = bbox.ymin() * SCALE
        det_bboxes[i, 2] = (bbox.xmin() + bbox.width()) * SCALE
        det_bboxes[i, 3] = (bbox.ymin() + bbox.height()) * SCALE

    ious = iou_batch(last_bbox.reshape(1, 4), det_bboxes)  # shape (1, N)
    if ious.size == 0:
        return None, None

    best_idx = np.argmax(ious[0])
    if ious[0, best_idx] < _SOT_IOU_THRESH:
        return None, None

    return persons[best_idx], det_bboxes[best_idx]


def _dispatch_sot_or_mot(
    persons,
    target_id,
    sot_enabled,
    sot_active,
    sot_last_bbox,
    sot_target_id,
    run_tracker,
    run_sot,
    attach_track_id=None,
):
    """Always run MOT; use SOT only as a fallback for the locked target.

    Returns (available_ids, person_by_id, person_to_id, sot_recovered).

    The MOT tracker runs unconditionally so every visible person gets a stable
    track ID surfaced to the UI / OpenHD. SOT only kicks in when MOT lost the
    locked target — a quiet safety net that re-attaches `target_id` to whichever
    detection still IOU-matches the last bbox.

    Parameters
    ----------
    persons : list of HailoDetection-like objects (each exposes get_bbox())
    target_id : int or None — the operator-locked / auto-selected target
    sot_enabled, sot_active, sot_last_bbox, sot_target_id : SOT state from user_data
    run_tracker : callable(persons) -> (available_ids, person_by_id, person_to_id)
        Wraps `_run_tracker(user_data.tracker, persons)` so this helper stays pure.
    run_sot : callable(persons, last_bbox) -> (matched, new_bbox)
        Wraps `_run_sot` for the same reason.
    attach_track_id : callable(person, track_id) -> None or None
        Used to attach a HailoUniqueID(track_id, TRACKING_ID) to a recovered
        person on SOT-fallback frames. None disables attachment (testing).

    sot_recovered : True iff MOT lost the target this frame *and* SOT recovered
        it. The caller can use that to keep the SOT bookkeeping alive even
        though MOT is now in charge again (refreshed for next frame).
    """
    available_ids, person_by_id, person_to_id = run_tracker(persons)

    sot_recovered = False
    if (
        sot_enabled
        and target_id is not None
        and target_id not in person_by_id
        and sot_active
        and sot_last_bbox is not None
        and sot_target_id == target_id
    ):
        # MOT lost the locked target this frame — try SOT IOU fallback.
        matched, _new_bbox = run_sot(persons, sot_last_bbox)
        if matched is not None:
            if attach_track_id is not None:
                attach_track_id(matched, target_id)
            person_by_id[target_id] = matched
            person_to_id[id(matched)] = target_id
            available_ids.add(target_id)
            sot_recovered = True

    return available_ids, person_by_id, person_to_id, sot_recovered


# Clamp matches the UI Target Size slider min/max
_TGT_BH_MIN = 0.10
_TGT_BH_MAX = 0.25


def capture_bbox_setpoint_from_height(config, height: float, source: str = "lock") -> Optional[float]:
    """At lock time, snap controller_config.target_bbox_height to the target's current bbox.

    Centralised so both the AUTO acquisition path (detection manager) and the
    operator-click path (follow_server) capture distance the same way.

    Returns the clamped value actually written, or None if the config is missing.
    """
    if config is None:
        return None
    h = max(_TGT_BH_MIN, min(_TGT_BH_MAX, float(height)))
    config.target_bbox_height = h
    LOGGER.info("[LOCK %s] target_bbox_height set to %.3f from current bbox", source, h)
    return h


def _capture_bbox_setpoint(config, person):
    """Convenience wrapper for the hailo-bound caller: pulls height off the bbox."""
    if person is None:
        return
    capture_bbox_setpoint_from_height(config, person.get_bbox().height(), source="AUTO")


# ---------------------------------------------------------------------------
# Test log helpers
# ---------------------------------------------------------------------------

def _log_detections(user_data, persons, person_to_id):
    if user_data._frame_log_data is None:
        return
    user_data._frame_log_data["detections"] = [
        {
            "id": person_to_id.get(id(p)),
            "bbox": [
                round(p.get_bbox().xmin(), 4),
                round(p.get_bbox().ymin(), 4),
                round(p.get_bbox().width(), 4),
                round(p.get_bbox().height(), 4),
            ],
            "score": round(p.get_confidence(), 3),
        }
        for p in persons
    ]


def _log_mode(user_data, mode, followed_id):
    if user_data._frame_log_data is None:
        return
    user_data._frame_log_data["mode"] = mode
    user_data._frame_log_data["followed_id"] = followed_id


# ---------------------------------------------------------------------------
# Main app callback
# ---------------------------------------------------------------------------

def app_callback(element, buffer, user_data):
    """Tiling pipeline callback: follow operator-selected person, update shared state.

    Tracker runs synchronously in the callback:
    1. Convert detections to Nx5 array, run tracker.update() synchronously
    2. Each returned track has input_index pointing to the matched detection
    3. Build person_by_id directly -- no cross-frame IoU re-matching needed
    """
    _perf_t0 = user_data.perf.frame_start()
    if user_data.test_log_file is not None:
        user_data.frame_index += 1
        user_data._frame_log_data = {
            "t": time.time(),
            "frame": user_data.frame_index,
            "mode": "",
            "followed_id": None,
            "detections": [],
        }
    else:
        user_data._frame_log_data = None
    try:
        _app_callback_inner(element, buffer, user_data)
    finally:
        user_data.perf.frame_end(_perf_t0, user_data.ui_state)
        if user_data.test_log_file is not None and user_data._frame_log_data is not None:
            try:
                user_data.test_log_file.write(
                    json.dumps(user_data._frame_log_data) + "\n")
            except (ValueError, OSError):
                pass


def _app_callback_inner(element, buffer, user_data):
    roi = hailo.get_roi_from_buffer(buffer)
    detections = roi.get_objects_typed(hailo.HAILO_DETECTION)
    persons = [d for d in detections if d.get_label() == "person"]

    target_state = user_data.target_state
    ui_state = user_data.ui_state
    config = user_data.controller_config
    auto_select = bool(getattr(config, "auto_select", True)) if config is not None else True

    if not persons:
        user_data.tracker.update(_EMPTY_DET_ARRAY)
        user_data.sot_active = False
        user_data.sot_last_bbox = None
        user_data.shared_state.update(None, available_ids=set())
        if target_state is not None and target_state.get_target() is not None:
            reid_mgr = user_data.reid_manager
            if reid_mgr is not None and reid_mgr.has_gallery:
                # ReID gallery exists — check timeout
                last_seen = target_state.get_last_seen()
                if last_seen is not None and time.monotonic() - last_seen > user_data.reid_search_timeout:
                    LOGGER.info("[REID TIMEOUT] Search exceeded %.0fs — returning to %s",
                                user_data.reid_search_timeout,
                                "auto mode" if auto_select else "IDLE (auto-select off)")
                    target_state.enter_auto_mode()
                    reid_mgr.clear()
                    if not auto_select:
                        target_state.set_paused(True)
                else:
                    LOGGER.debug("[REID SEARCH] No persons in frame — holding target ID %s, waiting",
                                 target_state.get_target())
            else:
                target_state.enter_auto_mode()
                if not auto_select:
                    target_state.set_paused(True)
                    LOGGER.info("[IDLE] Target lost (no persons) — auto-select off, holding position")
                else:
                    LOGGER.info("[AUTO] Target lost (no persons, no ReID gallery) — returning to auto mode")
        _paused = target_state.is_paused() if target_state else False
        _update_ui(ui_state, [], {}, None, paused=_paused)
        if target_state is None or target_state.get_target() is None:
            LOGGER.debug("[SEARCH MODE] No person detected in frame")
        _log_mode(user_data, "no-persons",
                  target_state.get_target() if target_state else None)
        return

    # --- SOT/MOT dispatch ---
    # MOT runs every frame so the operator sees every visible track ID and can
    # switch lock targets at any time. SOT is a quiet safety net: only consulted
    # when MOT loses the currently-locked target this frame.
    target_id = target_state.get_target() if target_state is not None else None
    reid_manager = user_data.reid_manager

    available_ids, person_by_id, person_to_id, sot_recovered = _dispatch_sot_or_mot(
        persons,
        target_id=target_id,
        sot_enabled=user_data.sot_enabled,
        sot_active=user_data.sot_active,
        sot_last_bbox=user_data.sot_last_bbox,
        sot_target_id=user_data.sot_target_id,
        run_tracker=lambda ps: _run_tracker(user_data.tracker, ps),
        run_sot=_run_sot,
        attach_track_id=lambda person, tid: person.add_object(
            hailo.HailoUniqueID(tid, hailo.TRACKING_ID)),
    )

    # Attach HailoUniqueID to every MOT-tracked person so downstream consumers
    # (overlay, OpenHD bridge) can read the track ID off the detection object.
    for person in persons:
        tid = person_to_id.get(id(person))
        if tid is not None and (not sot_recovered or tid != target_id):
            # SOT-recovered person already had its ID attached by the helper.
            person.add_object(hailo.HailoUniqueID(tid, hailo.TRACKING_ID))

    if sot_recovered:
        LOGGER.debug("[SOT] MOT lost target ID %s — SOT IOU fallback recovered it",
                     target_id)

    _log_detections(user_data, persons, person_to_id)

    # --- Target selection ---

    best = None
    follow_mode = ""
    if target_id is not None:
        best = person_by_id.get(target_id)

        if best is not None:
            # Successfully tracking target
            target_state.update_last_seen()
            follow_mode = f"ID {target_id}"

            # ReID: build/update gallery while following (auto or locked)
            if reid_manager is not None:
                reid_manager.on_target_selected(target_id)
                if reid_manager.should_update():
                    frame_bgr = get_frame_bgr(buffer, user_data.video_width, user_data.video_height)
                    if frame_bgr is not None:
                        reid_manager.update_gallery(
                            frame_bgr, best.get_bbox(),
                            user_data.video_width, user_data.video_height)

            # Activate SOT for next frame (if SOT mode enabled)
            if user_data.sot_enabled:
                SCALE = 1000.0
                tbbox = best.get_bbox()
                user_data.sot_last_bbox = np.array([
                    tbbox.xmin() * SCALE,
                    tbbox.ymin() * SCALE,
                    (tbbox.xmin() + tbbox.width()) * SCALE,
                    (tbbox.ymin() + tbbox.height()) * SCALE,
                ], dtype=np.float32)
                user_data.sot_target_id = target_id
                if not user_data.sot_active:
                    user_data.sot_active = True
                    LOGGER.info("[MOT→SOT] Entering SOT mode for target ID %d", target_id)
        else:
            # Target lost by tracker — reset SOT state and try ReID re-identification
            user_data.sot_active = False
            user_data.sot_last_bbox = None

            if reid_manager is not None and reid_manager.has_gallery and person_by_id:
                # ReID gallery exists — try re-identification
                last_seen = target_state.get_last_seen()
                if last_seen is not None and time.monotonic() - last_seen > user_data.reid_search_timeout:
                    LOGGER.info("[REID TIMEOUT] Search exceeded %.0fs — returning to %s",
                                user_data.reid_search_timeout,
                                "auto mode" if auto_select else "IDLE (auto-select off)")
                    target_state.enter_auto_mode()
                    reid_manager.clear()
                    if not auto_select:
                        target_state.set_paused(True)
                    # Fall through to auto-select below (gated on auto_select)
                else:
                    frame_bgr = get_frame_bgr(buffer, user_data.video_width, user_data.video_height)
                    if frame_bgr is not None:
                        new_tid = reid_manager.try_reidentify(
                            frame_bgr, person_by_id,
                            user_data.video_width, user_data.video_height)
                        if new_tid is not None:
                            # Re-identified — resume following with the new track ID
                            target_state.set_target(new_tid)
                            reid_manager.on_reidentified(new_tid)
                            best = person_by_id[new_tid]
                            target_state.update_last_seen()
                            follow_mode = f"REID→ID {new_tid}"

                    if best is None:
                        # ReID didn't match — hold position and retry next frame
                        user_data.shared_state.update(None, available_ids=available_ids)
                        _update_ui(ui_state, persons, person_to_id, None)
                        _log_mode(user_data, "reid-search", target_id)
                        return
            else:
                # No ReID gallery — return to auto mode (or IDLE if auto-select disabled)
                target_state.enter_auto_mode()
                if not auto_select:
                    target_state.set_paused(True)
                    LOGGER.info("[IDLE] Target ID %s lost — auto-select off, holding position. Available: %s",
                                target_id, sorted(available_ids) if available_ids else "none")
                else:
                    LOGGER.info("[AUTO] Target ID %s lost — returning to auto mode. Available: %s",
                                target_id, sorted(available_ids) if available_ids else "none")

    # Re-read target_id after possible enter_auto_mode() calls above
    target_id = target_state.get_target() if target_state is not None else None

    if target_id is None and best is None:
        # No explicit target — reset SOT state and decide between idle, hold, or auto-select
        user_data.sot_active = False
        user_data.sot_last_bbox = None

        if target_state is not None and target_state.is_paused():
            # True IDLE — hold position
            user_data.shared_state.update(None, available_ids=available_ids)
            _update_ui(ui_state, persons, person_to_id, None, paused=True)
            LOGGER.debug("[IDLE] Paused. Available: %s",
                        sorted(available_ids) if available_ids else "none")
            _log_mode(user_data, "idle", None)
            return
        if not auto_select:
            # Auto-select disabled — pilot-led workflow. Hold position; wait for operator click.
            user_data.shared_state.update(None, available_ids=available_ids)
            _update_ui(ui_state, persons, person_to_id, None, paused=True)
            LOGGER.debug("[IDLE] auto-select off — waiting for operator selection. Available: %s",
                        sorted(available_ids) if available_ids else "none")
            _log_mode(user_data, "idle-no-auto", None)
            return
        # AUTO mode — select biggest person
        biggest_id, biggest_person = _find_biggest_person(person_by_id)
        if biggest_id is not None:
            target_state.set_target(biggest_id)
            # Match manual-selection state: AUTO acquisition is treated as an explicit lock
            # so OpenHD reports the real follow_id and the state machine is symmetric.
            target_state.set_explicit_lock(True)
            target_state.update_last_seen()
            # Capture current bbox as the distance setpoint so the drone holds the
            # current distance instead of converging to a fixed target_bbox_height.
            _capture_bbox_setpoint(config, biggest_person)
            best = biggest_person
            follow_mode = f"AUTO→ID {biggest_id}"
            LOGGER.debug("[AUTO] Selected biggest person ID %s. Available: %s",
                        biggest_id, sorted(available_ids) if available_ids else "none")
            # Activate SOT for next frame (if SOT mode enabled)
            if user_data.sot_enabled:
                SCALE = 1000.0
                tbbox = biggest_person.get_bbox()
                user_data.sot_last_bbox = np.array([
                    tbbox.xmin() * SCALE,
                    tbbox.ymin() * SCALE,
                    (tbbox.xmin() + tbbox.width()) * SCALE,
                    (tbbox.ymin() + tbbox.height()) * SCALE,
                ], dtype=np.float32)
                user_data.sot_target_id = biggest_id
                user_data.sot_active = True
                LOGGER.info("[MOT→SOT] Entering SOT mode for target ID %d", biggest_id)
        else:
            user_data.shared_state.update(None, available_ids=available_ids)
            _update_ui(ui_state, persons, person_to_id, None)
            _log_mode(user_data, "auto-no-tracked", None)
            return

    if best is None:
        # Safety fallback — should not normally reach here
        user_data.shared_state.update(None, available_ids=available_ids)
        _update_ui(ui_state, persons, person_to_id, None)
        _log_mode(user_data, "fallback", None)
        return

    bbox = best.get_bbox()
    cx = bbox.xmin() + bbox.width() / 2
    cy = bbox.ymin() + bbox.height() / 2
    user_data.shared_state.update(Detection(
        label="person",
        confidence=best.get_confidence(),
        center_x=cx,
        center_y=cy,
        bbox_height=bbox.height(),
        timestamp=time.monotonic(),
    ), available_ids=available_ids)

    # Use the original ID for the UI so the operator sees a stable ID
    # even after ReID re-identifies the person with a new tracker ID.
    ui_following_id = target_state.get_target() if target_state else None
    ui_person_to_id = person_to_id
    if reid_manager is not None and reid_manager.original_id is not None:
        orig = reid_manager.original_id
        cur = target_state.get_target() if target_state else None
        if orig != cur and cur is not None:
            # Remap the followed detection's ID to the original so the
            # green highlight and "Following: ID X" both use it.
            ui_following_id = orig
            ui_person_to_id = dict(person_to_id)
            ui_person_to_id[id(best)] = orig
    _update_ui(ui_state, persons, ui_person_to_id, ui_following_id)

    available_str = f"Available: {sorted(available_ids)}" if available_ids else ""
    LOGGER.debug("[FOLLOWING %s] conf=%.2f center=(%.2f,%.2f) h=%.2f %s",
                follow_mode, best.get_confidence(), cx, cy, bbox.height(), available_str)
    _log_mode(user_data, follow_mode,
              target_state.get_target() if target_state else None)


# ---------------------------------------------------------------------------
# OpenHD pipeline helpers (local to drone-follow; not in hailo-apps core)
# ---------------------------------------------------------------------------

def _openhd_stream_pipeline(port=5500, host="127.0.0.1", bitrate=3917, name="openhd_stream"):
    """H264 SW encode + RTP + UDP sink for OpenHD input.

    Uses x264enc with ultrafast/zerolatency settings.
    RPi5 has no hardware H264 encoder; Hailo inference runs on the accelerator,
    leaving CPU available for software encoding.
    """
    from hailo_apps.python.core.gstreamer.gstreamer_helper_pipelines import QUEUE
    encoder = (
        f"x264enc name={name}_encoder bitrate={bitrate} "
        f"speed-preset=ultrafast tune=zerolatency "
        f"sliced-threads=false threads=2 key-int-max=5"
    )
    return (
        f"{QUEUE(name=f'{name}_convert_q')} ! "
        f"videoconvert n-threads=2 ! video/x-raw,format=I420 ! "
        f"{QUEUE(name=f'{name}_enc_q')} ! "
        f"{encoder} ! "
        f"rtph264pay config-interval=1 pt=96 mtu=1440 ! "
        f"udpsink host={host} port={port} sync=false async=false"
    )


# Sideband metadata file written by OpenHD with current SHM resolution
_SHM_META_PATH = "/tmp/openhd_raw_video.meta"


def _read_shm_resolution():
    """Read current SHM resolution from OpenHD's sideband metadata file.

    Returns (width, height, fps) or None if the file doesn't exist or is invalid.
    OpenHD writes this file every time the camera pipeline (re)starts, so it
    always reflects the active capture resolution.
    """
    import json as _json
    try:
        with open(_SHM_META_PATH, "r") as f:
            meta = _json.loads(f.read())
        w = int(meta["width"])
        h = int(meta["height"])
        fps = int(meta.get("fps", 30))
        if w > 0 and h > 0 and fps > 0:
            return (w, h, fps)
    except (FileNotFoundError, KeyError, ValueError, _json.JSONDecodeError) as e:
        LOGGER.debug("Cannot read SHM metadata from %s: %s", _SHM_META_PATH, e)
    return None


def _shm_source_pipeline(video_source, video_width, video_height, frame_rate, name="source"):
    """Build a GStreamer source pipeline for OpenHD shared-memory NV12 passthrough.

    shmsrc buffers are read-only (mmap'd shared memory).  Force an immediate
    NV12->I420 conversion to create writable buffers (cheap UV deinterleave).

    The caps MUST match the resolution that OpenHD is actually writing into
    shared memory.  We read the sideband metadata file that OpenHD writes on
    every pipeline (re)start to auto-detect the correct resolution, falling
    back to the caller-supplied video_width/video_height if the file is absent.
    """
    from hailo_apps.python.core.gstreamer.gstreamer_helper_pipelines import QUEUE

    # Auto-detect resolution from OpenHD metadata
    shm_res = _read_shm_resolution()
    if shm_res is not None:
        shm_w, shm_h, shm_fps = shm_res
        if shm_w != video_width or shm_h != video_height or shm_fps != frame_rate:
            LOGGER.info(
                "SHM resolution from metadata (%dx%d@%d) differs from "
                "CLI/defaults (%dx%d@%d) — using metadata values",
                shm_w, shm_h, shm_fps, video_width, video_height, frame_rate,
            )
            video_width = shm_w
            video_height = shm_h
            frame_rate = shm_fps

    socket_path = str(video_source).split('://', 1)[1]

    source_element = (
        f'shmsrc socket-path={socket_path} do-timestamp=true is-live=true name={name} ! '
        f'video/x-raw,format=NV12,width={video_width},height={video_height},'
        f'framerate={frame_rate}/1,pixel-aspect-ratio=1/1 ! '
        f'videoconvert ! video/x-raw,format=I420 ! '
    )
    return (
        f"{source_element} "
        f"{QUEUE(name=f'{name}_scale_q')} ! "
        f"videoscale name={name}_videoscale n-threads=2 ! "
        f"{QUEUE(name=f'{name}_convert_q')} ! "
        f"videoconvert n-threads=3 name={name}_convert qos=false ! "
        f"video/x-raw, pixel-aspect-ratio=1/1, format=RGB, "
        f"width={video_width}, height={video_height}"
    )


def _udp_h264_source_pipeline(video_source, video_width, video_height, frame_rate, name="source"):
    """Build a GStreamer source pipeline for an RTP/H.264 UDP stream.

    The hailo-apps SOURCE_PIPELINE for `udp://` assumes raw MJPEG datagrams
    and pipes `udpsrc ! jpegdec`, which fails immediately on RTP-framed input
    (`Not a JPEG file: starts with 0x80 0x60` — `0x80` = RTP v2, `0x60` = pt 96).

    Gazebo's `gz-video-bridge` and most simulators send H.264 inside RTP, so
    we replace that branch here with `udpsrc ! rtph264depay ! avdec_h264`.
    """
    from hailo_apps.python.core.gstreamer.gstreamer_helper_pipelines import QUEUE

    port = str(video_source).rsplit(':', 1)[-1]
    caps = "application/x-rtp,media=video,encoding-name=H264,payload=96"

    source_element = (
        f'udpsrc port={port} caps="{caps}" name={name} ! '
        f'{QUEUE(name=f"{name}_queue_rtp")} ! '
        f'rtph264depay ! h264parse ! avdec_h264 name={name}_decodebin ! '
    )
    return (
        f"{source_element} "
        f"{QUEUE(name=f'{name}_scale_q')} ! "
        f"videoscale name={name}_videoscale n-threads=2 ! "
        f"{QUEUE(name=f'{name}_convert_q')} ! "
        f"videoconvert n-threads=3 name={name}_convert qos=false ! "
        f"video/x-raw, pixel-aspect-ratio=1/1, format=RGB, "
        f"width={video_width}, height={video_height}"
    )


# ---------------------------------------------------------------------------
# Pipeline app factory
# ---------------------------------------------------------------------------


def create_app(shared_state, target_state=None, eos_reached=None, ui_state=None, ui_fps=10,
               parser: Optional[argparse.ArgumentParser] = None,
               record_enabled=False, record_dir=None, reid_manager=None,
               reid_search_timeout: float = 20.0, controller_config=None,
               tracker_name=None, log_perf=False, sot_enabled=False):
    """Create the tiling pipeline app with drone-follow callback.

    Follows the hailo-app pattern: build parser, create user_data,
    instantiate GStreamerTilingApp. If eos_reached is a threading.Event,
    EOS will set it instead of calling GStreamer shutdown (so we can land first).

    Args:
        shared_state: SharedDetectionState for passing detections to control loop
        target_state: FollowTargetState for tracking-based target selection (optional)
        eos_reached: threading.Event to signal EOS instead of shutdown (optional)
        ui_state: SharedUIState for web UI (optional)
        ui_fps: MJPEG stream frame rate (default: 10)
        parser: Pre-built argparse parser with all domain args already registered.
                If None, a bare pipeline parser is created (for backward compat).
        record_dir: Directory for recording output files (optional)
        reid_manager: ReIDManager for appearance-based re-identification (optional)
        reid_search_timeout: Seconds to search via ReID before returning to auto mode (default: 20.0)
    """
    from hailo_apps.python.pipeline_apps.tiling.tiling_pipeline import (
        GStreamerTilingApp,
    )
    from hailo_apps.python.core.gstreamer.gstreamer_app import app_callback_class
    from hailo_apps.python.core.common.core import get_pipeline_parser
    from hailo_apps.python.core.gstreamer.gstreamer_helper_pipelines import (
        QUEUE,
        INFERENCE_PIPELINE, USER_CALLBACK_PIPELINE,
        TILE_CROPPER_PIPELINE, SOURCE_PIPELINE, OVERLAY_PIPELINE,
    )

    if parser is None:
        parser = get_pipeline_parser()

    class DroneFollowUserData(app_callback_class):
        def __init__(self, shared_state, target_state=None, ui_state=None,
                     tracker=None, reid_manager=None, reid_search_timeout=20.0,
                     controller_config=None, log_perf=False, sot_enabled=False):
            super().__init__()
            self.shared_state = shared_state
            self.target_state = target_state
            self.ui_state = ui_state
            self.tracker = tracker
            self.reid_manager = reid_manager
            self.reid_search_timeout = reid_search_timeout
            self.controller_config = controller_config
            self.perf = PerfTracker(
                log_perf=log_perf,
                tracker_metrics=tracker.metrics if tracker is not None else None,
            )
            # SOT state (only used when sot_enabled)
            self.sot_enabled = sot_enabled
            self.sot_active = False
            self.sot_last_bbox = None
            self.sot_target_id = None
            # Set after app creation so callback can extract frames for ReID
            self.video_width = 0
            self.video_height = 0
            # Per-frame JSONL test log (opened lazily via open_test_log())
            self.test_log_file = None
            self.frame_index = 0
            self._frame_log_data = None

        def open_test_log(self, path):
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            self.test_log_file = open(path, "w", buffering=1)
            LOGGER.info("[test-log] writing per-frame detection log to %s", path)

        def close_test_log(self):
            if self.test_log_file is not None:
                try:
                    self.test_log_file.close()
                except OSError:
                    pass
                self.test_log_file = None

    class DroneFollowTilingApp(GStreamerTilingApp):
        """Tiling app with EOS handling and optional MJPEG appsink for web UI."""
        def __init__(self, app_callback, user_data, parser=None, eos_reached=None,
                     ui_enabled=False, ui_state=None, ui_fps=30,
                     record_enabled=False, record_dir=None):
            self._eos_reached = eos_reached
            self._ui_enabled = ui_enabled
            self._record_enabled = record_enabled
            self._ui_state = ui_state
            self._ui_fps = ui_fps
            self._recording = False
            self._record_dir = record_dir or os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "..", "recordings")
            self._record_lock = threading.Lock()
            self._shm_rebuild_pending = False
            self._ffmpeg_proc = None

            # Pre-detect SHM resolution BEFORE super().__init__() so that
            # the tiling configuration (tile grid, overlap, batch size) is
            # computed with the correct frame dimensions.  Without this,
            # the base class configures tiling for the CLI default (e.g.
            # 1280x720) while the SHM source actually delivers 640x480,
            # causing a buffer size mismatch → Hailo DMA crash.
            if parser is not None:
                _pre_args, _ = parser.parse_known_args()
                _pre_input = getattr(_pre_args, 'input', None)
                if _pre_input and str(_pre_input).startswith('shm://'):
                    shm_res = _read_shm_resolution()
                    if shm_res is not None:
                        shm_w, shm_h, shm_fps = shm_res
                        LOGGER.info(
                            "Pre-init: SHM metadata says %dx%d@%d — "
                            "injecting into parser defaults",
                            shm_w, shm_h, shm_fps)
                        # Override the parser defaults so the base class
                        # sees the correct resolution during configure().
                        parser.set_defaults(
                            width=shm_w, height=shm_h,
                            frame_rate=shm_fps)

            super().__init__(app_callback, user_data, parser=parser)
            # After base class init, sync resolution from SHM metadata if in
            # SHM mode so that self.video_width/height are correct for any
            # future rebuild (watchdog, manual, etc.).
            if str(getattr(self, 'video_source', '')).startswith('shm://'):
                shm_res = _read_shm_resolution()
                if shm_res is not None:
                    self.video_width, self.video_height, self.frame_rate = shm_res
            # Connect appsink after pipeline is created by super().__init__
            if self._ui_enabled:
                self._connect_mjpeg_sink()

        def _connect_mjpeg_sink(self):
            """Connect the MJPEG appsink and record appsink new-sample signals."""
            self._Gst = _get_gst()
            mjpeg_sink = self.pipeline.get_by_name("mjpeg_sink")
            if mjpeg_sink:
                mjpeg_sink.connect("new-sample", self._on_mjpeg_sample)
            record_sink = self.pipeline.get_by_name("record_appsink")
            if record_sink:
                record_sink.connect("new-sample", self._on_record_sample)

        def _on_mjpeg_sample(self, appsink):
            """appsink callback: extract pre-encoded JPEG bytes."""
            Gst = self._Gst
            sample = appsink.emit("pull-sample")
            if sample:
                buf = sample.get_buffer()
                success, map_info = buf.map(Gst.MapFlags.READ)
                if success:
                    self._ui_state.update_frame(bytes(map_info.data))
                    buf.unmap(map_info)
            return Gst.FlowReturn.OK

        def _on_record_sample(self, appsink):
            """appsink callback: pipe raw RGB frames to ffmpeg subprocess."""
            Gst = self._Gst
            sample = appsink.emit("pull-sample")
            if sample and self._recording and self._ffmpeg_proc:
                buf = sample.get_buffer()
                ok, mapinfo = buf.map(Gst.MapFlags.READ)
                if ok:
                    try:
                        self._ffmpeg_proc.stdin.write(mapinfo.data)
                    except (BrokenPipeError, OSError):
                        pass
                    buf.unmap(mapinfo)
            return Gst.FlowReturn.OK

        def bus_call(self, bus, message, loop):
            """Override to rebuild pipeline on errors in SHM mode instead of shutting down."""
            import gi
            gi.require_version("Gst", "1.0")
            from gi.repository import Gst, GLib
            t = message.type
            if t == Gst.MessageType.ERROR:
                err, debug = message.parse_error()
                is_shm = str(getattr(self, 'video_source', '')).startswith('shm://')
                if is_shm and not self._shm_rebuild_pending:
                    self._shm_rebuild_pending = True
                    LOGGER.warning("SHM pipeline error (%s) — waiting for socket + rebuilding", err)
                    # Start polling for the SHM socket to reappear (OpenHD may
                    # be restarting its pipeline with a new resolution).
                    self._shm_poll_count = 0
                    GLib.timeout_add(500, self._shm_wait_for_socket)
                    return True
                elif is_shm:
                    # Additional error while rebuild already pending — ignore
                    return True
            return super().bus_call(bus, message, loop)

        def _shm_wait_for_socket(self):
            """Poll until the SHM socket and metadata file exist, then rebuild.

            OpenHD removes the socket and recreates it during pipeline restart.
            The metadata file is written first (during setup()), then the socket
            appears when shmsink enters PLAYING.  We poll every 500ms for up to
            30s (60 attempts) before giving up.
            """
            self._shm_poll_count += 1
            socket_path = str(self.video_source).split('://', 1)[1]
            meta_ok = _read_shm_resolution() is not None
            socket_ok = os.path.exists(socket_path)
            if socket_ok and meta_ok:
                LOGGER.info("SHM socket + metadata ready after %d polls — rebuilding pipeline",
                            self._shm_poll_count)
                self._shm_rebuild()
                return False  # stop polling
            if self._shm_poll_count >= 60:
                LOGGER.warning("SHM socket/metadata did not reappear after 30s — rebuilding anyway")
                self._shm_rebuild()
                return False
            if self._shm_poll_count % 10 == 0:
                LOGGER.debug("Waiting for SHM socket (exists=%s) + metadata (exists=%s) [poll %d]",
                             socket_ok, meta_ok, self._shm_poll_count)
            return True  # keep polling

        def _shm_rebuild(self):
            """Rebuild pipeline after SHM error (e.g. OpenHD resolution change).

            Re-reads the OpenHD metadata file so the new pipeline uses
            the correct caps for the (potentially changed) resolution.
            Performs a careful teardown to avoid kernel warnings from the
            Hailo PCIe driver's DMA buffer mapping (find_vma race on
            kernel 6.12+).
            """
            import gi
            gi.require_version("Gst", "1.0")
            from gi.repository import Gst

            self._shm_rebuild_pending = False
            # Update our video dimensions from the metadata file so the
            # rebuilt pipeline negotiates the correct SHM buffer layout.
            shm_res = _read_shm_resolution()
            if shm_res is not None:
                new_w, new_h, new_fps = shm_res
                if new_w != self.video_width or new_h != self.video_height:
                    LOGGER.info(
                        "SHM rebuild: resolution changed %dx%d -> %dx%d",
                        self.video_width, self.video_height, new_w, new_h,
                    )
                self.video_width = new_w
                self.video_height = new_h
                self.frame_rate = new_fps

            # Pre-teardown: transition the old pipeline through READY/NULL
            # explicitly so in-flight Hailo inference buffers are drained
            # before we create the new pipeline.
            if self.pipeline:
                LOGGER.debug("SHM rebuild: pipeline PLAYING -> NULL (drain Hailo buffers)")
                self.pipeline.set_state(Gst.State.NULL)
                self.pipeline.get_state(5 * Gst.SECOND)
                bus = self.pipeline.get_bus()
                if bus:
                    bus.remove_signal_watch()
                self.pipeline = None
                # The Hailo PCIe driver needs time to fully release DMA
                # buffer mappings before new ones can be allocated.
                # Without this delay, hailo_vdma_buffer_map triggers
                # kernel warnings (find_vma race) and a segfault.
                LOGGER.debug("SHM rebuild: waiting for Hailo DMA release")
                time.sleep(2.0)

            # Reset tracker to clear stale predictions from old resolution
            if hasattr(self, 'user_data') and hasattr(self.user_data, 'tracker'):
                self.user_data.tracker.reset()
                LOGGER.debug("SHM rebuild: tracker reset")

            # Now build a fresh pipeline from scratch (skip base class
            # teardown since we already did it above).
            self.watchdog_paused = True
            self.rebuild_count += 1
            try:
                LOGGER.debug("SHM rebuild: creating new pipeline")
                pipeline_string = self.get_pipeline_string()
                LOGGER.debug("SHM rebuild: pipeline string: %s", pipeline_string)

                self.pipeline = Gst.parse_launch(pipeline_string)

                bus = self.pipeline.get_bus()
                bus.add_signal_watch()
                bus.connect("message", self.bus_call, self.loop)

                self._connect_callback()
                self._on_pipeline_rebuilt()

                from hailo_apps.python.core.gstreamer.gstreamer_app import disable_qos
                disable_qos(self.pipeline)

                ret = self.pipeline.set_state(Gst.State.PLAYING)
                if ret == Gst.StateChangeReturn.FAILURE:
                    LOGGER.error("SHM rebuild: failed to start new pipeline")
                    self.loop.quit()
                    return False

                LOGGER.info("SHM rebuild: pipeline rebuilt and playing")
                self.watchdog_paused = False
            except Exception:
                LOGGER.error("SHM rebuild: exception", exc_info=True)
                self.loop.quit()
            return False

        def on_eos(self):
            if self._eos_reached is not None:
                self._eos_reached.set()
            else:
                super().on_eos()

        def _on_pipeline_rebuilt(self):
            super()._on_pipeline_rebuilt()
            if self._ui_enabled:
                self._connect_mjpeg_sink()

        # ---- Recording control ----

        @property
        def is_recording(self):
            return self._recording

        def _generate_record_path(self):
            os.makedirs(self._record_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            return os.path.join(self._record_dir, f"rec_{ts}.mp4")

        def start_recording(self, path=None):
            """Spawn ffmpeg subprocess and open valve. Returns the output file path."""
            with self._record_lock:
                if self._recording:
                    LOGGER.warning("[record] Already recording")
                    return None

                valve = self.pipeline.get_by_name("record_valve")
                if valve is None:
                    LOGGER.error("[record] record_valve not found in pipeline")
                    return None

                record_path = path or self._generate_record_path()
                width, height = self.video_width, self.video_height
                # --frame-rate has no parser default in hailo-apps, so
                # self.frame_rate can be None when the user doesn't pass -f.
                # ffmpeg requires an integer for -r, so fall back to the
                # documented 30 FPS default.
                fps = self.frame_rate or 30
                LOGGER.info("[record] Spawning ffmpeg: %sx%s @ %s fps → %s",
                            width, height, fps, record_path)

                self._ffmpeg_proc = subprocess.Popen([
                    "ffmpeg", "-y", "-nostdin",
                    "-f", "rawvideo", "-pix_fmt", "rgb24",
                    "-s", f"{width}x{height}", "-r", str(fps),
                    "-i", "pipe:0",
                    "-c:v", "libx264", "-preset", "ultrafast",
                    "-tune", "zerolatency", "-b:v", "5000k",
                    record_path,
                ], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

                valve.set_property("drop", False)
                self._recording = True
                self._current_record_path = record_path
                LOGGER.info("[record] Started recording to %s", record_path)
                return record_path

        def stop_recording(self):
            """Close valve and finalize ffmpeg in background. Non-blocking."""
            with self._record_lock:
                if not self._recording:
                    return None

                valve = self.pipeline.get_by_name("record_valve")
                if valve:
                    valve.set_property("drop", True)

                self._recording = False
                path = self._current_record_path
                proc = self._ffmpeg_proc
                self._ffmpeg_proc = None

                def _finalize():
                    try:
                        if proc and proc.stdin:
                            proc.stdin.close()
                        if proc:
                            proc.wait(timeout=5)
                    except Exception:
                        LOGGER.exception("[record] ffmpeg finalize error")
                    LOGGER.info("[record] Finalized: %s", path)

                threading.Thread(target=_finalize, daemon=True).start()

                LOGGER.info("[record] Stopped recording: %s", path)
                return path

        def cleanup_recording_branch(self):
            """Force recording branch elements to NULL so they don't block pipeline shutdown."""
            if not self._record_enabled:
                return
            Gst = _get_gst()
            with self._record_lock:
                for name in ("record_valve", "record_appsink"):
                    el = self.pipeline.get_by_name(name)
                    if el is not None:
                        el.set_state(Gst.State.NULL)

        def get_pipeline_string(self):
            openhd_stream = getattr(self.options_menu, 'openhd_stream', False)
            no_display = getattr(self.options_menu, 'no_display', False)
            is_shm = str(self.video_source).startswith('shm://')
            is_udp = str(self.video_source).startswith('udp://')

            # If no custom output needed, delegate to parent
            if not self._ui_enabled and not self._record_enabled and not openhd_stream and not is_shm and not is_udp and not no_display:
                return super().get_pipeline_string()

            # Build pipeline with tee: one branch for display, one for MJPEG appsink,
            # and (if recording is enabled) one raw-RGB appsink for ffmpeg subprocess.
            if is_shm:
                source_pipeline = _shm_source_pipeline(
                    self.video_source, self.video_width, self.video_height,
                    self.frame_rate,
                )
            elif is_udp:
                # Gazebo / sim video bridges send RTP-framed H.264 over UDP.
                # Upstream SOURCE_PIPELINE for udp:// only handles raw MJPEG.
                source_pipeline = _udp_h264_source_pipeline(
                    self.video_source, self.video_width, self.video_height,
                    self.frame_rate,
                )
            else:
                source_pipeline = SOURCE_PIPELINE(
                    video_source=self.video_source,
                    video_width=self.video_width,
                    video_height=self.video_height,
                    frame_rate=self.frame_rate,
                    sync=self.sync,
                )

            detection_pipeline = INFERENCE_PIPELINE(
                hef_path=self.hef_path,
                post_process_so=self.post_process_so,
                post_function_name=self.post_function,
                batch_size=self.batch_size,
                config_json=self.labels_json,
            )

            # Detect identity case: 1x1 tiles where frame matches model
            # input exactly.  The hailotilecropper has a DMA buffer-pool
            # negotiation bug in this passthrough path (no scaling needed)
            # that crashes the Hailo PCIe driver.  Skip the tile cropper
            # entirely — the inference pipeline processes the full frame
            # directly and produces identical results since coordinates
            # map 1:1 when frame_size == model_input_size.
            skip_tiling = (
                self.tiles_x == 1 and self.tiles_y == 1
                and not self.use_multi_scale
                and self.video_width == self.model_input_width
                and self.video_height == self.model_input_height
            )

            if skip_tiling:
                LOGGER.info(
                    "Bypassing tile cropper: 1x1 tiles with frame "
                    "(%dx%d) matching model input — direct inference",
                    self.video_width, self.video_height,
                )
            else:
                tiling_mode = 1 if self.use_multi_scale else 0
                scale_level = self.scale_level if self.use_multi_scale else 0
                tile_cropper_pipeline = TILE_CROPPER_PIPELINE(
                    detection_pipeline,
                    name='tile_cropper_wrapper',
                    internal_offset=True,
                    scale_level=scale_level,
                    tiling_mode=tiling_mode,
                    tiles_along_x_axis=self.tiles_x,
                    tiles_along_y_axis=self.tiles_y,
                    overlap_x_axis=self.overlap_x,
                    overlap_y_axis=self.overlap_y,
                    iou_threshold=self.iou_threshold,
                    border_threshold=self.border_threshold,
                )

            user_callback_pipeline = USER_CALLBACK_PIPELINE()

            # Primary output sink (WITHOUT overlay — overlay is shared upstream)
            if openhd_stream:
                openhd_port = getattr(self.options_menu, 'openhd_port', 5500)
                openhd_bitrate = getattr(self.options_menu, 'openhd_bitrate', 3917)
                primary_sink = _openhd_stream_pipeline(port=openhd_port, bitrate=openhd_bitrate)
            elif no_display:
                primary_sink = f"fakesink sync={self.sync}"
            else:
                # Inline display pipeline without overlay (DISPLAY_PIPELINE has overlay built in)
                primary_sink = (
                    f"{QUEUE(name='hailo_display_videoconvert_q')} ! "
                    f"videoconvert name=hailo_display_videoconvert n-threads=2 qos=false ! "
                    f"{QUEUE(name='hailo_display_q')} ! "
                    f"fpsdisplaysink name=hailo_display video-sink={self.video_sink} "
                    f"sync={self.sync} text-overlay={self.show_fps} signal-fps-measurements=true "
                )

            # MJPEG branch for web UI (no overlay — browser draws interactive SVG)
            mjpeg_branch = None
            if self._ui_enabled:
                mjpeg_branch = (
                    f"videoconvert n-threads=2 ! "
                    f"videorate max-rate={self._ui_fps} ! "
                    f"video/x-raw,framerate={self._ui_fps}/1 ! "
                    f"jpegenc quality=70 ! "
                    f"appsink name=mjpeg_sink sync=false drop=true emit-signals=true"
                )

            # Recording branch (no overlay — shares overlayed frames from t_post)
            record_branch = None
            if self._record_enabled:
                record_branch = (
                    f"valve name=record_valve drop=true ! "
                    f"videoconvert n-threads=2 ! video/x-raw,format=RGB ! "
                    f"appsink name=record_appsink emit-signals=true drop=true "
                    f"sync=false async=false max-buffers=1"
                )

            # Assemble output pipeline with two-stage tee:
            #   t_pre (before overlay) — MJPEG taps clean frames here
            #   t_post (after overlay) — primary + recording tap overlayed frames
            has_mjpeg = mjpeg_branch is not None
            has_record = record_branch is not None

            if has_mjpeg and has_record:
                # Two-stage tee: t_pre feeds MJPEG (clean) and overlay path;
                # t_post feeds primary + recording (overlayed)
                output_pipeline = (
                    f"tee name=t_pre "
                    f"t_pre. ! {QUEUE(name='mjpeg_branch_q', leaky='downstream')} ! {mjpeg_branch} "
                    f"t_pre. ! {QUEUE(name='overlay_q', leaky='downstream')} ! "
                    f"{OVERLAY_PIPELINE(name='hailo_overlay')} ! tee name=t_post "
                    f"t_post. ! {QUEUE(name='primary_branch_q', leaky='downstream')} ! {primary_sink} "
                    f"t_post. ! {QUEUE(name='record_branch_q', max_size_buffers=1, leaky='downstream')} ! {record_branch}"
                )
            elif has_mjpeg:
                # MJPEG only: t_pre feeds MJPEG (clean) and overlay → primary
                output_pipeline = (
                    f"tee name=t_pre "
                    f"t_pre. ! {QUEUE(name='mjpeg_branch_q', leaky='downstream')} ! {mjpeg_branch} "
                    f"t_pre. ! {QUEUE(name='overlay_q', leaky='downstream')} ! "
                    f"{OVERLAY_PIPELINE(name='hailo_overlay')} ! {primary_sink}"
                )
            elif has_record:
                # Recording only: overlay → t_post feeds primary + recording
                output_pipeline = (
                    f"{OVERLAY_PIPELINE(name='hailo_overlay')} ! tee name=t_post "
                    f"t_post. ! {QUEUE(name='primary_branch_q', leaky='downstream')} ! {primary_sink} "
                    f"t_post. ! {QUEUE(name='record_branch_q', max_size_buffers=1, leaky='downstream')} ! {record_branch}"
                )
            else:
                # No extra branches: overlay → primary
                output_pipeline = f"{OVERLAY_PIPELINE(name='hailo_overlay')} ! {primary_sink}"

            if skip_tiling:
                # Direct pipeline: source → inference → callback → output
                pipeline_parts = [source_pipeline, detection_pipeline]
            else:
                pipeline_parts = [source_pipeline, tile_cropper_pipeline]
            pipeline_parts.extend([user_callback_pipeline, output_pipeline])

            return ' ! '.join(pipeline_parts)

    _tracker_name = tracker_name or "byte"
    _t0 = time.monotonic()
    _inner_tracker = create_tracker(
        _tracker_name,
        track_thresh=0.4, track_buffer=90, match_thresh=0.5, frame_rate=30,
    )
    _init_ms = (time.monotonic() - _t0) * 1000.0
    tracker = MetricsTracker(_inner_tracker, init_time_ms=_init_ms)
    LOGGER.info("[tracking] %s tracker (init %.1fms) running synchronously in callback",
                _tracker_name, _init_ms)

    user_data = DroneFollowUserData(
        shared_state, target_state, ui_state=ui_state, tracker=tracker,
        reid_manager=reid_manager, reid_search_timeout=reid_search_timeout,
        controller_config=controller_config, log_perf=log_perf,
        sot_enabled=sot_enabled,
    )
    app = DroneFollowTilingApp(
        app_callback, user_data, parser=parser, eos_reached=eos_reached,
        ui_enabled=(ui_state is not None), ui_state=ui_state, ui_fps=ui_fps,
        record_enabled=record_enabled, record_dir=record_dir,
    )
    # Store video dimensions on user_data so the callback can extract
    # frames for ReID cropping without needing a reference to the app.
    user_data.video_width = app.video_width
    user_data.video_height = app.video_height
    return app
