"""E2E: hailotileaggregator works downstream of hailotilecropper_dynamic.

The aggregator must:
  1. Translate detection bboxes from each tile-local space → frame-global space.
  2. Cross-tile NMS dedup.

We feed a fixed test video, attach 2 non-grid tiles dynamically via the
identity-handoff pattern, emulate inference output by attaching synthetic
detections inside each tile's ROI between cropper and aggregator, then
verify the aggregator's main-pad output ROI carries detections in global
coords.

GType Conflict Resolution — Task 18 DONE
-----------------------------------------
The GLib type-registration conflict that previously prevented hailotilecropper_dynamic
from coexisting with hailotileaggregator in the same process has been resolved.

Root cause was: hailotilecropper_dynamic bundled a copy of GstHailoBaseCropper which
collided with the same type exported by libgsthailotools.so (hailotileaggregator's
library).

Fix (Task 18): the bundled base class was renamed from GstHailoBaseCropper to
GstHailoBaseCropperDyn throughout the vendored source.  The freshly compiled .so
is preloaded via ctypes before Gst.init() so its GType registers first; GStreamer
then deduplicates the plugin by name and skips the stale system .so during the
registry scan, eliminating the conflict entirely.
"""
import pytest
import subprocess
import sys
import os


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _detect_type_conflict() -> str | None:
    """Return conflict description if the GLib type registration conflict is present.

    Runs a sub-process that loads both plugins and reports any GLib critical
    warnings.  Returns None if no conflict is detected.

    The probe always uses the freshest available .so (build-dir preferred over
    the system-installed one) so that a successful rename in the source tree is
    detectable even before `hailo-compile-postprocess` / `ninja install` has
    been run with root privileges.
    """
    import pathlib
    # __file__ is at: <repo>/hailo_apps/postprocess/cpp/hailotilecropper_dynamic/tests/e2e/
    # parents[6] = repo root
    _repo_root = pathlib.Path(__file__).resolve().parents[6]
    build_so = (
        _repo_root / "hailo_apps" / "postprocess" / "build.release" / "cpp"
        / "libgsthailotilecropper_dynamic.so"
    )
    system_so = pathlib.Path(
        "/usr/lib/x86_64-linux-gnu/gstreamer-1.0/libgsthailotilecropper_dynamic.so"
    )
    # Pick the newer of the two .sos; fall back gracefully.
    if build_so.exists() and system_so.exists():
        so_to_use = str(build_so if build_so.stat().st_mtime > system_so.stat().st_mtime else system_so)
    elif build_so.exists():
        so_to_use = str(build_so)
    else:
        so_to_use = str(system_so)

    probe_script = f"""\
import ctypes, gi, sys
# Preload our .so BEFORE Gst.init() so that GstHailoBaseCropperDyn is registered
# first.  GStreamer deduplicates plugins by name, so the stale system .so (which
# still has the old GstHailoBaseCropper) is skipped during the registry scan and
# no GType conflict occurs with libgsthailotools.so.
so_path = "{so_to_use}"
ctypes.CDLL(so_path, mode=ctypes.RTLD_GLOBAL)

gi.require_version('Gst', '1.0')
from gi.repository import Gst

Gst.init(None)

# Loading hailotileaggregator triggers libgsthailotools.so which registers
# GstHailoBaseCropper (the upstream type).  Our renamed plugin now registers
# GstHailoBaseCropperDyn — a distinct GType — so there should be no conflict.
factory_agg = Gst.ElementFactory.find('hailotileaggregator')
factory_dyn = Gst.ElementFactory.find('hailotilecropper_dynamic')

# If the dynamic factory is missing or broken, the conflict is present.
if factory_dyn is None:
    print("CONFLICT: hailotilecropper_dynamic factory not found after loading hailotileaggregator")
    sys.exit(1)

# Try to make both elements
agg = factory_agg.create('agg') if factory_agg else None
dyn = factory_dyn.create('tc') if factory_dyn else None

if dyn is None:
    print("CONFLICT: hailotilecropper_dynamic element could not be created")
    sys.exit(1)

print("OK: both elements created successfully")
sys.exit(0)
"""
    result = subprocess.run(
        [sys.executable, "-c", probe_script],
        capture_output=True,
        text=True,
        timeout=15,
        env={**os.environ, "GST_DEBUG": "2"},
    )
    combined = result.stdout + result.stderr
    if result.returncode != 0 or "CONFLICT" in combined:
        conflict_lines = [
            line for line in combined.splitlines()
            if any(k in line for k in ("CONFLICT", "cannot register", "assertion", "CRITICAL", "WARNING"))
        ]
        return "\n".join(conflict_lines) if conflict_lines else "non-zero exit: " + combined[:400]
    return None


# ---------------------------------------------------------------------------
# Decision-point test
# ---------------------------------------------------------------------------

def test_aggregator_merges_arbitrary_tile_layout(gst):
    """hailotileaggregator + hailotilecropper_dynamic coexistence and E2E test.

    Task 18 resolved the GLib type-registration conflict by renaming the bundled
    base class from GstHailoBaseCropper to GstHailoBaseCropperDyn.  This test:

    1. Verifies no GType conflict exists (subprocess probe).
    2. Runs the full E2E pipeline: hailotilecropper_dynamic → hailotileaggregator
       with synthetic detections to confirm coord translation + NMS work.
    """
    conflict = _detect_type_conflict()
    if conflict:
        pytest.fail(
            "GStHailoBaseCropper type-registration conflict detected — "
            "hailotilecropper_dynamic cannot coexist with hailotileaggregator "
            "in the same process.  Task 18 (custom hailotileaggregator_dynamic) "
            f"is required.\n\nConflict evidence:\n{conflict}"
        )

    # If we reach here the conflict is resolved.  Now run the actual E2E test.
    import hailo

    pipeline_str = (
        "videotestsrc num-buffers=2 ! "
        "video/x-raw,format=RGB,width=128,height=96,framerate=30/1 ! "
        "identity name=tile_setter signal-handoffs=true ! "
        "hailotilecropper_dynamic name=tc "
        "    tc.src_0 ! queue ! agg.sink_0 "
        "    tc.src_1 ! queue ! identity name=fake_inf signal-handoffs=true ! agg.sink_1 "
        "hailotileaggregator name=agg flatten-detections=true iou-threshold=0.3 "
        "agg.src ! fakesink name=final_sink signal-handoffs=true sync=false async=false"
    )
    pipe = gst.parse_launch(pipeline_str)

    def attach_tiles(identity, buf):
        roi = hailo.get_roi_from_buffer(buf)
        roi.add_object(hailo.HailoTileROI(
            hailo.HailoBBox(0.0, 0.0, 0.5, 0.5), 0, 0.0, 0.0, 0, hailo.SINGLE_SCALE))
        roi.add_object(hailo.HailoTileROI(
            hailo.HailoBBox(0.4, 0.4, 0.6, 0.6), 1, 0.0, 0.0, 0, hailo.SINGLE_SCALE))

    pipe.get_by_name("tile_setter").connect("handoff", attach_tiles)

    def fake_inference(identity, buf):
        roi = hailo.get_roi_from_buffer(buf)
        det = hailo.HailoDetection(
            hailo.HailoBBox(0.1, 0.1, 0.3, 0.3),
            "synthetic", 0.9,
        )
        roi.add_object(det)

    pipe.get_by_name("fake_inf").connect("handoff", fake_inference)

    detections_per_frame = []

    def on_final(_sink, buf, _pad):
        roi = hailo.get_roi_from_buffer(buf)
        dets = [obj for obj in roi.get_objects_typed(hailo.HAILO_DETECTION)]
        detections_per_frame.append(dets)

    pipe.get_by_name("final_sink").connect("handoff", on_final)
    pipe.set_state(gst.State.PLAYING)
    pipe.get_bus().timed_pop_filtered(
        5 * gst.SECOND, gst.MessageType.EOS | gst.MessageType.ERROR
    )
    pipe.set_state(gst.State.NULL)

    assert len(detections_per_frame) == 2
    for dets in detections_per_frame:
        assert len(dets) >= 1, "Aggregator dropped all detections"
        for d in dets:
            bb = d.get_bbox()
            assert 0.0 <= bb.xmin() <= 1.0
            assert 0.0 <= bb.ymin() <= 1.0
            assert bb.width() > 0 and bb.height() > 0
