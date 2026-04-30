"""Demo: hailotilecropper_dynamic with a moving dynamic tile.

Demonstrates:
  - src_0 (bypass): full original frame flows through to the aggregator main input
  - src_1 (crop):   one tile per frame around a moving region (dynamic)
  - The tile bbox walks left-to-right and back across the frame

In a real pipeline you would replace the ``identity name=fake_inf`` element
with a ``hailofilter`` running inference on the cropped tile.  The aggregator
(``hailotileaggregator``) then merges the per-tile detections back into the
full-frame coordinate space.

Note on display: ``hailotileaggregator`` does not expose caps on its src pad
in a way that ``videoconvert`` / ``autovideosink`` can negotiate.  The demo
therefore uses ``fakesink`` for headless validation.  In production, wire the
aggregator's src pad into a ``hailodisplay`` or a ``hailooverlay ! videoconvert
! autovideosink`` chain that pulls caps from upstream elements.

Press Ctrl-C to stop.

The demo prefers the freshly built .so under build.release/ when present (so it
runs before ``sudo hailo-compile-postprocess install`` updates the system .so).

Usage::

    python examples/tiling_dynamic_demo.py
    python examples/tiling_dynamic_demo.py --frames 300
    python examples/tiling_dynamic_demo.py --width 320 --height 240
"""
import argparse
import ctypes
import pathlib
import sys

# ---------------------------------------------------------------------------
# Preload the freshest plugin .so before GStreamer init — same approach as
# tests/e2e/conftest.py.  Needed when the system-installed .so is stale.
# ---------------------------------------------------------------------------
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[5]  # …/hailo-apps-infra
_BUILD_SO = (
    _REPO_ROOT / "hailo_apps" / "postprocess" / "build.release" / "cpp"
    / "libgsthailotilecropper_dynamic.so"
)
_SYS_SO = pathlib.Path(
    "/usr/lib/x86_64-linux-gnu/gstreamer-1.0/libgsthailotilecropper_dynamic.so"
)


def _preferred_so() -> pathlib.Path | None:
    if _BUILD_SO.exists() and _SYS_SO.exists():
        return _BUILD_SO if _BUILD_SO.stat().st_mtime > _SYS_SO.stat().st_mtime else _SYS_SO
    return _BUILD_SO if _BUILD_SO.exists() else (_SYS_SO if _SYS_SO.exists() else None)


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
# Dynamic tile callback
# ---------------------------------------------------------------------------

def make_attach_dynamic_tile():
    """Return a handoff callback that attaches a single dynamic tile per buffer.

    Walks the tile bbox left-to-right and back across the frame.  In a real
    app this is where you'd plug in tracker output.
    """
    state = {"phase": 0.0, "frames": 0}

    def handoff(_identity, buf):
        roi = hailo.get_roi_from_buffer(buf)
        # x oscillates between 0.1 and 0.5 so the 0.4-wide tile stays in frame
        x = 0.1 + 0.4 * abs((state["phase"] % 2.0) - 1.0)
        roi.add_object(hailo.HailoTileROI(
            hailo.HailoBBox(x, 0.2, 0.4, 0.4),
            0, 0.0, 0.0, 0, hailo.SINGLE_SCALE,
        ))
        state["phase"] += 0.05
        state["frames"] += 1
        if state["frames"] % 30 == 0:
            print(f"  frame {state['frames']:5d}  tile x={x:.3f}", flush=True)

    return handoff


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--width", type=int, default=640)
    p.add_argument("--height", type=int, default=480)
    p.add_argument("--frames", type=int, default=0,
                   help="Number of frames to process (0 = run until Ctrl-C)")
    args = p.parse_args()

    num_buffers = f"num-buffers={args.frames}" if args.frames > 0 else ""

    pipeline_str = (
        f"videotestsrc is-live=false {num_buffers} ! "
        f"videoconvert ! "
        f"video/x-raw,format=RGB,width={args.width},height={args.height},framerate=30/1 ! "
        "identity name=tile_setter signal-handoffs=true ! "
        "hailotilecropper_dynamic name=tc "
        "tc.src_0 ! queue ! agg.sink_0 "
        "tc.src_1 ! queue ! identity name=fake_inf signal-handoffs=true ! agg.sink_1 "
        "hailotileaggregator name=agg flatten-detections=true iou-threshold=0.3 "
        "agg.src ! fakesink sync=false async=false"
    )
    print(f"Pipeline:\n  {pipeline_str}\n", flush=True)

    pipe = Gst.parse_launch(pipeline_str)
    pipe.get_by_name("tile_setter").connect("handoff", make_attach_dynamic_tile())

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
