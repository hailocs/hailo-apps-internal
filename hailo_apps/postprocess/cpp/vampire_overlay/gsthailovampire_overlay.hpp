/**
 * Copyright (c) 2026 Hailo Technologies Ltd. All rights reserved.
 * Distributed under the LGPL license.
 *
 * hailovampire_overlay - GStreamer element that paints "vampire" pixels
 * with the corresponding region of a shared-memory background buffer.
 **/
#pragma once

#include <gst/base/gstbasetransform.h>
#include "hailo_objects.hpp"

G_BEGIN_DECLS

#define GST_TYPE_HAILO_VAMPIRE_OVERLAY (gst_hailovampire_overlay_get_type())
#define GST_HAILO_VAMPIRE_OVERLAY(obj) \
    (G_TYPE_CHECK_INSTANCE_CAST((obj), GST_TYPE_HAILO_VAMPIRE_OVERLAY, GstHailoVampireOverlay))
#define GST_HAILO_VAMPIRE_OVERLAY_CLASS(klass) \
    (G_TYPE_CHECK_CLASS_CAST((klass), GST_TYPE_HAILO_VAMPIRE_OVERLAY, GstHailoVampireOverlayClass))
#define GST_IS_HAILO_VAMPIRE_OVERLAY(obj) \
    (G_TYPE_CHECK_INSTANCE_TYPE((obj), GST_TYPE_HAILO_VAMPIRE_OVERLAY))
#define GST_IS_HAILO_VAMPIRE_OVERLAY_CLASS(obj) \
    (G_TYPE_CHECK_CLASS_TYPE((klass), GST_TYPE_HAILO_VAMPIRE_OVERLAY))

typedef struct _GstHailoVampireOverlay GstHailoVampireOverlay;
typedef struct _GstHailoVampireOverlayClass GstHailoVampireOverlayClass;

struct _GstHailoVampireOverlay
{
    GstBaseTransform base;

    // Shared-memory background buffer names (created by BackgroundService).
    // Empty strings mean "not configured" — element is pass-through in that case.
    gchar  *bg_shm_a_name;
    gchar  *bg_shm_b_name;
    gchar  *bg_idx_shm_name;

    // Background buffer dimensions. Must match the BackgroundService config.
    gint    bg_width;
    gint    bg_height;

    // Classification type tag the Python layer attaches to detections that
    // should be vampire-d. Default: "vampire".
    gchar  *vampire_classification_type;

    // Mask dilation params.
    gint    dilate_radius;        // default 15
    gint    dilate_iterations;    // default 2

    // Internal state — populated lazily on first transform_ip when shm names are set.
    // Tasks 7/8 will fill these in. Declared here so the struct shape is stable.
    void   *bg_a_map;    // mmap pointer (uint8*) for bg_shm_a
    void   *bg_b_map;    // mmap pointer (uint8*) for bg_shm_b
    void   *idx_map;     // mmap pointer (uint8*) for bg_idx_shm
    int     bg_a_fd;
    int     bg_b_fd;
    int     idx_fd;
    gsize   bg_bytes;    // bg_width * bg_height * 3
};

struct _GstHailoVampireOverlayClass
{
    GstBaseTransformClass base_class;
};

GType gst_hailovampire_overlay_get_type(void);

G_END_DECLS
