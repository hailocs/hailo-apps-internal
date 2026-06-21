#define CATCH_CONFIG_MAIN
#include <catch2/catch.hpp>
#include <gst/gst.h>
#include <gst/check/gstharness.h>

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

TEST_CASE("no tiles -> zero crop-pad outputs, one bypass output")
{
    register_once();
    GstHarness *h_main = gst_harness_new_with_padnames(
        "hailotilecropper_dynamic", "sink", "src_0");
    GstHarness *h_crop = gst_harness_new_with_element(
        h_main->element, nullptr, "src_1");

    gst_harness_set_src_caps_str(h_main,
        "video/x-raw,format=RGB,width=64,height=48,framerate=30/1");

    GstBuffer *buf = gst_harness_create_buffer(h_main, 64 * 48 * 3);
    REQUIRE(gst_harness_push(h_main, buf) == GST_FLOW_OK);

    REQUIRE(gst_harness_buffers_received(h_main) == 1);  /* bypass */
    REQUIRE(gst_harness_buffers_received(h_crop) == 0);  /* no tiles */

    gst_harness_teardown(h_crop);
    gst_harness_teardown(h_main);
}
