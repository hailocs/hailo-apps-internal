"""E2E: tiles attached upstream via the identity element's handoff signal.

Mirrors the production pattern: an application callback (running inside
hailofilter or equivalent) decides what to crop and attaches HailoTileROI
objects to each buffer's main ROI before the buffer reaches the cropper.

Implementation note
-------------------
Python pad probes (Gst.PadProbeType.BUFFER) receive a non-writable GstBuffer
reference: GStreamer's PadProbeInfo holds an extra ref, so the buffer refcount
is > 1 and gst_buffer_add_hailo_meta() refuses to add meta to it.  The
``identity signal-handoffs=true`` pattern avoids this: the ``handoff`` signal
fires while the buffer is being processed inside the identity chain function,
where the refcount is 1 and the buffer is writable.
"""
import hailo


def test_dynamic_tiles_via_handoff_signal(gst):
    """4 tiles attached per frame via the identity handoff signal."""
    pipeline_str = (
        "videotestsrc num-buffers=6 ! "
        "video/x-raw,format=RGB,width=64,height=48,framerate=30/1 ! "
        "identity name=tile_setter signal-handoffs=true ! "
        "hailotilecropper_dynamic name=tc "
        "tc.src_0 ! fakesink sync=false async=false "
        "tc.src_1 ! fakesink name=crop_sink signal-handoffs=true sync=false async=false"
    )
    pipe = gst.parse_launch(pipeline_str)

    crop_count = [0]
    pipe.get_by_name("crop_sink").connect(
        "handoff",
        lambda sink, buf, pad: crop_count.__setitem__(0, crop_count[0] + 1),
    )

    def attach_tiles(identity, buf):
        roi = hailo.get_roi_from_buffer(buf)
        for i in range(4):
            tile = hailo.HailoTileROI(
                hailo.HailoBBox(0.25 * (i % 2), 0.25 * (i // 2), 0.5, 0.5),
                i, 0.0, 0.0, 0, hailo.SINGLE_SCALE,
            )
            roi.add_object(tile)

    pipe.get_by_name("tile_setter").connect("handoff", attach_tiles)

    pipe.set_state(gst.State.PLAYING)
    msg = pipe.get_bus().timed_pop_filtered(
        5 * gst.SECOND, gst.MessageType.EOS | gst.MessageType.ERROR
    )
    pipe.set_state(gst.State.NULL)
    assert msg is not None and msg.type == gst.MessageType.EOS
    assert crop_count[0] == 24  # 6 frames × 4 dynamic tiles


def test_variable_tile_count_per_frame(gst):
    """Different number of tiles per frame — simulates dynamic app behavior."""
    pipeline_str = (
        "videotestsrc num-buffers=3 ! "
        "video/x-raw,format=RGB,width=64,height=48,framerate=30/1 ! "
        "identity name=tile_setter signal-handoffs=true ! "
        "hailotilecropper_dynamic name=tc "
        "tc.src_0 ! fakesink sync=false async=false "
        "tc.src_1 ! fakesink name=crop_sink signal-handoffs=true sync=false async=false"
    )
    pipe = gst.parse_launch(pipeline_str)

    crop_count = [0]
    pipe.get_by_name("crop_sink").connect(
        "handoff",
        lambda sink, buf, pad: crop_count.__setitem__(0, crop_count[0] + 1),
    )

    frame_idx = [0]

    def attach_variable(identity, buf):
        roi = hailo.get_roi_from_buffer(buf)
        for i in range(frame_idx[0] + 1):
            tile = hailo.HailoTileROI(
                hailo.HailoBBox(0.0, 0.0, 1.0, 1.0),
                i, 0.0, 0.0, 0, hailo.SINGLE_SCALE,
            )
            roi.add_object(tile)
        frame_idx[0] += 1

    pipe.get_by_name("tile_setter").connect("handoff", attach_variable)

    pipe.set_state(gst.State.PLAYING)
    pipe.get_bus().timed_pop_filtered(
        5 * gst.SECOND, gst.MessageType.EOS | gst.MessageType.ERROR
    )
    pipe.set_state(gst.State.NULL)
    assert crop_count[0] == 1 + 2 + 3  # 6 total
