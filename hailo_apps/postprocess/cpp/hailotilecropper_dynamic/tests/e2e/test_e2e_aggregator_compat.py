"""E2E: hailotileaggregator works downstream of hailotilecropper_dynamic.

The aggregator must:
  1. Translate detection bboxes from each tile-local space → frame-global space.
  2. Cross-tile NMS dedup.

We feed a fixed test video, attach 2 non-grid tiles dynamically via the
identity-handoff pattern, emulate inference output by attaching synthetic
detections inside each tile's ROI between cropper and aggregator, then
verify the aggregator's main-pad output ROI carries detections in global
coords.

KNOWN FAILURE — Task 18 required
---------------------------------
This test FAILS with a GLib type-registration conflict:

  GLib-GObject-WARNING: cannot register existing type 'GstHailoBaseCropper'
  GStreamer-CRITICAL: gst_element_register: assertion 'g_type_is_a (type, GST_TYPE_ELEMENT)' failed

Root cause: hailotilecropper_dynamic bundles its own copy of GstHailoBaseCropper
(compiled from TAPPAS upstream source).  libgsthailotools.so (which contains
hailotileaggregator) also exports GstHailoBaseCropper.  GLib forbids registering
a GType name twice; when both shared libraries are loaded in the same process our
plugin fails to register its element type entirely, making the pipeline impossible
to construct.  Even the element creation step (Gst.ElementFactory.make) hangs
because the factory is left in a broken state.

Consequence: hailotilecropper_dynamic cannot be used in the same GStreamer process
as hailotileaggregator.  Task 18 (custom hailotileaggregator_dynamic plugin) is
therefore REQUIRED.  The new aggregator must not inherit from GstHailoBaseCropper
and must live in our own shared library.
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
    """
    probe_script = """\
import gi, sys, warnings
gi.require_version('Gst', '1.0')
from gi.repository import Gst

# Capture GLib warnings
import logging
logging.captureWarnings(True)

Gst.init(None)

# Loading hailotileaggregator triggers libgsthailotools.so which registers
# GstHailoBaseCropper.  Then querying for hailotilecropper_dynamic triggers
# our plugin which tries to register the same type again.
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

@pytest.mark.xfail(
    reason=(
        "GLib type-registration conflict: GstHailoBaseCropper is registered by "
        "both libgsthailotilecropper_dynamic.so (bundled copy) and libgsthailotools.so "
        "(hailotileaggregator's library).  The pipeline cannot be constructed.  "
        "Task 18 (custom aggregator) is required to resolve this."
    ),
    strict=True,
)
def test_aggregator_merges_arbitrary_tile_layout(gst):
    """Decision-point test: hailotileaggregator + hailotilecropper_dynamic compatibility.

    This test is marked xfail(strict=True).  It will:
    - Pass (unexpected pass → xpass → ERROR) only if the conflict is resolved.
    - Fail (expected xfail → XFAIL) while the conflict remains — documenting
      that Task 18 (custom aggregator) is required.

    The test detects the conflict via a subprocess probe to avoid hanging the
    main pytest process, then asserts no conflict exists (which will fail while
    the conflict is present, producing the expected XFAIL result).
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
