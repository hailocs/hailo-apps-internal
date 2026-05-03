"""Demo: hailotilecropper_dynamic with a moving dynamic tile (with display).

What you see:
    A source video (test pattern, RPi camera, USB cam, or file) plays in a
    window with a red rectangle drawn at the tile's location each frame.
    The rectangle walks left-to-right and back across the frame, showing
    where the dynamic tile cropper is currently cropping.

Pipeline:
    source → identity (attach HailoTileROI per buffer) → hailotilecropper_dynamic
                                                              ↓ src_0 (bypass)
                                                                  → videoconvert
                                                                  → cairooverlay (draws tile box)
                                                                  → autovideosink
                                                              ↓ src_1 (cropped tile)
                                                                  → fakesink

The bypass branch (src_0) is the one displayed because it carries the
unmodified original frame; cairooverlay draws the tile box on top so you can
see *where* the cropper is operating without depending on the aggregator +
hailooverlay path (which requires real inference output to be useful).

The cropped output (src_1) is consumed by fakesink — in a real pipeline this
is where ``hailonet ! hailofilter`` runs inference on the tile and feeds the
result into ``hailotileaggregator``. See
``tests/e2e/test_e2e_aggregator_compat.py`` for the full aggregator wiring.

Works on x86_64 and aarch64 (RPi). The plugin .so is preloaded via the path
returned by ``pkg-config --variable=pluginsdir gstreamer-1.0`` so the demo
doesn't hardcode any multiarch directory.

Usage:
    DISPLAY=:0 python tiling_dynamic_demo.py                            # videotestsrc (default)
    DISPLAY=:0 python tiling_dynamic_demo.py --input libcamera          # RPi CSI camera
    DISPLAY=:0 python tiling_dynamic_demo.py --input /dev/video0        # USB webcam
    DISPLAY=:0 python tiling_dynamic_demo.py --input /path/to/video.mp4 # file
    python tiling_dynamic_demo.py --frames 60 --no-display              # headless smoke test

Press Ctrl-C to stop.
"""
import argparse
import ctypes
import pathlib
import subprocess
import sys

# ---------------------------------------------------------------------------
# Plugin .so preload — works on any arch via pkg-config.
#
# GStreamer caches its plugin registry, so a freshly-built .so under
# build.release/ may not be picked up before ``hailo-compile-postprocess
# install`` updates the system copy. Preloading forces the library into the
# process so Gst.init resolves the element regardless of registry state.
# ---------------------------------------------------------------------------
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[5]  # …/hailo-apps-infra
_BUILD_SO = (
    _REPO_ROOT / "hailo_apps" / "postprocess" / "build.release" / "cpp"
    / "libgsthailotilecropper_dynamic.so"
)


def _system_plugin_so() -> pathlib.Path | None:
    """Locate the installed plugin via pkg-config (multiarch-portable)."""
    try:
        pluginsdir = subprocess.check_output(
            ["pkg-config", "--variable=pluginsdir", "gstreamer-1.0"],
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return pathlib.Path(pluginsdir) / "libgsthailotilecropper_dynamic.so" if pluginsdir else None


def _preferred_so() -> pathlib.Path | None:
    """Prefer the freshest of the local build vs. system-installed .so."""
    sys_so = _system_plugin_so()
    candidates = [p for p in (_BUILD_SO, sys_so) if p is not None and p.exists()]
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


_so = _preferred_so()
if _so is not None:
    print(f"Preloading: {_so}", flush=True)
    ctypes.CDLL(str(_so), mode=ctypes.RTLD_GLOBAL)

import gi  # noqa: E402

gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib  # noqa: E402
import hailo  # noqa: E402

Gst.init(None)


# ---------------------------------------------------------------------------
# Source-element selection (mirrors hailo_apps' SOURCE_PIPELINE conventions)
# ---------------------------------------------------------------------------

def build_source_element(input_src: str, width: int, height: int, frames: int) -> str:
    """Return a GStreamer source chain ending in ``video/x-raw,format=RGB,WxH``."""
    common_caps = f"video/x-raw,format=RGB,width={width},height={height}"
    num_buffers = f" num-buffers={frames}" if frames > 0 else ""

    if input_src == "test":
        return (
            f"videotestsrc is-live=false{num_buffers} ! "
            f"videoconvert ! {common_caps},framerate=30/1"
        )
    if input_src == "libcamera":
        # RPi CSI camera via libcamera. Requires libcamera + gstreamer1.0-libcamera.
        return (
            f"libcamerasrc ! video/x-raw,framerate=30/1 ! "
            f"videoscale ! videoconvert ! {common_caps}"
        )
    if input_src.startswith("/dev/video"):
        # V4L2 device (USB webcam). MJPEG via decodebin handles most webcams.
        return (
            f"v4l2src device={input_src}{num_buffers} ! image/jpeg,framerate=30/1 ! "
            f"decodebin ! videoscale ! videoconvert ! {common_caps}"
        )
    # Anything else — treat as a file path.
    return (
        f"filesrc location=\"{input_src}\" ! decodebin ! "
        f"videoscale ! videoconvert ! {common_caps}"
    )


# ---------------------------------------------------------------------------
# Tile state shared between the cropper-handoff and the cairooverlay draw.
# ---------------------------------------------------------------------------

class TileWalker:
    """Per-frame tile generator. Walks a 0.4-wide tile back and forth."""

    TILE_W = 0.4
    TILE_H = 0.4
    TILE_Y = 0.2
    X_MIN = 0.1
    X_MAX = 0.5  # so left edge stays in [0.1, 0.5] → tile fully in frame
    PHASE_STEP = 0.05

    def __init__(self):
        self._phase = 0.0
        self._frames = 0
        self.x = self.X_MIN

    def step(self) -> float:
        """Advance one frame. Returns the new tile x (left edge, normalized)."""
        self.x = self.X_MIN + (self.X_MAX - self.X_MIN) * abs((self._phase % 2.0) - 1.0)
        self._phase += self.PHASE_STEP
        self._frames += 1
        if self._frames % 30 == 0:
            print(f"  frame {self._frames:5d}  tile x={self.x:.3f}", flush=True)
        return self.x


# ---------------------------------------------------------------------------
# Pipeline callbacks
# ---------------------------------------------------------------------------

def make_attach_dynamic_tile(walker: TileWalker):
    """Handoff that attaches one moving tile per buffer.

    In a real app this is where tracker / detector output goes.
    """
    def handoff(_identity, buf):
        x = walker.step()
        roi = hailo.get_roi_from_buffer(buf)
        roi.add_object(hailo.HailoTileROI(
            hailo.HailoBBox(x, walker.TILE_Y, walker.TILE_W, walker.TILE_H),
            0, 0.0, 0.0, 0, hailo.SINGLE_SCALE,
        ))
    return handoff


def make_draw_tile_box(walker: TileWalker, frame_w: int, frame_h: int):
    """cairooverlay draw handler — paints the current tile rectangle on the frame."""
    def draw(_overlay, ctx, _ts, _dur):
        x = walker.x * frame_w
        y = walker.TILE_Y * frame_h
        w = walker.TILE_W * frame_w
        h = walker.TILE_H * frame_h
        ctx.set_source_rgb(1.0, 0.2, 0.2)  # red
        ctx.set_line_width(3.0)
        ctx.rectangle(x, y, w, h)
        ctx.stroke()
    return draw


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--input", default="test",
                   help="Source: 'test' (videotestsrc, default), 'libcamera' (RPi CSI), "
                        "'/dev/videoN' (V4L2), or path to a video file.")
    p.add_argument("--width", type=int, default=640)
    p.add_argument("--height", type=int, default=480)
    p.add_argument("--frames", type=int, default=0,
                   help="Number of frames to process (0 = run until Ctrl-C). "
                        "Only honoured for 'test' and V4L2 sources.")
    p.add_argument("--no-display", action="store_true",
                   help="Use fakesink instead of autovideosink (headless smoke test).")
    args = p.parse_args()

    walker = TileWalker()
    source = build_source_element(args.input, args.width, args.height, args.frames)
    primary_sink = (
        "fakesink sync=false async=false"
        if args.no_display
        else "videoconvert ! autovideosink sync=false"
    )

    pipeline_str = (
        f"{source} ! "
        "identity name=tile_setter signal-handoffs=true ! "
        "hailotilecropper_dynamic name=tc internal-offset=true "
        # Bypass branch (src_0): the original frame, displayed with a tile-box overlay.
        f"tc.src_0 ! queue ! videoconvert ! cairooverlay name=tile_overlay ! {primary_sink} "
        # Cropped branch (src_1): consume so the cropper has somewhere to push.
        # In a real pipeline this is hailonet ! hailofilter ! agg.sink_1.
        "tc.src_1 ! queue ! fakesink sync=false async=false"
    )
    print(f"Pipeline:\n  {pipeline_str}\n", flush=True)

    pipe = Gst.parse_launch(pipeline_str)
    pipe.get_by_name("tile_setter").connect("handoff", make_attach_dynamic_tile(walker))
    pipe.get_by_name("tile_overlay").connect(
        "draw", make_draw_tile_box(walker, args.width, args.height)
    )

    loop = GLib.MainLoop()
    bus = pipe.get_bus()
    bus.add_signal_watch()

    def on_msg(_b, msg):
        t = msg.type
        if t == Gst.MessageType.EOS:
            print("EOS received — stopping.", flush=True)
            loop.quit()
        elif t == Gst.MessageType.ERROR:
            err, dbg = msg.parse_error()
            print(f"ERROR: {err.message}\n{dbg}", file=sys.stderr)
            loop.quit()
    bus.connect("message", on_msg)

    pipe.set_state(Gst.State.PLAYING)
    print("Pipeline running — press Ctrl-C to stop.\n", flush=True)
    try:
        loop.run()
    except KeyboardInterrupt:
        print("\nInterrupted.", flush=True)
    finally:
        pipe.set_state(Gst.State.NULL)
    print("Pipeline stopped.", flush=True)


if __name__ == "__main__":
    main()
