#define CATCH_CONFIG_MAIN
#include <catch2/catch.hpp>
#include <gst/gst.h>
#include <gst/check/gstharness.h>
#include "gst_hailo_meta.hpp"
#include "hailo_objects.hpp"
#include "gsthailotilecropper_dynamic.hpp"

static void register_once()
{
    static gsize once = 0;
    if (g_once_init_enter(&once)) {
        gst_init(nullptr, nullptr);
        gst_element_register(nullptr, "hailotilecropper_dynamic",
                             GST_RANK_PRIMARY, GST_TYPE_HAILO_TILE_CROPPER_DYNAMIC);
        g_once_init_leave(&once, 1);
    }
}

TEST_CASE("static tiles -> N crop-pad outputs per buffer; HailoTileROI attached to bypass")
{
    register_once();
    GstHarness *h_main = gst_harness_new_with_padnames(
        "hailotilecropper_dynamic", "sink", "src_0");
    GstHarness *h_crop = gst_harness_new_with_element(
        h_main->element, nullptr, "src_1");

    g_object_set(h_main->element,
                 "tiles-static", "0.0,0.0,0.5,1.0;0.5,0.0,0.5,1.0",
                 nullptr);
    gst_harness_set_src_caps_str(h_main,
        "video/x-raw,format=RGB,width=64,height=48,framerate=30/1");

    GstBuffer *buf = gst_harness_create_buffer(h_main, 64 * 48 * 3);
    REQUIRE(gst_harness_push(h_main, buf) == GST_FLOW_OK);

    REQUIRE(gst_harness_buffers_received(h_main) == 1);
    REQUIRE(gst_harness_buffers_received(h_crop) == 2);

    GstBuffer *out = gst_harness_pull(h_main);
    HailoROIPtr roi = get_hailo_main_roi(out, /*create=*/false);
    REQUIRE(roi != nullptr);
    REQUIRE(roi->get_objects_typed(HAILO_TILE).size() == 2);
    gst_buffer_unref(out);

    gst_harness_teardown(h_crop);
    gst_harness_teardown(h_main);
}

TEST_CASE("malformed static-tiles string is silently skipped (with WARNING)")
{
    register_once();
    GstHarness *h_main = gst_harness_new_with_padnames(
        "hailotilecropper_dynamic", "sink", "src_0");
    GstHarness *h_crop = gst_harness_new_with_element(
        h_main->element, nullptr, "src_1");

    /* "not,a,tile" -> unparseable; "1.5,0.0,0.4,0.4" -> out-of-range x.
     * Both should be rejected (with WARNING). The two valid ones survive. */
    g_object_set(h_main->element,
                 "tiles-static", "0.0,0.0,1.0,1.0;not,a,tile;1.5,0.0,0.4,0.4;0.1,0.1,0.4,0.4",
                 nullptr);
    gst_harness_set_src_caps_str(h_main,
        "video/x-raw,format=RGB,width=32,height=32,framerate=30/1");

    GstBuffer *buf = gst_harness_create_buffer(h_main, 32 * 32 * 3);
    REQUIRE(gst_harness_push(h_main, buf) == GST_FLOW_OK);

    /* 2 valid tiles => 2 crops; malformed and out-of-range are dropped. */
    REQUIRE(gst_harness_buffers_received(h_crop) == 2);

    gst_harness_teardown(h_crop);
    gst_harness_teardown(h_main);
}
