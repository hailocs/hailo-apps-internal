"""E2E: no tiles configured anywhere → crop pad receives zero buffers."""
import pytest


def _run_pipeline(gst, pipeline_str, expected_main, expected_crop):
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
    assert msg is not None and msg.type == gst.MessageType.EOS, "Pipeline did not reach EOS"
    assert main_count[0] == expected_main
    assert crop_count[0] == expected_crop


def test_no_tiles_bypass_only(gst):
    _run_pipeline(
        gst,
        pipeline_str=(
            "videotestsrc num-buffers=10 ! "
            "video/x-raw,format=RGB,width=64,height=48,framerate=30/1 ! "
            "hailotilecropper_dynamic name=tc tiles-static=\"\" "
            "tc.src_0 ! fakesink name=main_sink signal-handoffs=true sync=false "
            "tc.src_1 ! fakesink name=crop_sink signal-handoffs=true sync=false async=false"
        ),
        expected_main=10,
        expected_crop=0,
    )
