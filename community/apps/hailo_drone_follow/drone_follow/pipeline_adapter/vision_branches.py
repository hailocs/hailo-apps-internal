"""Pipeline output branches for drone-follow.

After source -> tile_cropper(detection) -> user_callback, the pipeline tees
into up to four branches. Only the ones the operator opts into are built::

    tee output_tee
        ├─ [--webui]   : MJPEG appsink (clean frames; client renders bbox)
        ├─ [--openhd]  : RTP H.264 over UDP to an OpenHD ground station
        └─ [--display / --record]
                       : identity local_meta_id  (pad probe: strip_tiles +
                                                  highlight_target — both
                                                  pure-metadata, no pixels)
                       : hailooverlay
                       : tee local_tee
                            ├─ [--display] : videoconvert + fpsdisplaysink
                            └─ [--record]  : valve + H.264 + matroskamux + filesink

All vision work uses GStreamer-native elements + Hailo metadata APIs;
no pad probe maps the buffer pixels.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from typing import Optional

import hailo

LOGGER = logging.getLogger(__name__)

# class_id used to recolour the locked/auto target detection on the local
# display branch. hailooverlay paints by class_id (deterministic palette in
# the compiled .so); 99 is far above any COCO class so the colour clearly
# differs from the default 'person' bbox. Tune this if the rendered colour
# isn't visually distinguishable enough on your display.
TARGET_CLASS_ID = 99


# ---------------------------------------------------------------------------
# H.264 encoder selection
# ---------------------------------------------------------------------------

_H264_ENCODER_TEMPLATE: Optional[str] = None


def select_h264_encoder(bitrate_bps: int, bitrate_kbps: int) -> str:
    """Return a launch fragment for the best available H.264 SW encoder.

    Tries ``x264enc`` first (gst-plugins-ugly — better quality / latency,
    historically preferred on RPi for OpenHD), then falls back to
    ``openh264enc`` (gst-plugins-bad — pre-installed on most RPi images).
    The result is cached so repeated calls don't re-shell out to
    ``gst-inspect-1.0``.

    Both encoders accept a ``bitrate`` property but with different units;
    we render the right value for whichever encoder is chosen, and
    callers that update bitrate at runtime (the OpenHD bridge) need to
    handle the unit difference themselves via ``encoder.get_factory().get_name()``.
    """
    global _H264_ENCODER_TEMPLATE
    if _H264_ENCODER_TEMPLATE is None:
        _H264_ENCODER_TEMPLATE = _detect_h264_encoder()
    return _H264_ENCODER_TEMPLATE.format(bps=bitrate_bps, kbps=bitrate_kbps)


def _detect_h264_encoder() -> str:
    def _has(elem: str) -> bool:
        if not shutil.which("gst-inspect-1.0"):
            return False
        rc = subprocess.run(["gst-inspect-1.0", elem],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL).returncode
        return rc == 0

    if _has("x264enc"):
        return ("x264enc tune=zerolatency speed-preset=ultrafast "
                "bitrate={kbps}")
    if _has("openh264enc"):
        return ("openh264enc bitrate={bps} complexity=low "
                "rate-control=bitrate gop-size=15")
    raise RuntimeError(
        "No H.264 encoder found. Install one of:\n"
        "  sudo apt install gstreamer1.0-plugins-ugly   # provides x264enc\n"
        "  sudo apt install gstreamer1.0-plugins-bad    # provides openh264enc"
    )


# ---------------------------------------------------------------------------
# Branch fragments
# ---------------------------------------------------------------------------

def webui_branch(ui_fps: int) -> str:
    """MJPEG appsink for the web UI. Clean frames (no overlay) so the
    browser can render its own interactive SVG bboxes on top.
    """
    return (
        "queue name=mjpeg_branch_q leaky=downstream max-size-buffers=3 ! "
        "videoconvert n-threads=2 ! "
        f"videorate max-rate={ui_fps} ! "
        f"video/x-raw,framerate={ui_fps}/1 ! "
        "jpegenc quality=70 ! "
        "appsink name=mjpeg_sink sync=false drop=true emit-signals=true"
    )


def openhd_branch(port: int, bitrate_kbps: int) -> str:
    """OpenHD branch — H.264 SW encode + RTP + UDP sink. Element name
    ``openhd_stream_encoder`` is preserved for the OpenHD bridge's
    bitrate-update probe.
    """
    bitrate_bps = bitrate_kbps * 1000
    encoder = select_h264_encoder(bitrate_bps, bitrate_kbps)
    factory, props = encoder.split(" ", 1)
    return (
        "queue name=openhd_branch_q leaky=downstream max-size-buffers=3 ! "
        "queue name=openhd_stream_convert_q ! "
        "videoconvert n-threads=2 ! video/x-raw,format=I420 ! "
        "queue name=openhd_stream_enc_q ! "
        f"{factory} name=openhd_stream_encoder {props} ! "
        "h264parse config-interval=1 ! "
        "rtph264pay config-interval=1 pt=96 mtu=1440 ! "
        f"udpsink host=127.0.0.1 port={port} sync=false async=false"
    )


def _display_subbranch(video_sink: str, sync: str, show_fps: str) -> str:
    return (
        "queue name=display_branch_q leaky=downstream max-size-buffers=3 ! "
        "videoconvert name=hailo_display_videoconvert n-threads=2 qos=false ! "
        "queue name=hailo_display_q ! "
        f"fpsdisplaysink name=hailo_display video-sink={video_sink} "
        f"sync={sync} text-overlay={show_fps} signal-fps-measurements=true"
    )


def _record_subbranch(record_output: str, record_bitrate_kbps: int) -> str:
    bitrate_bps = record_bitrate_kbps * 1000
    encoder = select_h264_encoder(bitrate_bps, record_bitrate_kbps)
    return (
        "queue name=record_branch_q leaky=downstream max-size-buffers=3 ! "
        "valve name=record_valve drop=true ! "
        "videoconvert n-threads=2 ! "
        f"{encoder} ! "
        "h264parse config-interval=1 ! "
        "matroskamux name=file_sink_mux ! "
        f"filesink name=file_sink location={record_output}"
    )


def local_branch(*, display: bool, record: bool, record_output: Optional[str],
                 record_bitrate_kbps: int, video_sink: str, sync: str,
                 show_fps: str) -> str:
    """Display + record local branch.

    Both sub-branches share an upstream ``identity name=local_meta_id``
    (pad-probe attachment point for ``strip_tiles_and_highlight_target``)
    and a single ``hailooverlay``.
    """
    if not display and not record:
        raise ValueError("local_branch requires display or record (or both)")

    head = (
        "queue name=local_branch_q leaky=downstream max-size-buffers=3 ! "
        "identity name=local_meta_id ! "
        "queue name=hailo_overlay_q ! hailooverlay name=hailo_overlay"
    )

    subs = []
    if display:
        subs.append(_display_subbranch(video_sink, sync, show_fps))
    if record:
        if record_output is None:
            raise ValueError("record=True requires a record_output path")
        subs.append(_record_subbranch(record_output, record_bitrate_kbps))

    if len(subs) == 1:
        return f"{head} ! {subs[0]}"
    return (f"{head} ! tee name=local_tee "
            + " ".join(f"local_tee. ! {sub}" for sub in subs))


def assemble_output_stage(*, display: bool, record: bool, openhd: bool,
                          webui: bool, openhd_port: int = 5500,
                          openhd_bitrate_kbps: int = 3917,
                          ui_fps: int = 10, record_output: Optional[str] = None,
                          record_bitrate_kbps: int = 5000,
                          video_sink: str = "autovideosink", sync: str = "false",
                          show_fps: str = "false",
                          fakesink_sync: str = "false") -> str:
    """Build the full output stage (everything after user_callback).

    Returns a single launch-string. If exactly one output is requested,
    returns just that branch. If multiple, wraps them in a top-level
    ``tee output_tee``. If none, returns a fakesink so the pipeline is
    still well-formed.
    """
    branches = []
    if webui:
        branches.append(webui_branch(ui_fps))
    if openhd:
        branches.append(openhd_branch(openhd_port, openhd_bitrate_kbps))
    if display or record:
        branches.append(local_branch(
            display=display, record=record,
            record_output=record_output,
            record_bitrate_kbps=record_bitrate_kbps,
            video_sink=video_sink, sync=sync, show_fps=show_fps,
        ))

    if not branches:
        return f"fakesink name=fake_sink sync={fakesink_sync}"
    if len(branches) == 1:
        return branches[0]
    return ("tee name=output_tee "
            + " ".join(f"output_tee. ! {b}" for b in branches))


# ---------------------------------------------------------------------------
# Metadata pad probe (display/record branch)
# ---------------------------------------------------------------------------

def strip_tiles_and_highlight_target(pad, info, target_state):
    """Pure-metadata pad probe for the local (display/record) branch.

    1. Remove ``HAILO_TILE`` sub-objects so ``hailooverlay`` does not draw
       the tile grid. Detections are unaffected because the tile aggregator
       already flattens them onto the parent ROI.

    2. If a target is locked, replace the target's ``HailoDetection`` with
       a copy carrying ``class_id=TARGET_CLASS_ID`` so ``hailooverlay``
       paints it in a different palette colour, visually emphasising the
       followed person. Other detections are left at their default colour.

    No pixel buffers are mapped; only ROI metadata is touched.
    """
    # Local import — avoid pulling gi at import time.
    import gi  # noqa: F401
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    buffer = info.get_buffer()
    if buffer is None:
        return Gst.PadProbeReturn.OK

    roi = hailo.get_roi_from_buffer(buffer)

    for tile in roi.get_objects_typed(hailo.HAILO_TILE):
        roi.remove_object(tile)

    target_id = target_state.get_target() if target_state is not None else None
    if target_id is None or target_id <= 0:
        return Gst.PadProbeReturn.OK

    for det in roi.get_objects_typed(hailo.HAILO_DETECTION):
        match = False
        for uid in det.get_objects_typed(hailo.HAILO_UNIQUE_ID):
            if uid.get_id() == target_id:
                match = True
                break
        if not match:
            continue
        if det.get_class_id() == TARGET_CLASS_ID:
            return Gst.PadProbeReturn.OK
        bbox = det.get_bbox()
        new_det = hailo.HailoDetection(bbox, TARGET_CLASS_ID, det.get_label(),
                                       det.get_confidence())
        for child in list(det.get_objects()):
            try:
                new_det.add_object(child)
            except Exception:  # noqa: BLE001 — child re-attach is best-effort
                pass
        roi.remove_object(det)
        roi.add_object(new_det)
        break

    return Gst.PadProbeReturn.OK


def wire_local_meta_probe(pipeline, target_state) -> bool:
    """Attach :func:`strip_tiles_and_highlight_target` to the
    ``local_meta_id`` identity element if it exists in the pipeline.

    Returns True if a probe was attached; False if the element is absent
    (no display/record branch was built). Safe to call after every
    pipeline rebuild.
    """
    ident = pipeline.get_by_name("local_meta_id")
    if ident is None:
        return False
    src_pad = ident.get_static_pad("src")
    if src_pad is None:
        return False
    import gi  # noqa: F401
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst
    src_pad.add_probe(
        Gst.PadProbeType.BUFFER,
        strip_tiles_and_highlight_target,
        target_state,
    )
    return True
