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

TEST_CASE("dynamic tiles pre-attached to ROI produce one crop per tile")
{
    register_once();
    GstHarness *h_main = gst_harness_new_with_padnames(
        "hailotilecropper_dynamic", "sink", "src_0");
    GstHarness *h_crop = gst_harness_new_with_element(
        h_main->element, nullptr, "src_1");

    gst_harness_set_src_caps_str(h_main,
        "video/x-raw,format=RGB,width=64,height=48,framerate=30/1");

    GstBuffer *buf = gst_harness_create_buffer(h_main, 64 * 48 * 3);

    /* Attach 3 dynamic tiles to the buffer's main ROI BEFORE pushing. */
    HailoROIPtr roi = get_hailo_main_roi(buf, /*create=*/true);
    for (int i = 0; i < 3; ++i) {
        roi->add_object(std::make_shared<HailoTileROI>(
            HailoBBox(0.1f * i, 0.1f * i, 0.3f, 0.3f),
            i, 0.0f, 0.0f, 0, SINGLE_SCALE));
    }

    REQUIRE(gst_harness_push(h_main, buf) == GST_FLOW_OK);
    REQUIRE(gst_harness_buffers_received(h_crop) == 3);

    gst_harness_teardown(h_crop);
    gst_harness_teardown(h_main);
}
