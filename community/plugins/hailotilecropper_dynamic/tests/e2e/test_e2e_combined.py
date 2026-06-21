"""E2E: dynamic tiles from upstream + static tiles from property — both used."""
import hailo


def test_combined_static_plus_dynamic(gst):
    pipe = gst.parse_launch(
        "videotestsrc num-buffers=4 ! "
        "video/x-raw,format=RGB,width=64,height=48,framerate=30/1 ! "
        "identity name=tile_setter signal-handoffs=true ! "
        "hailotilecropper_dynamic name=tc "
        "tiles-static=\"0.0,0.0,1.0,1.0;0.25,0.25,0.5,0.5\" "
        "tc.src_0 ! fakesink sync=false async=false "
        "tc.src_1 ! fakesink name=crop_sink signal-handoffs=true sync=false async=false"
    )
    crop_count = [0]
    pipe.get_by_name("crop_sink").connect(
        "handoff", lambda sink, buf, pad: crop_count.__setitem__(0, crop_count[0] + 1)
    )

    def attach_one_dynamic(identity, buf):
        roi = hailo.get_roi_from_buffer(buf)
        roi.add_object(hailo.HailoTileROI(
            hailo.HailoBBox(0.0, 0.0, 0.5, 0.5),
            99, 0.0, 0.0, 0, hailo.SINGLE_SCALE,
        ))

    pipe.get_by_name("tile_setter").connect("handoff", attach_one_dynamic)

    pipe.set_state(gst.State.PLAYING)
    pipe.get_bus().timed_pop_filtered(
        5 * gst.SECOND, gst.MessageType.EOS | gst.MessageType.ERROR
    )
    pipe.set_state(gst.State.NULL)
    # 1 dynamic + 2 static = 3 tiles per frame × 4 frames = 12
    assert crop_count[0] == 12
