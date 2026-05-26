/*
 * gsthailotilecropper_dynamic.cpp
 *
 * Derived from TAPPAS hailotilecropper (LGPL-2.1).
 * Copyright (c) 2021-2026 Hailo Technologies Ltd. (base class & reference impl)
 * Copyright (c) 2026 hailo-apps-infra contributors (this derivative)
 *
 * Distributed under the LGPL-2.1 license.
 */
#include <gst/gst.h>
#include <opencv2/opencv.hpp>
#include <sstream>
#include <string>
#include <vector>

#include "gsthailotilecropper_dynamic.hpp"
#include "gst_hailo_meta.hpp"
#include "hailo_common.hpp"

GST_DEBUG_CATEGORY_STATIC(gst_hailotilecropper_dynamic_debug);
#define GST_CAT_DEFAULT gst_hailotilecropper_dynamic_debug
#define _do_init \
    GST_DEBUG_CATEGORY_INIT(gst_hailotilecropper_dynamic_debug, \
                            "hailotilecropper_dynamic", 0, \
                            "hailotilecropper_dynamic element");

#define gst_hailotilecropper_dynamic_parent_class parent_class
G_DEFINE_TYPE_WITH_CODE(GstHailoTileCropperDynamic,
                        gst_hailotilecropper_dynamic,
                        GST_TYPE_HAILO_BASE_CROPPER_DYN,
                        _do_init);

enum
{
    PROP_0,
    PROP_TILES_STATIC,   /* "x,y,w,h;x,y,w,h;..." (normalized 0..1) */
    PROP_ALLOW_EMPTY,    /* allow producing zero crops without warning */
    PROP_TILING_MODE,    /* SINGLE_SCALE (default) or MULTI_SCALE */
};

/* GEnum for the tiling-mode property. Mirrors the upstream hailotilecropper
 * enum so external consumers can use the same string values
 * ("single-scale" / "multi-scale"). */
#define GST_TYPE_HAILOTILECROPPER_DYNAMIC_TILING_MODE \
    (gst_hailotilecropper_dynamic_tiling_mode_get_type())
static GType
gst_hailotilecropper_dynamic_tiling_mode_get_type(void)
{
    static GType type_id = 0;
    static const GEnumValue modes[] = {
        {SINGLE_SCALE, "Single Scale", "single-scale"},
        {MULTI_SCALE,  "Multi Scale",  "multi-scale"},
        {0, NULL, NULL},
    };
    if (!type_id)
        type_id = g_enum_register_static(
            "GstHailoTileCropperDynamicTilingMode", modes);
    return type_id;
}

static void gst_hailotilecropper_dynamic_set_property(GObject *o, guint id,
                                                      const GValue *v, GParamSpec *p);
static void gst_hailotilecropper_dynamic_get_property(GObject *o, guint id,
                                                      GValue *v, GParamSpec *p);
static void gst_hailotilecropper_dynamic_finalize(GObject *o);

static std::vector<HailoROIPtr>
gst_hailotilecropper_dynamic_prepare_crops(GstHailoBaseCropperDyn *cropper, GstBuffer *buf);

/* Pass-through resize: same as TAPPAS hailotilecropper does. */
static void
hailotilecropper_dynamic_resize(GstHailoBaseCropperDyn *,
                                std::vector<cv::Mat> &cropped,
                                std::vector<cv::Mat> &resized,
                                HailoROIPtr,
                                GstVideoFormat fmt)
{
    resize_normal(cv::INTER_LINEAR, cropped, resized, fmt);
}

/* Trim leading/trailing ASCII whitespace from a std::string view. */
static std::string
trim_ws(const std::string &in)
{
    size_t start = 0;
    while (start < in.size() && std::isspace((unsigned char)in[start])) ++start;
    size_t end = in.size();
    while (end > start && std::isspace((unsigned char)in[end - 1])) --end;
    return in.substr(start, end - start);
}

/* Parse the optional mode field ("m"/"multi-scale" → 1, "s"/"single-scale" → 0,
 * empty → -1 sentinel meaning "use cropper default"). Returns -2 on parse error. */
static int
parse_tile_mode(const std::string &raw)
{
    std::string s = trim_ws(raw);
    if (s.empty()) return -1;
    if (s == "m" || s == "multi-scale" || s == "1" || s == "multi" || s == "M")
        return (int)MULTI_SCALE;
    if (s == "s" || s == "single-scale" || s == "0" || s == "single" || s == "S")
        return (int)SINGLE_SCALE;
    return -2;
}

/* Parse `tiles-static`: "x,y,w,h[,mode];x,y,w,h[,mode]" — whitespace allowed.
 * `mode` is optional and per-tile; absent ⇒ cropper's tiling-mode applies. */
static std::vector<StaticTile>
parse_static_tiles(const gchar *raw)
{
    std::vector<StaticTile> out;
    if (!raw || !*raw)
        return out;

    std::string s(raw);
    std::stringstream ss(s);
    std::string tile_str;
    while (std::getline(ss, tile_str, ';'))
    {
        if (tile_str.empty())
            continue;
        std::stringstream ts(tile_str);
        std::string field;
        float vals[4] = {0, 0, 0, 0};
        int idx = 0;
        int mode_override = -1;
        bool parse_err = false;
        while (idx < 4 && std::getline(ts, field, ','))
        {
            try { vals[idx++] = std::stof(field); }
            catch (const std::exception &) { parse_err = true; idx = -1; break; }
        }
        /* Optional 5th field: per-tile mode override. */
        if (idx == 4 && std::getline(ts, field, ','))
        {
            int m = parse_tile_mode(field);
            if (m == -2) {
                GST_WARNING("Tile '%s': unrecognized mode '%s' "
                            "(expected 'm'/'s' or 'multi-scale'/'single-scale'); "
                            "falling back to cropper default.",
                            tile_str.c_str(), field.c_str());
            } else {
                mode_override = m;
            }
        }
        /* Reject any trailing fields beyond the 5th. */
        if (std::getline(ts, field, ',')) {
            GST_WARNING("Tile '%s' has unexpected trailing fields after mode; "
                        "expected 'x,y,w,h[,mode]'.", tile_str.c_str());
            parse_err = true;
        }
        /* I1: bounds-check to [0,1] with small float epsilon. */
        constexpr float kEps = 1e-4f;
        bool valid = (!parse_err && idx == 4
                      && vals[2] > 0 && vals[3] > 0
                      && vals[0] >= -kEps && vals[1] >= -kEps
                      && vals[0] + vals[2] <= 1.0f + kEps
                      && vals[1] + vals[3] <= 1.0f + kEps);
        /* I2: warn on malformed/out-of-range entries instead of silently dropping. */
        if (!valid) {
            GST_WARNING("Skipping malformed tile entry: '%s'", tile_str.c_str());
            continue;
        }
        out.push_back({vals[0], vals[1], vals[2], vals[3], mode_override});
    }
    return out;
}

static void
gst_hailotilecropper_dynamic_class_init(GstHailoTileCropperDynamicClass *klass)
{
    GObjectClass             *gobject_class    = G_OBJECT_CLASS(klass);
    GstElementClass          *gstelement_class = GST_ELEMENT_CLASS(klass);
    GstHailoBaseCropperDynClass *base_class       = (GstHailoBaseCropperDynClass *)klass;

    gobject_class->set_property = gst_hailotilecropper_dynamic_set_property;
    gobject_class->get_property = gst_hailotilecropper_dynamic_get_property;
    gobject_class->finalize     = gst_hailotilecropper_dynamic_finalize;

    base_class->prepare_crops = gst_hailotilecropper_dynamic_prepare_crops;
    base_class->resize        = hailotilecropper_dynamic_resize;

    gst_element_class_set_static_metadata(
        gstelement_class,
        "hailotilecropper_dynamic - Dynamic Tiling",
        "Hailo/Tools",
        "Crops tiles defined dynamically by upstream pipeline elements and/or statically by properties",
        "hailo-apps-infra contributors <noreply@hailo.ai>");

    g_object_class_install_property(
        gobject_class, PROP_TILES_STATIC,
        g_param_spec_string(
            "tiles-static", "Static tiles",
            "Semicolon-separated list of static tile rectangles, normalized to "
            "[0,1] of the frame. Format: 'x,y,w,h[,mode];x,y,w,h[,mode];...'. "
            "The optional 5th field 'mode' overrides the cropper-level "
            "'tiling-mode' for that tile only; accepted values are 'm' / "
            "'multi-scale' / '1' (boundary-strip ON) and 's' / 'single-scale' "
            "/ '0' (boundary-strip OFF). Omit the mode to inherit the cropper "
            "default. Static tiles are appended to dynamic tiles read from the "
            "buffer's HailoROI on every frame. Empty string disables static tiles.",
            "",
            (GParamFlags)(G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS)));

    g_object_class_install_property(
        gobject_class, PROP_ALLOW_EMPTY,
        g_param_spec_boolean(
            "allow-empty", "Allow empty",
            "If TRUE (default), buffers with zero tiles produce zero crop-pad "
            "outputs (bypass-only). If FALSE, log a warning when no tiles are produced.",
            TRUE,
            (GParamFlags)(G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS)));

    g_object_class_install_property(
        gobject_class, PROP_TILING_MODE,
        g_param_spec_enum(
            "tiling-mode", "Tiling mode",
            "Tag emitted HailoTileROI objects with this mode. Default "
            "'single-scale' preserves legacy behavior. Set to 'multi-scale' "
            "when the configured tiles form a scale hierarchy (e.g. dense "
            "grid + coarser extra grids); the downstream hailotileaggregator "
            "then enables remove_exceeded_bboxes (boundary stripping via "
            "'border-threshold') and remove_large_landscape. Tiles at the "
            "actual frame boundary are exempt from boundary stripping, so "
            "objects at the frame edge are preserved.",
            GST_TYPE_HAILOTILECROPPER_DYNAMIC_TILING_MODE,
            (gint)SINGLE_SCALE,
            (GParamFlags)(G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS)));
}

static void
gst_hailotilecropper_dynamic_init(GstHailoTileCropperDynamic *self)
{
    self->tiles_static_str = g_strdup("");
    new (&self->static_tiles) std::vector<StaticTile>();  /* placement-new */
    self->allow_empty = TRUE;
    self->tiling_mode = SINGLE_SCALE;
}

static void
gst_hailotilecropper_dynamic_finalize(GObject *object)
{
    GstHailoTileCropperDynamic *self = GST_HAILO_TILE_CROPPER_DYNAMIC(object);
    g_free(self->tiles_static_str);
    self->static_tiles.~vector<StaticTile>();
    G_OBJECT_CLASS(gst_hailotilecropper_dynamic_parent_class)->finalize(object);
}

static void
gst_hailotilecropper_dynamic_set_property(GObject *object, guint prop_id,
                                          const GValue *value, GParamSpec *pspec)
{
    GstHailoTileCropperDynamic *self = GST_HAILO_TILE_CROPPER_DYNAMIC(object);
    switch (prop_id)
    {
    case PROP_TILES_STATIC: {
        GST_OBJECT_LOCK(self);
        g_free(self->tiles_static_str);
        self->tiles_static_str = g_value_dup_string(value);
        self->static_tiles = parse_static_tiles(self->tiles_static_str);
        GST_INFO_OBJECT(self, "Parsed %zu static tile(s)", self->static_tiles.size());
        GST_OBJECT_UNLOCK(self);
        break;
    }
    case PROP_ALLOW_EMPTY:
        self->allow_empty = g_value_get_boolean(value);
        break;
    case PROP_TILING_MODE:
        GST_OBJECT_LOCK(self);
        self->tiling_mode = (hailo_tiling_mode_t)g_value_get_enum(value);
        GST_OBJECT_UNLOCK(self);
        break;
    default:
        G_OBJECT_WARN_INVALID_PROPERTY_ID(object, prop_id, pspec);
    }
}

static void
gst_hailotilecropper_dynamic_get_property(GObject *object, guint prop_id,
                                          GValue *value, GParamSpec *pspec)
{
    GstHailoTileCropperDynamic *self = GST_HAILO_TILE_CROPPER_DYNAMIC(object);
    switch (prop_id)
    {
    case PROP_TILES_STATIC:
        GST_OBJECT_LOCK(self);
        g_value_set_string(value, self->tiles_static_str);
        GST_OBJECT_UNLOCK(self);
        break;
    case PROP_ALLOW_EMPTY:
        g_value_set_boolean(value, self->allow_empty);
        break;
    case PROP_TILING_MODE:
        GST_OBJECT_LOCK(self);
        g_value_set_enum(value, (gint)self->tiling_mode);
        GST_OBJECT_UNLOCK(self);
        break;
    default:
        G_OBJECT_WARN_INVALID_PROPERTY_ID(object, prop_id, pspec);
    }
}

/* Override: collect dynamic tiles already on the parent ROI, append static
 * tiles, return everything. Each static tile is *added* to the ROI so the
 * downstream hailotileaggregator sees the same set we cropped.
 */
static std::vector<HailoROIPtr>
gst_hailotilecropper_dynamic_prepare_crops(GstHailoBaseCropperDyn *cropper, GstBuffer *buf)
{
    GstHailoTileCropperDynamic *self = GST_HAILO_TILE_CROPPER_DYNAMIC(cropper);

    HailoROIPtr main_roi = get_hailo_main_roi(buf, /*create_if_missing=*/true);
    std::vector<HailoROIPtr> crops;

    /* 1. Dynamic tiles: HailoTileROI objects pre-attached to main_roi. */
    for (auto &obj : main_roi->get_objects_typed(HAILO_TILE)) {
        /* I4: guard against a non-HailoROI HAILO_TILE object (defensive cast). */
        auto roi = std::dynamic_pointer_cast<HailoROI>(obj);
        if (roi) crops.push_back(std::move(roi));
    }

    /* I3: capture dynamic count explicitly before appending static tiles. */
    const size_t dynamic_count = crops.size();

    /* 2. Static tiles: snapshot tiles + tiling-mode under lock so a
     * concurrent set_property mid-flight is safe. */
    std::vector<StaticTile> snapshot;
    hailo_tiling_mode_t mode_snapshot;
    {
        GST_OBJECT_LOCK(self);
        snapshot = self->static_tiles;
        mode_snapshot = self->tiling_mode;
        GST_OBJECT_UNLOCK(self);
    }
    uint next_index = static_cast<uint>(crops.size());
    for (auto &t : snapshot)
    {
        /* Per-tile mode_override (-1 sentinel) falls back to the cropper's
         * tiling-mode default. */
        hailo_tiling_mode_t tile_mode =
            (t.mode_override >= 0)
                ? (hailo_tiling_mode_t)t.mode_override
                : mode_snapshot;
        auto tile = std::make_shared<HailoTileROI>(
            HailoBBox(t.x, t.y, t.w, t.h),
            next_index++,
            /*overlap_x_axis=*/0.0f,
            /*overlap_y_axis=*/0.0f,
            /*layer=*/0,
            /*mode=*/tile_mode);
        main_roi->add_object(tile);
        crops.push_back(tile);
    }

    if (crops.empty() && !self->allow_empty)
        GST_WARNING_OBJECT(self,
            "Buffer %p produced zero tiles and allow-empty=false",
            (void *)buf);

    GST_LOG_OBJECT(self,
        "prepare_crops: %zu tile(s) (%zu dynamic + %zu static)",
        crops.size(),
        dynamic_count,
        snapshot.size());

    return crops;
}

/* ============================================================================
 * Plugin registration (mirrors gsthailooverlay_community.cpp pattern)
 * ============================================================================ */

static gboolean
plugin_init(GstPlugin *plugin)
{
    return gst_element_register(plugin,
                                "hailotilecropper_dynamic",
                                GST_RANK_PRIMARY,
                                GST_TYPE_HAILO_TILE_CROPPER_DYNAMIC);
}

#ifndef PACKAGE
#define PACKAGE "hailotilecropper_dynamic"
#endif
#ifndef PACKAGE_VERSION
#define PACKAGE_VERSION "0.1.0"
#endif

GST_PLUGIN_DEFINE(GST_VERSION_MAJOR,
                  GST_VERSION_MINOR,
                  hailotilecropper_dynamic,
                  "Dynamic tile cropper for Hailo pipelines",
                  plugin_init,
                  PACKAGE_VERSION,
                  "LGPL",
                  "hailo-apps-infra",
                  "https://github.com/hailo-ai/hailo-apps-infra")
