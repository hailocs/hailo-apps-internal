/**
 * Copyright (c) 2021-2022 Hailo Technologies Ltd. All rights reserved.
 * Distributed under the LGPL license (https://www.gnu.org/licenses/old-licenses/lgpl-2.1.txt)
 **/

#include <gst/video/video-format.h>
#include <atomic>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <sys/stat.h>

#include "hailo_objects.hpp"
#include "hailo_common.hpp"
#include "image.hpp"
#include "lp_crop_saver.hpp"

#include <opencv2/opencv.hpp>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>
#include <opencv2/core.hpp>

#define LICENSE_PLATE_LABEL "license_plate"
// Expand LP crop by this fraction on each side.
#define LP_CROP_PAD_FRACTION 0.30f

static std::atomic<int> g_lp_crop_counter{0};

static bool lpr_debug_enabled()
{
    static int enabled = -1;
    if (enabled == -1)
    {
        const char *val = std::getenv("HAILO_LPR_DEBUG");
        if (!val || val[0] == '\0')
            enabled = 0;
        else if (val[0] == '1' || val[0] == 't' || val[0] == 'T' || val[0] == 'y' || val[0] == 'Y')
            enabled = 1;
        else if (val[0] == '0' || val[0] == 'f' || val[0] == 'F' || val[0] == 'n' || val[0] == 'N')
            enabled = 0;
        else
            enabled = 1;
    }
    return enabled == 1;
}

static int lpr_debug_every_n()
{
    static int every_n = -1;
    if (every_n == -1)
    {
        const char *val = std::getenv("HAILO_LPR_DEBUG_EVERY_N");
        if (val && val[0] != '\0')
        {
            char *end = nullptr;
            long parsed = std::strtol(val, &end, 10);
            every_n = (end != val && parsed > 0) ? static_cast<int>(parsed) : 1;
        }
        else
        {
            every_n = 30;
        }
    }
    return every_n;
}

static void lp_dbg(const char *fmt, ...)
{
    if (!lpr_debug_enabled())
        return;
    static std::atomic<int> debug_counter{0};
    int every_n = lpr_debug_every_n();
    int count = debug_counter.fetch_add(1);
    if (every_n > 1 && (count % every_n) != 0)
        return;
    std::fprintf(stderr, "[lp_crop_saver] ");
    va_list args;
    va_start(args, fmt);
    std::vfprintf(stderr, fmt, args);
    va_end(args);
    std::fprintf(stderr, "\n");
    std::fflush(stderr);
}

static bool lpr_save_crops_enabled()
{
    const char *val = std::getenv("HAILO_LPR_SAVE_CROPS");
    if (!val || val[0] == '\0')
        return false;
    return val[0] != '0';
}

static const char *get_crops_dir()
{
    static const char *dir = nullptr;
    if (dir == nullptr)
    {
        dir = std::getenv("HAILO_LPR_CROPS_DIR");
        if (dir == nullptr || dir[0] == '\0')
            dir = "lpr_debug_crops";
    }
    return dir;
}

static void ensure_dir_exists(const std::string &path)
{
    mkdir(path.c_str(), 0755);
}

static int get_tracking_id(const HailoDetectionPtr &detection)
{
    for (auto obj : detection->get_objects_typed(HAILO_UNIQUE_ID))
    {
        auto unique_id = std::dynamic_pointer_cast<HailoUniqueID>(obj);
        if (unique_id && unique_id->get_mode() == TRACKING_ID)
        {
            return unique_id->get_id();
        }
    }
    return -1;
}

static void save_crop_image(std::shared_ptr<HailoMat> image,
                            const HailoBBox &bbox,
                            const std::string &prefix,
                            int id,
                            int track_id)
{
    if (!lpr_save_crops_enabled() || !image)
        return;

    try
    {
        const float pad_x = bbox.width() * LP_CROP_PAD_FRACTION;
        const float pad_y = bbox.height() * LP_CROP_PAD_FRACTION;
        const float xmin = std::max(0.0f, std::min(1.0f, bbox.xmin() - pad_x));
        const float ymin = std::max(0.0f, std::min(1.0f, bbox.ymin() - pad_y));
        const float xmax = std::max(xmin, std::min(1.0f, bbox.xmax() + pad_x));
        const float ymax = std::max(ymin, std::min(1.0f, bbox.ymax() + pad_y));

        if (xmax <= xmin || ymax <= ymin)
            return;

        auto crop_roi = std::make_shared<HailoROI>(HailoBBox(xmin, ymin, (xmax - xmin), (ymax - ymin)));
        std::vector<cv::Mat> cropped_image_vec = image->crop(crop_roi);
        if (cropped_image_vec.empty() || cropped_image_vec[0].empty())
            return;

        cv::Mat bgr_crop;
        switch (image->get_type())
        {
        case HAILO_MAT_RGB:
            cv::cvtColor(cropped_image_vec[0], bgr_crop, cv::COLOR_RGB2BGR);
            break;
        case HAILO_MAT_YUY2:
            cv::cvtColor(cropped_image_vec[0], bgr_crop, cv::COLOR_YUV2BGR_YUY2);
            break;
        case HAILO_MAT_NV12:
            if (cropped_image_vec.size() < 2)
                return;
            cv::cvtColorTwoPlane(cropped_image_vec[0], cropped_image_vec[1], bgr_crop, cv::COLOR_YUV2BGR_NV12);
            break;
        default:
            bgr_crop = cropped_image_vec[0];
            break;
        }

        std::string base_dir = get_crops_dir();
        ensure_dir_exists(base_dir);
        std::string prefix_dir = base_dir + "/" + prefix;
        ensure_dir_exists(prefix_dir);
        std::string sub_dir = prefix_dir;
        if (track_id >= 0)
        {
            sub_dir = prefix_dir + "/track_" + std::to_string(track_id);
            ensure_dir_exists(sub_dir);
        }

        char filename[512];
        std::snprintf(filename, sizeof(filename), "%s/%s_%05d.jpg", sub_dir.c_str(), prefix.c_str(), id);
        cv::imwrite(filename, bgr_crop);

        lp_dbg("SAVED: %s (%dx%d)", filename, bgr_crop.cols, bgr_crop.rows);
    }
    catch (const std::exception &e)
    {
        lp_dbg("Failed to save crop: %s", e.what());
    }
}

static void save_lp_crops(HailoROIPtr roi, std::shared_ptr<HailoMat> image)
{
    if (!roi || !image)
        return;

    auto detections = hailo_common::get_hailo_detections(roi);
    for (auto &det : detections)
    {
        std::string label = det->get_label();
        if (label == LICENSE_PLATE_LABEL)
        {
            HailoBBox lp_flat_bbox = hailo_common::create_flattened_bbox(det->get_bbox(), det->get_scaling_bbox());
            int track_id = get_tracking_id(det);
            int crop_id = g_lp_crop_counter.fetch_add(1);
            save_crop_image(image, lp_flat_bbox, "lp_to_ocr", crop_id, track_id);
            continue;
        }

        // If this is a vehicle, look for nested license plates
        int vehicle_track_id = get_tracking_id(det);
        auto nested = hailo_common::get_hailo_detections(det);
        for (auto &lp_det : nested)
        {
            std::string lp_label = lp_det->get_label();
            if (lp_label != LICENSE_PLATE_LABEL)
                continue;
            HailoBBox lp_flat_bbox = hailo_common::create_flattened_bbox(lp_det->get_bbox(), lp_det->get_scaling_bbox());
            int track_id = get_tracking_id(lp_det);
            if (track_id < 0 && vehicle_track_id >= 0)
                track_id = vehicle_track_id;
            int crop_id = g_lp_crop_counter.fetch_add(1);
            save_crop_image(image, lp_flat_bbox, "lp_to_ocr", crop_id, track_id);
        }
    }
}

void filter(HailoROIPtr roi, GstVideoFrame *frame)
{
    if (!frame || !roi)
        return;

    if (!lpr_save_crops_enabled())
        return;

    std::shared_ptr<HailoMat> hmat = get_mat_by_format(*(&frame->buffer), &frame->info, 1, 1);
    if (!hmat)
        return;

    save_lp_crops(roi, hmat);
}
