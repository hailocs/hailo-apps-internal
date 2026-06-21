"""E2E: tiling-mode property + per-tile mode override in tiles-static.

Covers:
* `tiling-mode` is a GEnum {single-scale, multi-scale} with single-scale default.
* Property is readable/writable via the GObject API and accepts both nick
  ("single-scale" / "multi-scale") and integer (0 / 1) forms.
* The optional 5th field per tile in `tiles-static` overrides the cropper's
  `tiling-mode` for that tile only; omitted ⇒ inherit the cropper default.
* Invalid mode tokens emit a warning but the tile inherits the default
  (parse-error path), and pipelines still produce the expected number of crops.
* Pipelines with mode-tagged tiles produce the right number of crop buffers
  (so the parser correctly skips the 5th field and doesn't drop tiles).
"""
import pytest


def _count_crops(gst, pipeline_str, num_buffers, expected_crops):
    pipe = gst.parse_launch(pipeline_str)
    crop_sink = pipe.get_by_name("crop_sink")
    crop_count = [0]
    crop_sink.connect("handoff", lambda *a: crop_count.__setitem__(0, crop_count[0] + 1))
    pipe.set_state(gst.State.PLAYING)
    msg = pipe.get_bus().timed_pop_filtered(
        5 * gst.SECOND, gst.MessageType.EOS | gst.MessageType.ERROR
    )
    pipe.set_state(gst.State.NULL)
    assert msg is not None and msg.type == gst.MessageType.EOS, \
        f"pipeline error or timeout: {msg}"
    assert crop_count[0] == expected_crops, (
        f"expected {expected_crops} crops, got {crop_count[0]}"
    )


def test_tiling_mode_default_is_single_scale(gst):
    """Without setting the property the default is 'single-scale' (= 0)."""
    pipe = gst.parse_launch(
        "videotestsrc num-buffers=1 ! "
        "video/x-raw,format=RGB,width=32,height=32,framerate=30/1 ! "
        "hailotilecropper_dynamic name=tc "
        "tc.src_0 ! fakesink sync=false "
        "tc.src_1 ! fakesink sync=false async=false"
    )
    tc = pipe.get_by_name("tc")
    # Enum nick string round-trip
    assert tc.get_property("tiling-mode").value_nick == "single-scale"
    # Integer round-trip (GEnum exposes both)
    assert int(tc.get_property("tiling-mode")) == 0


def test_tiling_mode_set_get_round_trip(gst):
    """Property accepts nick string and integer; both readbacks match."""
    pipe = gst.parse_launch(
        "videotestsrc num-buffers=1 ! "
        "video/x-raw,format=RGB,width=32,height=32,framerate=30/1 ! "
        "hailotilecropper_dynamic name=tc "
        "tc.src_0 ! fakesink sync=false "
        "tc.src_1 ! fakesink sync=false async=false"
    )
    tc = pipe.get_by_name("tc")

    tc.set_property("tiling-mode", "multi-scale")
    assert tc.get_property("tiling-mode").value_nick == "multi-scale"
    assert int(tc.get_property("tiling-mode")) == 1

    tc.set_property("tiling-mode", 0)
    assert tc.get_property("tiling-mode").value_nick == "single-scale"


def test_tiles_static_with_per_tile_mode_overrides(gst):
    """4-field rects + 5-field rects (with mode 'm'/'s') in one tiles-static string.

    Parser must accept all three forms and produce one crop per tile:
      - bare         "0.0,0.0,0.5,1.0"
      - explicit 's' "0.5,0.0,0.25,1.0,s"
      - explicit 'm' "0.75,0.0,0.25,1.0,m"
    """
    _count_crops(gst,
        "videotestsrc num-buffers=3 ! "
        "video/x-raw,format=RGB,width=64,height=32,framerate=30/1 ! "
        "hailotilecropper_dynamic name=tc tiling-mode=single-scale "
        "tiles-static=\"0.0,0.0,0.5,1.0;0.5,0.0,0.25,1.0,s;0.75,0.0,0.25,1.0,m\" "
        "tc.src_0 ! fakesink sync=false "
        "tc.src_1 ! fakesink name=crop_sink signal-handoffs=true sync=false async=false",
        num_buffers=3, expected_crops=3 * 3,
    )


def test_tiles_static_alternate_mode_spellings(gst):
    """Parser accepts the long names + integer 0/1, not just 'm'/'s'."""
    _count_crops(gst,
        "videotestsrc num-buffers=2 ! "
        "video/x-raw,format=RGB,width=64,height=32,framerate=30/1 ! "
        "hailotilecropper_dynamic name=tc "
        "tiles-static=\""
            "0.0,0.0,0.25,1.0,multi-scale;"
            "0.25,0.0,0.25,1.0,single-scale;"
            "0.5,0.0,0.25,1.0,1;"
            "0.75,0.0,0.25,1.0,0\" "
        "tc.src_0 ! fakesink sync=false "
        "tc.src_1 ! fakesink name=crop_sink signal-handoffs=true sync=false async=false",
        num_buffers=2, expected_crops=2 * 4,
    )


def test_tiles_static_unknown_mode_falls_back_to_default(gst):
    """An unrecognized mode token is logged as a warning, the tile is still
    emitted (it just inherits the cropper-level default). The buffer count
    must not regress."""
    _count_crops(gst,
        "videotestsrc num-buffers=2 ! "
        "video/x-raw,format=RGB,width=64,height=32,framerate=30/1 ! "
        "hailotilecropper_dynamic name=tc "
        "tiles-static=\"0.0,0.0,0.5,1.0,bogus;0.5,0.0,0.5,1.0\" "
        "tc.src_0 ! fakesink sync=false "
        "tc.src_1 ! fakesink name=crop_sink signal-handoffs=true sync=false async=false",
        num_buffers=2, expected_crops=2 * 2,
    )


def test_tiles_static_trailing_field_rejects_tile(gst):
    """A 6-field tile entry (extra trailing field after mode) is malformed and
    dropped; the surviving valid tile is kept."""
    _count_crops(gst,
        "videotestsrc num-buffers=2 ! "
        "video/x-raw,format=RGB,width=64,height=32,framerate=30/1 ! "
        "hailotilecropper_dynamic name=tc "
        "tiles-static=\"0.0,0.0,0.5,1.0,s,extra;0.5,0.0,0.5,1.0\" "
        "tc.src_0 ! fakesink sync=false "
        "tc.src_1 ! fakesink name=crop_sink signal-handoffs=true sync=false async=false",
        num_buffers=2, expected_crops=2 * 1,
    )


def test_tile_mode_propagates_to_hailo_tile_roi(gst):
    """Verify the mode in the parsed tiles-static actually reaches the
    HailoTileROI objects attached to the buffer.

    We pull the main ROI off the buffer in a pad probe on src_0 (which still
    sees the per-buffer metadata flattened by the aggregator), and assert
    that the two HailoTile children carry the requested modes.
    """
    import hailo

    captured = {"modes": None}

    def probe(pad, info):
        buf = info.get_buffer()
        if buf is None:
            return gst.PadProbeReturn.OK
        roi = hailo.get_roi_from_buffer(buf)
        tiles = roi.get_objects_typed(hailo.HAILO_TILE)
        # Sort tiles by xmin so we have a deterministic order regardless
        # of how the cropper enqueued them.
        tiles_sorted = sorted(tiles, key=lambda t: t.get_bbox().xmin())
        captured["modes"] = [int(t.mode()) for t in tiles_sorted]
        return gst.PadProbeReturn.OK

    pipe = gst.parse_launch(
        "videotestsrc num-buffers=1 ! "
        "video/x-raw,format=RGB,width=32,height=32,framerate=30/1 ! "
        "hailotilecropper_dynamic name=tc tiling-mode=single-scale "
        "tiles-static=\"0.0,0.0,0.5,1.0,m;0.5,0.0,0.5,1.0,s\" "
        "tc.src_0 ! fakesink name=main_sink sync=false async=false "
        "tc.src_1 ! fakesink sync=false async=false"
    )
    main_sink = pipe.get_by_name("main_sink")
    main_sink.get_static_pad("sink").add_probe(gst.PadProbeType.BUFFER, probe)
    pipe.set_state(gst.State.PLAYING)
    msg = pipe.get_bus().timed_pop_filtered(
        5 * gst.SECOND, gst.MessageType.EOS | gst.MessageType.ERROR
    )
    pipe.set_state(gst.State.NULL)
    assert msg is not None and msg.type == gst.MessageType.EOS

    # SINGLE_SCALE = 0, MULTI_SCALE = 1 in hailo_objects.hpp
    SINGLE_SCALE, MULTI_SCALE = 0, 1
    assert captured["modes"] == [MULTI_SCALE, SINGLE_SCALE], (
        f"expected [MULTI_SCALE, SINGLE_SCALE], got {captured['modes']}"
    )


def test_cropper_default_applies_when_per_tile_mode_omitted(gst):
    """When tiles-static rect omits the 5th field, the tile inherits the
    cropper-level tiling-mode property. Setting cropper to multi-scale
    must make the bare tile carry MULTI_SCALE."""
    import hailo

    captured = {"modes": None}

    def probe(pad, info):
        buf = info.get_buffer()
        if buf is None:
            return gst.PadProbeReturn.OK
        roi = hailo.get_roi_from_buffer(buf)
        tiles = roi.get_objects_typed(hailo.HAILO_TILE)
        tiles_sorted = sorted(tiles, key=lambda t: t.get_bbox().xmin())
        captured["modes"] = [int(t.mode()) for t in tiles_sorted]
        return gst.PadProbeReturn.OK

    pipe = gst.parse_launch(
        "videotestsrc num-buffers=1 ! "
        "video/x-raw,format=RGB,width=32,height=32,framerate=30/1 ! "
        "hailotilecropper_dynamic name=tc tiling-mode=multi-scale "
        "tiles-static=\"0.0,0.0,0.5,1.0;0.5,0.0,0.5,1.0,s\" "
        "tc.src_0 ! fakesink name=main_sink sync=false async=false "
        "tc.src_1 ! fakesink sync=false async=false"
    )
    main_sink = pipe.get_by_name("main_sink")
    main_sink.get_static_pad("sink").add_probe(gst.PadProbeType.BUFFER, probe)
    pipe.set_state(gst.State.PLAYING)
    msg = pipe.get_bus().timed_pop_filtered(
        5 * gst.SECOND, gst.MessageType.EOS | gst.MessageType.ERROR
    )
    pipe.set_state(gst.State.NULL)
    assert msg is not None and msg.type == gst.MessageType.EOS

    SINGLE_SCALE, MULTI_SCALE = 0, 1
    # First tile inherits cropper default (multi-scale), second is forced single.
    assert captured["modes"] == [MULTI_SCALE, SINGLE_SCALE], (
        f"expected [MULTI_SCALE, SINGLE_SCALE], got {captured['modes']}"
    )
