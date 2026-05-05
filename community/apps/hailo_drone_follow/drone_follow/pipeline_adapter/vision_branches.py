"""Pipeline output branches for drone-follow.

After source -> tile_cropper(detection) -> user_callback, the pipeline tees
into up to four branches. Only the ones the operator opts into are built::

    tee output_tee
        ├─ [--webui]   : MJPEG appsink (clean frames; client renders bbox)
        ├─ [--openhd]  : RTP H.264 over UDP to an OpenHD ground station
        └─ [--display / --record]
                       : identity local_meta_id  (pad probe: replace the
                                                  target's HailoDetection
                                                  with one whose class_id
                                                  is TARGET_OVERLAY_CLASS_ID
                                                  so the per-class YAML
                                                  style applies)
                       : hailooverlay_community show-tiles=false
                                                style-config=<yaml>
                       : tee local_tee
                            ├─ [--display] : videoconvert + fpsdisplaysink
                            └─ [--record]  : valve + H.264 + matroskamux + filesink

All vision work uses GStreamer-native elements + Hailo metadata APIs;
no pad probe maps the buffer pixels.

Tile-bbox suppression is handled at the element level
(``show-tiles=false``). Per-detection emphasis (color + line thickness)
is delegated to the community overlay's YAML style-config: the pad probe
just retags the target detection with a sentinel class_id; the YAML rule
under ``styles.<TARGET_OVERLAY_CLASS_ID>`` defines what that class looks
like (green, thicker line, etc.).
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from typing import Optional

import hailo

LOGGER = logging.getLogger(__name__)

# Sentinel class_id used to retag the locked/auto target detection on
# the local branch. The YAML style-config maps this to a thicker green
# bbox; all other detections keep their default class_id and inherit
# the element-level (thin) line thickness.
TARGET_OVERLAY_CLASS_ID = 99

# Packed 0xRRGGBB colour drawn around every non-target detection on the
# local branch. Attached via an ``overlay_color`` HailoClassification
# (read by hailooverlay_community when ``use-custom-colors=true``).
NON_TARGET_BBOX_COLOR_RGB = 0xFFFFFF  # white

# Path to the bundled overlay style YAML. Resolved relative to this file
# so the module works from a checkout, an editable install, or a copied
# tree without env-var fiddling.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_STYLE_CONFIG = os.path.normpath(
    os.path.join(_THIS_DIR, "..", "..", "configs", "overlay_style.yaml")
)
DEFAULT_OVERLAY_STYLE_CONFIG = (
    _DEFAULT_STYLE_CONFIG if os.path.isfile(_DEFAULT_STYLE_CONFIG) else ""
)


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
    (pad-probe attachment point for :func:`highlight_target`) and a
    single ``hailooverlay_community``.
    """
    if not display and not record:
        raise ValueError("local_branch requires display or record (or both)")

    overlay_props = (
        "show-tiles=false line-thickness=2 "
        "font-thickness=1 text-background=true "
        "use-custom-colors=true"
    )
    if DEFAULT_OVERLAY_STYLE_CONFIG:
        overlay_props += f' style-config="{DEFAULT_OVERLAY_STYLE_CONFIG}"'
    head = (
        "queue name=local_branch_q leaky=downstream max-size-buffers=3 ! "
        "identity name=local_meta_id ! "
        "queue name=hailo_overlay_q ! "
        f"hailooverlay_community name=hailo_overlay {overlay_props}"
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

def _tag_white(det):
    """Attach an ``overlay_color`` classification (white) so the local
    overlay renders this detection with a white bbox. Idempotent.
    """
    for cls in det.get_objects_typed(hailo.HAILO_CLASSIFICATION):
        if cls.get_classification_type() == "overlay_color":
            return
    det.add_object(hailo.HailoClassification(
        "overlay_color",            # classification type read by overlay
        NON_TARGET_BBOX_COLOR_RGB,  # class_id = packed 0xRRGGBB (white)
        "",                         # label (unused on packed-int path)
        0.0,                        # confidence
    ))


def highlight_target(pad, info, target_state):
    """Style the local-branch detections so the operator can tell the
    locked/auto target apart from everyone else at a glance:

    * **Target**: retagged with ``class_id = TARGET_OVERLAY_CLASS_ID`` so
      the YAML style-config rule applies — thicker, green bbox.
    * **Non-target detections**: an ``overlay_color`` classification of
      :data:`NON_TARGET_BBOX_COLOR_RGB` (white) is attached so they render
      in white at the element-level (thin) line thickness.

    Pure metadata work — no pixel buffers are mapped.

    HailoDetection has no ``set_class_id`` setter in the Python binding,
    so the target detection is replaced with a copy carrying the new
    class_id; sub-objects (HailoUniqueID, classifications, …) are
    re-attached so downstream metadata survives.
    """
    import gi  # noqa: F401 — local import keeps gi out of module-load time
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    buffer = info.get_buffer()
    if buffer is None:
        return Gst.PadProbeReturn.OK

    target_id = target_state.get_target() if target_state is not None else None
    roi = hailo.get_roi_from_buffer(buffer)
    target_orig = None
    others = []

    for det in roi.get_objects_typed(hailo.HAILO_DETECTION):
        is_target = False
        if target_id is not None and target_id > 0:
            for uid in det.get_objects_typed(hailo.HAILO_UNIQUE_ID):
                if uid.get_id() == target_id:
                    is_target = True
                    break
        if is_target and det.get_class_id() != TARGET_OVERLAY_CLASS_ID:
            target_orig = det
        elif not is_target:
            others.append(det)

    # Tag every non-target detection white so it stands apart from the
    # target's green bbox. Idempotent across probe re-runs.
    for det in others:
        _tag_white(det)

    # Retag the target detection so the YAML rule for class_id 99 fires.
    if target_orig is not None:
        bbox = target_orig.get_bbox()
        new_det = hailo.HailoDetection(
            bbox, TARGET_OVERLAY_CLASS_ID, target_orig.get_label(),
            target_orig.get_confidence(),
        )
        for child in list(target_orig.get_objects()):
            # Skip any pre-existing overlay_color classification —
            # otherwise the metadata would override the YAML green.
            if (isinstance(child, hailo.HailoClassification)
                    and child.get_classification_type() == "overlay_color"):
                continue
            try:
                new_det.add_object(child)
            except Exception:  # noqa: BLE001 — child re-attach is best-effort
                pass
        roi.remove_object(target_orig)
        roi.add_object(new_det)

    return Gst.PadProbeReturn.OK


# Backwards-compat alias — older callers may still import the old name.
strip_tiles_and_highlight_target = highlight_target


def wire_local_meta_probe(pipeline, target_state) -> bool:
    """Attach :func:`highlight_target` to the ``local_meta_id`` identity
    element if it exists in the pipeline.

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
        highlight_target,
        target_state,
    )
    return True
