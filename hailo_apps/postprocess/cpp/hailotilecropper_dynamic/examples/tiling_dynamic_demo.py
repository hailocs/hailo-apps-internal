"""Demo: hailotilecropper_dynamic on top of GStreamerTilingApp.

Reuses the standard tiling app from ``hailo_apps`` and swaps the regular
``hailotilecropper`` for the community ``hailotilecropper_dynamic`` element.
Everything else — input source (``--input rpi/usb/file/...``), HEF resolution,
inference pipeline, hailooverlay + display sink, FPS counter — is inherited
from the framework.

Static + dynamic contrast
-------------------------
Two tiles run side-by-side every frame, so the same scene is inferred twice
at different resolutions:

  * **Static tile** — a *large* always-on rectangle on the left half of the
    frame (``--static-tiles`` default ``"0.0,0.05,0.5,0.9"``). It covers a
    wide area, so when ``internal-offset`` rescales it to the model's
    expected input (e.g. 640×480 for the default HEF) every person inside
    occupies only a small fraction of the tile pixels. **Lower per-object
    detail → lower confidence.**

  * **Dynamic tile** — a *small* moving rectangle (0.2 × 0.3) attached
    per-frame via the identity-handoff pattern. Walks left-to-right and
    back. Because it is smaller, internal-offset upscales fewer source
    pixels by a larger factor, so each person inside occupies a larger
    fraction of the model input. **Higher per-object detail → higher
    confidence whenever an object is in the dynamic tile.**

Watch the confidence reported by the user callback as the dynamic tile
sweeps across the frame: persons that show up only in the static tile
report lower confidences than the same persons once the dynamic tile lands
on them. ``hailotileaggregator`` does cross-tile NMS so the higher-
confidence (dynamic-tile) detection wins where the two overlap.

Pass ``--static-tiles ""`` to disable the static tile and run only the
dynamic one.

Pipeline (inherited shape):

    source → identity (attach moving tile)
           → hailotilecropper_dynamic [tiles-static="…"]
                ├─ src_0 (bypass)        → agg.sink_0
                └─ src_1 (cropped tiles) → INFERENCE_PIPELINE → agg.sink_1
                       (one cropped buffer per static + dynamic tile)
           → hailotileaggregator → user_callback → hailooverlay → display

Why this matters: a regular cropper runs inference on every cell of a fixed
grid (uniform budget across the frame). Here inference budget goes where
the application points it — a coarse always-on safety net via the static
tile, plus a high-detail tracker tile via the dynamic injection.

Works on x86_64 and aarch64 (RPi). The plugin .so is preloaded via
``pkg-config --variable=pluginsdir gstreamer-1.0`` so the demo doesn't
hardcode a multiarch directory.

Usage::

    DISPLAY=:0 python tiling_dynamic_demo.py --input test               # videotestsrc
    DISPLAY=:0 python tiling_dynamic_demo.py --input rpi                # RPi CSI camera
    DISPLAY=:0 python tiling_dynamic_demo.py --input /dev/video0        # USB webcam
    DISPLAY=:0 python tiling_dynamic_demo.py --input /path/to/video.mp4 # file

Press Ctrl-C to stop.

The tile-grid flags inherited from the parent app (``--tiles-x``,
``--tiles-y``, ``--multi-scale``, ``--scale-levels``) are ignored — the
dynamic cropper has no grid.
"""
# ---------------------------------------------------------------------------
# Plugin .so preload — must run BEFORE any hailo_apps import so that
# GstHailoBaseCropperDyn registers before libgsthailotools.so registers
# upstream's GstHailoBaseCropper.  Multiarch-portable via pkg-config.
# ---------------------------------------------------------------------------
import ctypes  # noqa: E402
import pathlib  # noqa: E402
import subprocess  # noqa: E402

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[5]  # …/hailo-apps-infra
_BUILD_SO = (
    _REPO_ROOT / "hailo_apps" / "postprocess" / "build.release" / "cpp"
    / "libgsthailotilecropper_dynamic.so"
)


def _system_plugin_so() -> "pathlib.Path | None":
    """Locate the installed plugin via pkg-config (multiarch-portable)."""
    try:
        pluginsdir = subprocess.check_output(
            ["pkg-config", "--variable=pluginsdir", "gstreamer-1.0"],
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return pathlib.Path(pluginsdir) / "libgsthailotilecropper_dynamic.so" if pluginsdir else None


def _preferred_so() -> "pathlib.Path | None":
    """Prefer the freshest of the local build vs. system-installed .so."""
    sys_so = _system_plugin_so()
    candidates = [p for p in (_BUILD_SO, sys_so) if p is not None and p.exists()]
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


_so = _preferred_so()
if _so is not None:
    print(f"Preloading: {_so}", flush=True)
    ctypes.CDLL(str(_so), mode=ctypes.RTLD_GLOBAL)


# ---------------------------------------------------------------------------
# Imports — after the preload above.
# ---------------------------------------------------------------------------
import hailo  # noqa: E402

from hailo_apps.python.core.common.hailo_logger import get_logger  # noqa: E402
from hailo_apps.python.core.gstreamer.gstreamer_app import (  # noqa: E402
    app_callback_class,
    dummy_callback,
)
from hailo_apps.python.core.gstreamer.gstreamer_helper_pipelines import (  # noqa: E402
    DISPLAY_PIPELINE,
    INFERENCE_PIPELINE,
    QUEUE,
    USER_CALLBACK_PIPELINE,
)
from hailo_apps.python.pipeline_apps.tiling.tiling_pipeline import (  # noqa: E402
    GStreamerTilingApp,
)

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Helper: dynamic-tile-cropper pipeline fragment.
# Mirrors hailo_apps' TILE_CROPPER_PIPELINE but with hailotilecropper_dynamic
# and an upstream identity-handoff for per-buffer tile injection.
# ---------------------------------------------------------------------------

def DYNAMIC_TILE_CROPPER_PIPELINE(
    inner_pipeline: str,
    name: str = "dyn_tile_cropper",
    internal_offset: bool = True,
    iou_threshold: float = 0.3,
    border_threshold: float = 0.0,
    tiles_static: str = "",
) -> str:
    """Build a `tile_setter ! cropper [tee] aggregator` chain.

    Same I/O contract as `TILE_CROPPER_PIPELINE` — drops in where that
    helper would be used. The bypass branch carries the original frame to
    `agg.sink_0`; the cropped branch is fed through ``inner_pipeline``
    (typically ``INFERENCE_PIPELINE(...)``) and joins at ``agg.sink_1``.

    Connect a Python handoff to the element named ``{name}_tile_setter`` to
    attach `HailoTileROI` sub-objects per buffer.
    """
    border = (
        f"border-threshold={str(border_threshold).lower()} "
        if border_threshold else ""
    )
    static_prop = f'tiles-static="{tiles_static}" ' if tiles_static else ""
    return (
        f"identity name={name}_tile_setter signal-handoffs=true ! "
        f"{QUEUE(name=f'{name}_input_q')} ! "
        f"hailotilecropper_dynamic name={name}_cropper "
        f"internal-offset={str(internal_offset).lower()} {static_prop}"
        f"hailotileaggregator name={name}_agg "
        f"flatten-detections=true iou-threshold={iou_threshold} {border}"
        # bypass branch
        f"{name}_cropper. ! {QUEUE(name=f'{name}_bypass_q')} ! {name}_agg. "
        # inference branch — capsfilter pins the crop output format to RGB so
        # the cropper's src_1 caps negotiation doesn't fixate on a YUV format
        # (which mismatches the bypass/sink format and trips the cropper's
        # in_format == out_format guard).
        f"{name}_cropper. ! video/x-raw,format=RGB ! {inner_pipeline} ! {name}_agg. "
        # aggregator output
        f"{name}_agg. ! {QUEUE(name=f'{name}_output_q')}"
    )


# ---------------------------------------------------------------------------
# Subclass: same as GStreamerTilingApp, with hailotilecropper_dynamic in the
# pipeline string. Everything else (source, inference, display) is inherited.
# ---------------------------------------------------------------------------

CROPPER_NAME = "dyn_tc"

# Static tile: a *large* always-on rectangle on the left half of the frame.
# Covers a wide area, so when internal-offset rescales it to the model's
# expected input (e.g. 640x480), each person inside occupies only a small
# fraction of the tile pixels — detector confidence drops accordingly.
# Format: "x,y,w,h;…" (normalized 0..1). Use --static-tiles "" to disable.
DEFAULT_STATIC_TILES = "0.0,0.05,0.5,0.9"


class GStreamerDynamicTilingApp(GStreamerTilingApp):
    """Tiling app that uses the community dynamic cropper instead of a fixed grid."""

    def __init__(self, app_callback, user_data, parser=None):
        # The parent already adds many args via _add_tiling_arguments; we
        # tack one more on for the static-tile contrast experiment.
        if parser is None:
            from hailo_apps.python.core.common.core import get_pipeline_parser
            parser = get_pipeline_parser()
        parser.add_argument(
            "--static-tiles",
            default=DEFAULT_STATIC_TILES,
            help=(
                "Semicolon-separated 'x,y,w,h' rectangles (normalized 0..1) "
                "passed to hailotilecropper_dynamic's tiles-static property. "
                f"Default: '{DEFAULT_STATIC_TILES}' (a large always-on tile "
                "on the left half — lower per-object detail, lower accuracy). "
                "Pass '' to disable so only the moving dynamic tile runs."
            ),
        )
        # Walker survives EOS rebuilds so the tile keeps moving smoothly when
        # the framework reloads the file. We attach the handoff after each
        # rebuild via _on_pipeline_rebuilt below.
        self._walker = TileWalker()
        super().__init__(app_callback, user_data, parser)
        self._connect_tile_handoff()

    def _connect_tile_handoff(self):
        """Bind the per-frame tile-injection handoff to the (possibly fresh)
        ``{CROPPER_NAME}_tile_setter`` element in the current pipeline.

        Called once from __init__ and again from ``_on_pipeline_rebuilt``
        after the framework recreates the pipeline on EOS.
        """
        tile_setter = self.pipeline.get_by_name(f"{CROPPER_NAME}_tile_setter")
        if tile_setter is None:
            raise RuntimeError(
                f"could not find '{CROPPER_NAME}_tile_setter' in the pipeline — "
                "DYNAMIC_TILE_CROPPER_PIPELINE wiring is wrong"
            )
        tile_setter.connect("handoff", make_tile_handoff(self._walker))

    def _on_pipeline_rebuilt(self):
        """Reattach the dynamic-tile handoff after the framework rebuilds the
        pipeline on EOS. Without this, the new ``tile_setter`` identity has
        no signal handler and the dynamic tile vanishes from the second loop
        onward (only the static tile keeps producing crops).
        """
        super()._on_pipeline_rebuilt()
        self._connect_tile_handoff()

    def get_pipeline_string(self) -> str:
        source_pipeline = self.get_source_pipeline()

        detection_pipeline = INFERENCE_PIPELINE(
            hef_path=self.hef_path,
            post_process_so=self.post_process_so,
            post_function_name=self.post_function,
            batch_size=self.batch_size,
            config_json=self.labels_json,
        )

        tile_cropper_pipeline = DYNAMIC_TILE_CROPPER_PIPELINE(
            detection_pipeline,
            name=CROPPER_NAME,
            internal_offset=True,
            iou_threshold=self.iou_threshold,
            tiles_static=self.options_menu.static_tiles,
        )

        user_callback_pipeline = USER_CALLBACK_PIPELINE()

        display_pipeline = DISPLAY_PIPELINE(
            video_sink=self.video_sink,
            sync=self.sync,
            show_fps=self.show_fps,
        )

        return (
            f"{source_pipeline} ! "
            f"{tile_cropper_pipeline} ! "
            f"{user_callback_pipeline} ! "
            f"{display_pipeline}"
        )


# ---------------------------------------------------------------------------
# Per-frame: walk a single tile across the frame.
# ---------------------------------------------------------------------------

class TileWalker:
    """Returns a small moving tile each frame; left edge bounces across the frame.

    Intentionally smaller than the default static tile so that, when an object
    falls inside the dynamic crop, internal-offset's rescale-to-model-input
    upscales fewer source pixels by a larger factor — the object occupies a
    larger fraction of the model's input field, and per-object confidence
    typically rises versus what the static tile alone produces.
    """

    TILE_W = 0.2
    TILE_H = 0.3
    TILE_Y = 0.25
    # Walk the left edge across most of the frame; X_MAX is set so the tile
    # stays in-frame (X_MAX + TILE_W ≤ 1.0).
    X_MIN = 0.0
    X_MAX = 0.8
    PHASE_STEP = 0.02

    def __init__(self):
        self._phase = 0.0
        self._frames = 0

    def step(self) -> "hailo.HailoTileROI":
        x = self.X_MIN + (self.X_MAX - self.X_MIN) * abs((self._phase % 2.0) - 1.0)
        self._phase += self.PHASE_STEP
        self._frames += 1
        if self._frames % 30 == 0:
            print(f"  frame {self._frames:5d}  tile x={x:.3f}", flush=True)
        return hailo.HailoTileROI(
            hailo.HailoBBox(x, self.TILE_Y, self.TILE_W, self.TILE_H),
            0, 0.0, 0.0, 0, hailo.SINGLE_SCALE,
        )


def make_tile_handoff(walker: TileWalker):
    def handoff(_identity, buf):
        roi = hailo.get_roi_from_buffer(buf)
        roi.add_object(walker.step())
    return handoff


# ---------------------------------------------------------------------------
# User callback: log the merged detections per frame (optional but nice).
# ---------------------------------------------------------------------------

class UserData(app_callback_class):
    pass


def app_callback(_pad, buffer, user_data):
    if buffer is None:
        return
    dets = list(
        hailo.get_roi_from_buffer(buffer).get_objects_typed(hailo.HAILO_DETECTION)
    )
    if dets:
        labels = ", ".join(f"{d.get_label()}@{d.get_confidence():.2f}" for d in dets[:5])
        print(f"  frame {user_data.get_count():5d}  detections=[{labels}]", flush=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    logger.info("Starting hailotilecropper_dynamic demo (on top of GStreamerTilingApp)")

    user_data = UserData()
    app = GStreamerDynamicTilingApp(app_callback, user_data)
    # Tile handoff is wired in the constructor and re-wired on every EOS
    # rebuild via _on_pipeline_rebuilt — nothing more to do here.
    app.run()


if __name__ == "__main__":
    main()
