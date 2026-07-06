/**
 * Copyright (c) 2026 Hailo Technologies Ltd. All rights reserved.
 * Distributed under the LGPL license.
 *
 * hailovampire_overlay - GStreamer element that paints "vampire"-tagged
 * detection mask regions with pixels from a shared-memory background
 * buffer maintained by an external BackgroundService.
 **/
#include <gst/gst.h>
#include <gst/video/video.h>
#include <memory>
#include <opencv2/core.hpp>
#include "gsthailovampire_overlay.hpp"
#include "bg_shm_reader.hpp"
#include "gst_hailo_meta.hpp"
#include "hailo_common.hpp"
#include "vampire_draw.hpp"

/* ---------------------------------------------------------------------------
 * File-static shared-memory readers (s_ prefix = file-static convention).
 *
 * Known limitation: file-static state means only one element instance is
 * supported per process. If multi-instance support becomes a concern, move
 * these into the GObject struct (_GstHailoVampireOverlay) in a future task.
 * ---------------------------------------------------------------------------*/
static std::unique_ptr<BgShmReader> s_bg_a;
static std::unique_ptr<BgShmReader> s_bg_b;
static std::unique_ptr<BgShmReader> s_idx;

GST_DEBUG_CATEGORY_STATIC(gst_hailovampire_overlay_debug_category);
#define GST_CAT_DEFAULT gst_hailovampire_overlay_debug_category

/* prototypes */

static void gst_hailovampire_overlay_set_property(GObject *object,
                                                   guint property_id,
                                                   const GValue *value,
                                                   GParamSpec *pspec);
static void gst_hailovampire_overlay_get_property(GObject *object,
                                                   guint property_id,
                                                   GValue *value,
                                                   GParamSpec *pspec);
static void gst_hailovampire_overlay_finalize(GObject *object);

static gboolean gst_hailovampire_overlay_stop(GstBaseTransform *trans);
static GstFlowReturn gst_hailovampire_overlay_transform_ip(GstBaseTransform *trans,
                                                            GstBuffer *buffer);

/* class boilerplate */

G_DEFINE_TYPE_WITH_CODE(GstHailoVampireOverlay, gst_hailovampire_overlay,
                        GST_TYPE_BASE_TRANSFORM,
                        GST_DEBUG_CATEGORY_INIT(gst_hailovampire_overlay_debug_category,
                                                "hailovampire_overlay", 0,
                                                "debug category for hailovampire_overlay element"));

enum
{
    PROP_0,
    PROP_BG_SHM_A_NAME,
    PROP_BG_SHM_B_NAME,
    PROP_BG_IDX_SHM_NAME,
    PROP_BG_WIDTH,
    PROP_BG_HEIGHT,
    PROP_VAMPIRE_CLASSIFICATION_TYPE,
    PROP_DILATE_RADIUS,
    PROP_DILATE_ITERATIONS,
};

static GstStaticPadTemplate sink_template =
    GST_STATIC_PAD_TEMPLATE("sink",
                            GST_PAD_SINK,
                            GST_PAD_ALWAYS,
                            GST_STATIC_CAPS("video/x-raw,format=RGB,"
                                            "width=[1," G_STRINGIFY(G_MAXINT) "],"
                                            "height=[1," G_STRINGIFY(G_MAXINT) "]"));

static GstStaticPadTemplate src_template =
    GST_STATIC_PAD_TEMPLATE("src",
                            GST_PAD_SRC,
                            GST_PAD_ALWAYS,
                            GST_STATIC_CAPS("video/x-raw,format=RGB,"
                                            "width=[1," G_STRINGIFY(G_MAXINT) "],"
                                            "height=[1," G_STRINGIFY(G_MAXINT) "]"));

static void
gst_hailovampire_overlay_class_init(GstHailoVampireOverlayClass *klass)
{
    GObjectClass *gobject_class = G_OBJECT_CLASS(klass);
    GstBaseTransformClass *base_transform_class = GST_BASE_TRANSFORM_CLASS(klass);

    gst_element_class_add_static_pad_template(GST_ELEMENT_CLASS(klass), &sink_template);
    gst_element_class_add_static_pad_template(GST_ELEMENT_CLASS(klass), &src_template);

    gst_element_class_set_static_metadata(GST_ELEMENT_CLASS(klass),
                                          "hailovampire_overlay",
                                          "Filter/Effect/Video",
                                          "Paints vampire pixels with corresponding region of a "
                                          "shared-memory background buffer",
                                          "hailo.ai <contact@hailo.ai>");

    gobject_class->set_property = gst_hailovampire_overlay_set_property;
    gobject_class->get_property = gst_hailovampire_overlay_get_property;
    gobject_class->finalize     = gst_hailovampire_overlay_finalize;

    base_transform_class->stop        = GST_DEBUG_FUNCPTR(gst_hailovampire_overlay_stop);
    base_transform_class->transform_ip =
        GST_DEBUG_FUNCPTR(gst_hailovampire_overlay_transform_ip);

    /* Shared-memory buffer names */
    g_object_class_install_property(gobject_class, PROP_BG_SHM_A_NAME,
        g_param_spec_string("bg-shm-a-name", "bg-shm-a-name",
                            "POSIX shared-memory name for background buffer A (empty = pass-through).",
                            "",
                            (GParamFlags)(GST_PARAM_MUTABLE_READY | G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS)));

    g_object_class_install_property(gobject_class, PROP_BG_SHM_B_NAME,
        g_param_spec_string("bg-shm-b-name", "bg-shm-b-name",
                            "POSIX shared-memory name for background buffer B (empty = pass-through).",
                            "",
                            (GParamFlags)(GST_PARAM_MUTABLE_READY | G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS)));

    g_object_class_install_property(gobject_class, PROP_BG_IDX_SHM_NAME,
        g_param_spec_string("bg-idx-shm-name", "bg-idx-shm-name",
                            "POSIX shared-memory name for the active-buffer index byte.",
                            "",
                            (GParamFlags)(GST_PARAM_MUTABLE_READY | G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS)));

    /* Background dimensions */
    g_object_class_install_property(gobject_class, PROP_BG_WIDTH,
        g_param_spec_int("bg-width", "bg-width",
                         "Width of the background shared-memory buffer in pixels. 0 = unconfigured.",
                         0, G_MAXINT, 0,
                         (GParamFlags)(GST_PARAM_MUTABLE_READY | G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS)));

    g_object_class_install_property(gobject_class, PROP_BG_HEIGHT,
        g_param_spec_int("bg-height", "bg-height",
                         "Height of the background shared-memory buffer in pixels. 0 = unconfigured.",
                         0, G_MAXINT, 0,
                         (GParamFlags)(GST_PARAM_MUTABLE_READY | G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS)));

    /* Classification type tag */
    g_object_class_install_property(gobject_class, PROP_VAMPIRE_CLASSIFICATION_TYPE,
        g_param_spec_string("vampire-classification-type", "vampire-classification-type",
                            "Classification type tag used to identify vampire detections. Default: \"vampire\".",
                            "vampire",
                            (GParamFlags)(GST_PARAM_MUTABLE_READY | G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS)));

    /* Mask dilation */
    g_object_class_install_property(gobject_class, PROP_DILATE_RADIUS,
        g_param_spec_int("dilate-radius", "dilate-radius",
                         "Radius (in pixels) of the dilation kernel applied to the vampire mask. Default: 15.",
                         0, G_MAXINT, 15,
                         (GParamFlags)(GST_PARAM_MUTABLE_READY | G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS)));

    g_object_class_install_property(gobject_class, PROP_DILATE_ITERATIONS,
        g_param_spec_int("dilate-iterations", "dilate-iterations",
                         "Number of dilation iterations applied to the vampire mask. Default: 2.",
                         0, G_MAXINT, 2,
                         (GParamFlags)(GST_PARAM_MUTABLE_READY | G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS)));
}

static void
gst_hailovampire_overlay_init(GstHailoVampireOverlay *self)
{
    /* String properties */
    self->bg_shm_a_name              = g_strdup("");
    self->bg_shm_b_name              = g_strdup("");
    self->bg_idx_shm_name            = g_strdup("");
    self->vampire_classification_type = g_strdup("vampire");

    /* Integer properties */
    self->bg_width         = 0;
    self->bg_height        = 0;
    self->dilate_radius    = 15;
    self->dilate_iterations = 2;

    /* Internal state */
    self->bg_bytes  = 0;

    /* Ensure the element actually runs transform_ip (not passthrough mode) */
    gst_base_transform_set_passthrough(GST_BASE_TRANSFORM(self), FALSE);
    gst_base_transform_set_in_place(GST_BASE_TRANSFORM(self), TRUE);
}

static void
gst_hailovampire_overlay_set_property(GObject *object, guint property_id,
                                      const GValue *value, GParamSpec *pspec)
{
    GstHailoVampireOverlay *self = GST_HAILO_VAMPIRE_OVERLAY(object);

    GST_DEBUG_OBJECT(self, "set_property");

    switch (property_id)
    {
    case PROP_BG_SHM_A_NAME:
        g_free(self->bg_shm_a_name);
        self->bg_shm_a_name = g_value_dup_string(value);
        break;
    case PROP_BG_SHM_B_NAME:
        g_free(self->bg_shm_b_name);
        self->bg_shm_b_name = g_value_dup_string(value);
        break;
    case PROP_BG_IDX_SHM_NAME:
        g_free(self->bg_idx_shm_name);
        self->bg_idx_shm_name = g_value_dup_string(value);
        break;
    case PROP_BG_WIDTH:
        self->bg_width = g_value_get_int(value);
        break;
    case PROP_BG_HEIGHT:
        self->bg_height = g_value_get_int(value);
        break;
    case PROP_VAMPIRE_CLASSIFICATION_TYPE:
        g_free(self->vampire_classification_type);
        self->vampire_classification_type = g_value_dup_string(value);
        break;
    case PROP_DILATE_RADIUS:
        self->dilate_radius = g_value_get_int(value);
        break;
    case PROP_DILATE_ITERATIONS:
        self->dilate_iterations = g_value_get_int(value);
        break;
    default:
        G_OBJECT_WARN_INVALID_PROPERTY_ID(object, property_id, pspec);
        break;
    }
}

static void
gst_hailovampire_overlay_get_property(GObject *object, guint property_id,
                                      GValue *value, GParamSpec *pspec)
{
    GstHailoVampireOverlay *self = GST_HAILO_VAMPIRE_OVERLAY(object);

    GST_DEBUG_OBJECT(self, "get_property");

    switch (property_id)
    {
    case PROP_BG_SHM_A_NAME:
        g_value_set_string(value, self->bg_shm_a_name);
        break;
    case PROP_BG_SHM_B_NAME:
        g_value_set_string(value, self->bg_shm_b_name);
        break;
    case PROP_BG_IDX_SHM_NAME:
        g_value_set_string(value, self->bg_idx_shm_name);
        break;
    case PROP_BG_WIDTH:
        g_value_set_int(value, self->bg_width);
        break;
    case PROP_BG_HEIGHT:
        g_value_set_int(value, self->bg_height);
        break;
    case PROP_VAMPIRE_CLASSIFICATION_TYPE:
        g_value_set_string(value, self->vampire_classification_type);
        break;
    case PROP_DILATE_RADIUS:
        g_value_set_int(value, self->dilate_radius);
        break;
    case PROP_DILATE_ITERATIONS:
        g_value_set_int(value, self->dilate_iterations);
        break;
    default:
        G_OBJECT_WARN_INVALID_PROPERTY_ID(object, property_id, pspec);
        break;
    }
}

static void
gst_hailovampire_overlay_finalize(GObject *object)
{
    GstHailoVampireOverlay *self = GST_HAILO_VAMPIRE_OVERLAY(object);

    GST_DEBUG_OBJECT(self, "finalize");

    g_free(self->bg_shm_a_name);
    g_free(self->bg_shm_b_name);
    g_free(self->bg_idx_shm_name);
    g_free(self->vampire_classification_type);

    G_OBJECT_CLASS(gst_hailovampire_overlay_parent_class)->finalize(object);
}

static gboolean
gst_hailovampire_overlay_stop(GstBaseTransform *trans)
{
    GstHailoVampireOverlay *self = GST_HAILO_VAMPIRE_OVERLAY(trans);
    GST_DEBUG_OBJECT(self, "stop: releasing bg shm mappings");
    s_bg_a.reset();
    s_bg_b.reset();
    s_idx.reset();
    return TRUE;
}

static bool
ensure_shm_open(GstHailoVampireOverlay *self)
{
    if (s_bg_a && s_bg_b && s_idx) return true;

    const bool any_name_empty =
        (!self->bg_shm_a_name || self->bg_shm_a_name[0] == '\0') ||
        (!self->bg_shm_b_name || self->bg_shm_b_name[0] == '\0') ||
        (!self->bg_idx_shm_name || self->bg_idx_shm_name[0] == '\0');
    if (any_name_empty) {
        GST_DEBUG_OBJECT(self,
            "bg-shm-*-name properties not set; element is pass-through");
        return false;
    }
    static bool warned_dims = false;
    if (self->bg_width <= 0 || self->bg_height <= 0) {
        if (!warned_dims) {
            GST_ERROR_OBJECT(self,
                "bg-width and bg-height must be > 0 (got %dx%d)",
                self->bg_width, self->bg_height);
            warned_dims = true;
        }
        return false;
    }

    const std::size_t bg_bytes =
        (std::size_t)self->bg_width * self->bg_height * 3;
    try {
        s_bg_a = std::make_unique<BgShmReader>(self->bg_shm_a_name, bg_bytes);
        s_bg_b = std::make_unique<BgShmReader>(self->bg_shm_b_name, bg_bytes);
        s_idx  = std::make_unique<BgShmReader>(self->bg_idx_shm_name, 1);
        self->bg_bytes = bg_bytes;
        GST_INFO_OBJECT(self,
            "Opened bg shm: a=%s b=%s idx=%s (%zu bytes)",
            self->bg_shm_a_name, self->bg_shm_b_name,
            self->bg_idx_shm_name, bg_bytes);
    } catch (const std::exception &e) {
        GST_ERROR_OBJECT(self, "Failed to open bg shm: %s", e.what());
        // Reset on partial failure so a later configure attempt can retry.
        s_bg_a.reset();
        s_bg_b.reset();
        s_idx.reset();
        return false;
    }
    return true;
}

static GstFlowReturn
gst_hailovampire_overlay_transform_ip(GstBaseTransform *trans, GstBuffer *buffer)
{
    GstHailoVampireOverlay *self = GST_HAILO_VAMPIRE_OVERLAY(trans);
    if (!ensure_shm_open(self)) {
        return GST_FLOW_OK;
    }

    GstCaps *caps = gst_pad_get_current_caps(trans->sinkpad);
    if (!caps) {
        return GST_FLOW_OK;
    }
    GstVideoInfo info;
    gst_video_info_init(&info);
    const bool caps_ok = gst_video_info_from_caps(&info, caps);
    gst_caps_unref(caps);
    if (!caps_ok) return GST_FLOW_OK;

    const int frame_w = GST_VIDEO_INFO_WIDTH(&info);
    const int frame_h = GST_VIDEO_INFO_HEIGHT(&info);

    // The background buffer must match the frame dimensions exactly.
    if (frame_w != self->bg_width || frame_h != self->bg_height) {
        GST_WARNING_OBJECT(self,
            "Frame %dx%d != bg %dx%d; skipping vampire draw",
            frame_w, frame_h, self->bg_width, self->bg_height);
        return GST_FLOW_OK;
    }

    GstMapInfo map;
    if (!gst_buffer_map(buffer, &map, GST_MAP_READWRITE)) {
        return GST_FLOW_OK;
    }

    cv::Mat frame(frame_h, frame_w, CV_8UC3, map.data,
                  GST_VIDEO_INFO_PLANE_STRIDE(&info, 0));

    const uint8_t current_idx = s_idx->data()[0];
    const uint8_t *bg_data = (current_idx == 0) ? s_bg_a->data() : s_bg_b->data();
    cv::Mat bg(self->bg_height, self->bg_width, CV_8UC3,
               const_cast<uint8_t*>(bg_data));

    VampireDrawParams params{};
    params.bg = &bg;
    params.vampire_classification_type =
        self->vampire_classification_type ? self->vampire_classification_type : "vampire";
    params.dilate_radius = self->dilate_radius;
    params.dilate_iterations = self->dilate_iterations;

    HailoROIPtr roi = get_hailo_main_roi(buffer, true);
    if (roi) {
        const int drawn = draw_vampires(frame, roi, params);
        GST_LOG_OBJECT(self, "draw_vampires: %d detections drawn", drawn);
    }

    gst_buffer_unmap(buffer, &map);
    return GST_FLOW_OK;
}

/* Plugin registration */
static gboolean
plugin_init(GstPlugin *plugin)
{
    return gst_element_register(plugin, "hailovampire_overlay",
                                GST_RANK_NONE, GST_TYPE_HAILO_VAMPIRE_OVERLAY);
}

GST_PLUGIN_DEFINE(
    GST_VERSION_MAJOR,
    GST_VERSION_MINOR,
    hailovampire_overlay,
    "Vampire-effect overlay reading background pixels from shared memory",
    plugin_init,
    "1.0",
    "LGPL",
    "hailo-apps-infra",
    "https://github.com/hailo-ai/hailo-apps-infra")
