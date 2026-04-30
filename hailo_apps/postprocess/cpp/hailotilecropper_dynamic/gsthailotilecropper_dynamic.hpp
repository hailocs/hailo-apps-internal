/*
 * gsthailotilecropper_dynamic.hpp
 *
 * GStreamer element: hailotilecropper_dynamic
 *
 * Crops tiles based on HailoTileROI sub-objects pre-attached to the buffer's
 * main ROI (dynamic, set by upstream pipeline elements) plus optional static
 * tiles configured via the `tiles-static` property.
 *
 * Derived from TAPPAS hailotilecropper (LGPL-2.1).
 * Copyright (c) 2021-2026 Hailo Technologies Ltd. (base class & reference impl)
 * Copyright (c) 2026 hailo-apps-infra contributors (this derivative)
 *
 * Distributed under the LGPL-2.1 license.
 */
#pragma once

#include <gst/gst.h>
#include <vector>
#include "gsthailobasecropper.hpp"
#include "hailo_objects.hpp"

G_BEGIN_DECLS

#define GST_TYPE_HAILO_TILE_CROPPER_DYNAMIC (gst_hailotilecropper_dynamic_get_type())
#define GST_HAILO_TILE_CROPPER_DYNAMIC(obj) \
    (G_TYPE_CHECK_INSTANCE_CAST((obj), GST_TYPE_HAILO_TILE_CROPPER_DYNAMIC, GstHailoTileCropperDynamic))
#define GST_HAILO_TILE_CROPPER_DYNAMIC_CLASS(klass) \
    (G_TYPE_CHECK_CLASS_CAST((klass), GST_TYPE_HAILO_TILE_CROPPER_DYNAMIC, GstHailoTileCropperDynamicClass))
#define GST_IS_HAILO_TILE_CROPPER_DYNAMIC(obj) \
    (G_TYPE_CHECK_INSTANCE_TYPE((obj), GST_TYPE_HAILO_TILE_CROPPER_DYNAMIC))
#define GST_IS_HAILO_TILE_CROPPER_DYNAMIC_CLASS(klass) \
    (G_TYPE_CHECK_CLASS_TYPE((klass), GST_TYPE_HAILO_TILE_CROPPER_DYNAMIC))

typedef struct _GstHailoTileCropperDynamic      GstHailoTileCropperDynamic;
typedef struct _GstHailoTileCropperDynamicClass GstHailoTileCropperDynamicClass;

/* One static tile parsed from the `tiles-static` property string.
 * All values are normalized [0.0, 1.0] (fraction of frame).
 */
struct StaticTile
{
    float x;
    float y;
    float w;
    float h;
};

struct _GstHailoTileCropperDynamic
{
    GstHailoBaseCropper hailo_cropper;     /* base */
    gchar              *tiles_static_str;  /* property: raw "x,y,w,h;..." */
    std::vector<StaticTile> static_tiles;  /* parsed cache */
    gboolean            allow_empty;       /* property: if FALSE, log a warning when no tiles produced */
};

struct _GstHailoTileCropperDynamicClass
{
    GstHailoBaseCropperClass parent_class;
};

GType gst_hailotilecropper_dynamic_get_type(void);

G_END_DECLS
