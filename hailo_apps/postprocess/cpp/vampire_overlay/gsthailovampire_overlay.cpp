/**
 * Copyright (c) 2026 Hailo Technologies Ltd. All rights reserved.
 * Distributed under the LGPL license.
 *
 * hailovampire_overlay - GStreamer element skeleton.
 * transform_ip is pass-through for Task 6; Tasks 7/8 will add shm reading
 * and vampire-mask drawing.
 **/
#include <gst/gst.h>
#include <gst/video/video.h>
#include "gsthailovampire_overlay.hpp"

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

    /* Internal state — zeroed until Tasks 7/8 populate them */
    self->bg_a_map  = nullptr;
    self->bg_b_map  = nullptr;
    self->idx_map   = nullptr;
    self->bg_a_fd   = -1;
    self->bg_b_fd   = -1;
    self->idx_fd    = -1;
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

static GstFlowReturn
gst_hailovampire_overlay_transform_ip(GstBaseTransform *trans, GstBuffer *buffer)
{
    GST_DEBUG_OBJECT(GST_HAILO_VAMPIRE_OVERLAY(trans), "transform_ip pass-through");
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
