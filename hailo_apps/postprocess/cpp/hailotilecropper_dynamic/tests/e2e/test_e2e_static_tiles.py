"""E2E: static tiles configured via property → N crops per buffer."""
import pytest


def _count_buffers(gst, pipeline_str):
    pipe = gst.parse_launch(pipeline_str)
    main_sink = pipe.get_by_name("main_sink")
    crop_sink = pipe.get_by_name("crop_sink")
    main_count, crop_count = [0], [0]
    main_sink.connect("handoff", lambda *a: main_count.__setitem__(0, main_count[0] + 1))
    crop_sink.connect("handoff", lambda *a: crop_count.__setitem__(0, crop_count[0] + 1))
    pipe.set_state(gst.State.PLAYING)
    msg = pipe.get_bus().timed_pop_filtered(
        5 * gst.SECOND, gst.MessageType.EOS | gst.MessageType.ERROR
    )
    pipe.set_state(gst.State.NULL)
    assert msg is not None and msg.type == gst.MessageType.EOS
    return main_count[0], crop_count[0]


def test_two_static_tiles_split_frame_in_half(gst):
    main, crop = _count_buffers(gst,
        "videotestsrc num-buffers=5 ! "
        "video/x-raw,format=RGB,width=64,height=48,framerate=30/1 ! "
        "hailotilecropper_dynamic name=tc "
        "tiles-static=\"0.0,0.0,0.5,1.0;0.5,0.0,0.5,1.0\" "
        "tc.src_0 ! fakesink name=main_sink signal-handoffs=true sync=false async=false "
        "tc.src_1 ! fakesink name=crop_sink signal-handoffs=true sync=false async=false"
    )
    assert main == 5
    assert crop == 10  # 5 frames × 2 tiles


def test_three_overlapping_static_tiles(gst):
    main, crop = _count_buffers(gst,
        "videotestsrc num-buffers=4 ! "
        "video/x-raw,format=RGB,width=64,height=48,framerate=30/1 ! "
        "hailotilecropper_dynamic name=tc "
        "tiles-static=\"0.0,0.0,0.6,1.0;0.4,0.0,0.6,1.0;0.2,0.2,0.6,0.6\" "
        "tc.src_0 ! fakesink name=main_sink signal-handoffs=true sync=false async=false "
        "tc.src_1 ! fakesink name=crop_sink signal-handoffs=true sync=false async=false"
    )
    assert main == 4
    assert crop == 12  # 4 frames × 3 tiles


def test_property_change_at_runtime(gst):
    pipe = gst.parse_launch(
        "videotestsrc num-buffers=3 ! "
        "video/x-raw,format=RGB,width=64,height=48,framerate=30/1 ! "
        "hailotilecropper_dynamic name=tc "
        "tc.src_0 ! fakesink sync=false "
        "tc.src_1 ! fakesink sync=false async=false"
    )
    tc = pipe.get_by_name("tc")
    tc.set_property("tiles-static", "0.0,0.0,1.0,1.0")
    assert tc.get_property("tiles-static") == "0.0,0.0,1.0,1.0"
    pipe.set_state(gst.State.PLAYING)
    pipe.get_bus().timed_pop_filtered(
        5 * gst.SECOND, gst.MessageType.EOS | gst.MessageType.ERROR
    )
    pipe.set_state(gst.State.NULL)
