/**
 * Copyright (c) 2021-2022 Hailo Technologies Ltd. All rights reserved.
 * Distributed under the LGPL license (https://www.gnu.org/licenses/old-licenses/lgpl-2.1.txt)
 **/
#include "lpr_croppers.hpp"
#include <array>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cctype>
#include <fstream>
#include <iostream>
#include <sstream>
#include <unordered_map>
#include <mutex>
#include <vector>
#include <sys/stat.h>
#include <atomic>

#define LICENSE_PLATE_LABEL "license_plate"
#define OCR_RESULT_LABEL "lpr_result"

static constexpr std::array<const char *, 2> VEHICLE_LABELS = {"car", "vehicle"};
static constexpr float FULLFRAME_PAD_RATIO = 0.1f;
static constexpr float VEHICLE_TRI_X1 = 0.0f;
static constexpr float VEHICLE_TRI_Y1 = 0.75f;
static constexpr float VEHICLE_TRI_X2 = 1.0f;
static constexpr float VEHICLE_TRI_Y2 = 0.33f;
static constexpr float VEHICLE_TRI_X3 = 1.0f;
static constexpr float VEHICLE_TRI_Y3 = 1.0f;
static constexpr float CAMERA_RIGHT_AWAY_DISCARD_TOP_Y = 0.33f;

static constexpr float DEFAULT_VEHICLE_ROI_MIN_INTERSECTION = 1.0f;

// Frame counter for unique filenames
static std::atomic<int> g_frame_counter{0};
static std::atomic<int> g_vehicle_crop_counter{0};
static std::atomic<int> g_lp_crop_counter{0};
static std::unordered_map<int, int> g_vehicle_track_seen;
static constexpr int VEHICLE_WARMUP_FRAMES = 5;
static std::unordered_map<int, int> g_lp_track_age;
static constexpr int LP_TRACK_COOLDOWN_FRAMES = 3;
static constexpr float MIN_LP_REL_AREA = 0.01f;
static std::unordered_map<int, std::string> g_lp_db; // track_id -> plate text
static std::mutex g_lp_db_mutex;
struct TrackOcrStats
{
    int vehicle_crops = 0;
    int lp_to_ocr = 0;
    int ocr_results = 0;
};
static std::unordered_map<int, TrackOcrStats> g_track_ocr_stats;

struct VehicleRoiConfig
{
    bool enabled = false;
    HailoBBox roi = HailoBBox(0.0f, 0.0f, 1.0f, 1.0f);
    float min_intersection_ratio = DEFAULT_VEHICLE_ROI_MIN_INTERSECTION;
    std::string source;
};

static void mark_track_lpr(int track_id, const std::string &plate)
{
    if (track_id < 0)
        return;
    std::lock_guard<std::mutex> lock(g_lp_db_mutex);
    g_lp_db[track_id] = plate;
}

static bool track_has_lpr(int track_id, std::string *plate = nullptr)
{
    if (track_id < 0)
        return false;
    std::lock_guard<std::mutex> lock(g_lp_db_mutex);
    auto it = g_lp_db.find(track_id);
    if (it == g_lp_db.end())
        return false;
    if (plate)
        *plate = it->second;
    return true;
}

static bool parse_roi_list(const std::string &value, float &xmin, float &ymin, float &xmax, float &ymax, float &min_intersection)
{
    std::vector<float> vals;
    std::stringstream ss(value);
    std::string token;
    while (std::getline(ss, token, ','))
    {
        std::stringstream ts(token);
        float v = 0.0f;
        if (ts >> v)
        {
            vals.push_back(v);
        }
    }
    if (vals.size() < 4)
        return false;
    xmin = vals[0];
    ymin = vals[1];
    xmax = vals[2];
    ymax = vals[3];
    if (vals.size() >= 5)
        min_intersection = vals[4];
    return true;
}

static bool extract_key_float(const std::string &text, const std::string &key, float &out)
{
    size_t pos = text.find(key);
    if (pos == std::string::npos)
        return false;
    pos = text.find_first_of(":=", pos + key.size());
    if (pos == std::string::npos)
        return false;
    pos++;
    while (pos < text.size() && (std::isspace(static_cast<unsigned char>(text[pos])) || text[pos] == '[' || text[pos] == ',' || text[pos] == '"'))
        pos++;
    char *end = nullptr;
    out = std::strtof(text.c_str() + pos, &end);
    return end != (text.c_str() + pos);
}

static bool parse_roi_from_text(const std::string &text, VehicleRoiConfig &config)
{
    float xmin = 0.0f;
    float ymin = 0.0f;
    float xmax = 1.0f;
    float ymax = 1.0f;
    float min_intersection = DEFAULT_VEHICLE_ROI_MIN_INTERSECTION;
    bool has_key = false;

    has_key |= extract_key_float(text, "xmin", xmin);
    has_key |= extract_key_float(text, "ymin", ymin);
    has_key |= extract_key_float(text, "xmax", xmax);
    has_key |= extract_key_float(text, "ymax", ymax);
    extract_key_float(text, "min_intersection", min_intersection);
    extract_key_float(text, "min_intersection_ratio", min_intersection);

    if (!has_key)
    {
        std::vector<float> nums;
        const char *p = text.c_str();
        while (*p != '\0')
        {
            if ((*p >= '0' && *p <= '9') || *p == '-' || *p == '.')
            {
                char *end = nullptr;
                float v = std::strtof(p, &end);
                if (end != p)
                {
                    nums.push_back(v);
                    p = end;
                    continue;
                }
            }
            p++;
        }
        if (nums.size() >= 4)
        {
            xmin = nums[0];
            ymin = nums[1];
            xmax = nums[2];
            ymax = nums[3];
            if (nums.size() >= 5)
                min_intersection = nums[4];
        }
        else
        {
            return false;
        }
    }

    xmin = std::max(0.0f, std::min(1.0f, xmin));
    ymin = std::max(0.0f, std::min(1.0f, ymin));
    xmax = std::max(0.0f, std::min(1.0f, xmax));
    ymax = std::max(0.0f, std::min(1.0f, ymax));
    if (xmax <= xmin || ymax <= ymin)
        return false;
    min_intersection = std::max(0.0f, std::min(1.0f, min_intersection));

    config.enabled = true;
    config.roi = HailoBBox(xmin, ymin, xmax - xmin, ymax - ymin);
    config.min_intersection_ratio = min_intersection;
    return true;
}

static VehicleRoiConfig get_vehicle_roi_config()
{
    static std::atomic<int> initialized{0};
    static VehicleRoiConfig config;
    if (initialized.load() == 1)
        return config;

    VehicleRoiConfig local;
    const char *env_roi = std::getenv("HAILO_LPR_VEHICLE_ROI");
    if (env_roi && env_roi[0] != '\0')
    {
        float xmin = 0.0f, ymin = 0.0f, xmax = 1.0f, ymax = 1.0f;
        float min_intersection = DEFAULT_VEHICLE_ROI_MIN_INTERSECTION;
        if (parse_roi_list(env_roi, xmin, ymin, xmax, ymax, min_intersection))
        {
            float cxmin = CLAMP(xmin, 0.0f, 1.0f);
            float cymin = CLAMP(ymin, 0.0f, 1.0f);
            float cxmax = CLAMP(xmax, 0.0f, 1.0f);
            float cymax = CLAMP(ymax, 0.0f, 1.0f);
            if (cxmax > cxmin && cymax > cymin)
            {
                local.enabled = true;
                local.roi = HailoBBox(cxmin, cymin, cxmax - cxmin, cymax - cymin);
                local.min_intersection_ratio = CLAMP(min_intersection, 0.0f, 1.0f);
                local.source = "HAILO_LPR_VEHICLE_ROI";
            }
        }
    }

    const char *env_path = std::getenv("HAILO_LPR_VEHICLE_ROI_CONFIG");
    if (!local.enabled && env_path && env_path[0] != '\0')
    {
        std::ifstream file(env_path);
        if (file)
        {
            std::stringstream buffer;
            buffer << file.rdbuf();
            if (parse_roi_from_text(buffer.str(), local))
            {
                local.source = env_path;
            }
        }
    }

    config = local;
    initialized.store(1);
    return config;
}

static float intersection_ratio(const HailoBBox &bbox, const HailoBBox &roi)
{
    float ixmin = std::max(bbox.xmin(), roi.xmin());
    float iymin = std::max(bbox.ymin(), roi.ymin());
    float ixmax = std::min(bbox.xmax(), roi.xmax());
    float iymax = std::min(bbox.ymax(), roi.ymax());
    float iw = std::max(0.0f, ixmax - ixmin);
    float ih = std::max(0.0f, iymax - iymin);
    float area = bbox.width() * bbox.height();
    if (area <= 0.0f)
        return 0.0f;
    return (iw * ih) / area;
}

static void lpr_dbg(const char *fmt, ...);

static bool vehicle_roi_accepts_bbox(const HailoBBox &bbox)
{
    VehicleRoiConfig config = get_vehicle_roi_config();
    if (!config.enabled)
        return true;
    float ratio = intersection_ratio(bbox, config.roi);
    bool ok = ratio >= config.min_intersection_ratio;
    lpr_dbg("vehicles_without_ocr: ROI gate ratio=%.3f min=%.3f bbox=[%.3f,%.3f,%.3f,%.3f] roi=[%.3f,%.3f,%.3f,%.3f] => %s",
            ratio, config.min_intersection_ratio,
            bbox.xmin(), bbox.ymin(), bbox.width(), bbox.height(),
            config.roi.xmin(), config.roi.ymin(), config.roi.width(), config.roi.height(),
            ok ? "KEEP" : "DROP");
    return ok;
}

static bool lpr_debug_enabled()
{
    static int enabled = -1;
    if (enabled == -1)
    {
        const char *val = std::getenv("HAILO_LPR_DEBUG");
        enabled = (val && val[0] != '\0' && val[0] != '0') ? 1 : 0;
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

static bool lpr_save_crops_enabled()
{
    return true;
}

static const char* get_crops_dir()
{
    static const char* dir = nullptr;
    if (dir == nullptr)
    {
        dir = std::getenv("HAILO_LPR_CROPS_DIR");
        if (dir == nullptr || dir[0] == '\0')
            dir = "lpr_debug_crops";
    }
    return dir;
}

static void ensure_dir_exists(const std::string& path)
{
    mkdir(path.c_str(), 0755);
}

static void lpr_dbg(const char *fmt, ...)
{
    if (!lpr_debug_enabled())
        return;
    static std::atomic<int> debug_counter{0};
    int every_n = lpr_debug_every_n();
    int count = debug_counter.fetch_add(1);
    if (every_n > 1 && (count % every_n) != 0)
        return;
    std::fprintf(stderr, "[lpr_croppers] ");
    va_list args;
    va_start(args, fmt);
    std::vfprintf(stderr, fmt, args);
    va_end(args);
    std::fprintf(stderr, "\n");
    std::fflush(stderr);
}

static void track_ocr_debug(int track_id, const char *event, const char *extra = nullptr)
{
    if (track_id < 0 || !lpr_debug_enabled())
        return;
    auto &stats = g_track_ocr_stats[track_id];
    if (extra && extra[0] != '\0')
    {
        lpr_dbg("track_debug: track_id=%d event=%s %s vehicle_crops=%d lp_to_ocr=%d ocr_results=%d",
                track_id, event, extra, stats.vehicle_crops, stats.lp_to_ocr, stats.ocr_results);
    }
    else
    {
        lpr_dbg("track_debug: track_id=%d event=%s vehicle_crops=%d lp_to_ocr=%d ocr_results=%d",
                track_id, event, stats.vehicle_crops, stats.lp_to_ocr, stats.ocr_results);
    }
}

static void track_ocr_vehicle_crop(int track_id)
{
    if (track_id < 0 || !lpr_debug_enabled())
        return;
    auto &stats = g_track_ocr_stats[track_id];
    stats.vehicle_crops++;
    track_ocr_debug(track_id, "vehicle_crop->lp");
}

static void track_ocr_lp_to_ocr(int track_id)
{
    if (track_id < 0 || !lpr_debug_enabled())
        return;
    auto &stats = g_track_ocr_stats[track_id];
    stats.lp_to_ocr++;
    track_ocr_debug(track_id, "lp_crop->ocr");
}

static void track_ocr_check_missing(int track_id, const char *context)
{
    if (track_id < 0 || !lpr_debug_enabled())
        return;
    auto it = g_track_ocr_stats.find(track_id);
    if (it == g_track_ocr_stats.end())
        return;
    const auto &stats = it->second;
    if (stats.vehicle_crops > stats.lp_to_ocr)
    {
        lpr_dbg("track_debug: track_id=%d event=%s missing_lp_to_ocr=%d vehicle_crops=%d lp_to_ocr=%d ocr_results=%d",
                track_id, context, stats.vehicle_crops - stats.lp_to_ocr,
                stats.vehicle_crops, stats.lp_to_ocr, stats.ocr_results);
    }
}

static void track_ocr_result(int track_id, const std::string &plate)
{
    if (track_id < 0 || !lpr_debug_enabled())
        return;
    auto &stats = g_track_ocr_stats[track_id];
    stats.ocr_results++;
    if (!plate.empty())
    {
        std::string extra = "plate='" + plate + "'";
        track_ocr_debug(track_id, "ocr_result", extra.c_str());
    }
    else
    {
        track_ocr_debug(track_id, "ocr_result");
    }
    track_ocr_check_missing(track_id, "ocr_result");
}

static void lpr_log_settings()
{
    static int logged = 0;
    if (logged || !lpr_debug_enabled())
        return;
    logged = 1;
    VehicleRoiConfig roi_config = get_vehicle_roi_config();
    lpr_dbg("settings: HAILO_LPR_SAVE_CROPS=%d crops_dir='%s' OCR_RESULT_LABEL='%s' tri=(%.2f,%.2f)-(%.2f,%.2f)-(%.2f,%.2f)",
            lpr_save_crops_enabled() ? 1 : 0,
            get_crops_dir(),
            OCR_RESULT_LABEL,
            VEHICLE_TRI_X1,
            VEHICLE_TRI_Y1,
            VEHICLE_TRI_X2,
            VEHICLE_TRI_Y2,
            VEHICLE_TRI_X3,
            VEHICLE_TRI_Y3);
    if (roi_config.enabled)
    {
        lpr_dbg("settings: vehicle_roi source='%s' roi=[%.3f,%.3f,%.3f,%.3f] min_intersection=%.3f",
                roi_config.source.c_str(),
                roi_config.roi.xmin(), roi_config.roi.ymin(), roi_config.roi.width(), roi_config.roi.height(),
                roi_config.min_intersection_ratio);
    }
}

static bool is_vehicle_label(const std::string &label)
{
    for (const auto *vehicle_label : VEHICLE_LABELS)
    {
        if (label == vehicle_label)
            return true;
    }
    return false;
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

static void attach_tracking_id_if_missing(const HailoDetectionPtr &detection, int track_id)
{
    if (!detection || track_id < 0)
        return;

    for (auto obj : detection->get_objects_typed(HAILO_UNIQUE_ID))
    {
        auto unique_id = std::dynamic_pointer_cast<HailoUniqueID>(obj);
        if (unique_id && unique_id->get_mode() == TRACKING_ID && unique_id->get_id() == track_id)
            return;
    }

    detection->add_object(std::make_shared<HailoUniqueID>(track_id, TRACKING_ID));
}

static bool camera_angle_accepts_vehicle(const HailoBBox &bbox)
{
    // Base camera: camera on right side of road, vehicles moving away.
    // Discard detections whose center is in the top third of the frame.
    float center_y = (bbox.ymin() + bbox.ymax()) * 0.5f;
    return center_y >= CAMERA_RIGHT_AWAY_DISCARD_TOP_Y;
}

/**
 * @brief Save a crop image to disk for debugging
 */
static void save_crop_image(std::shared_ptr<HailoMat> image, const HailoBBox& bbox, 
                            const std::string& prefix, int id, int track_id)
{
    if (!lpr_save_crops_enabled() || !image)
        return;
    
    try
    {
        const float xmin = std::max(0.0f, std::min(1.0f, bbox.xmin()));
        const float ymin = std::max(0.0f, std::min(1.0f, bbox.ymin()));
        const float xmax = std::max(xmin, std::min(1.0f, bbox.xmax()));
        const float ymax = std::max(ymin, std::min(1.0f, bbox.ymax()));

        if (xmax <= xmin || ymax <= ymin)
            return;

        auto crop_roi = std::make_shared<HailoROI>(HailoBBox(xmin, ymin, (xmax - xmin), (ymax - ymin)));
        std::vector<cv::Mat> cropped_image_vec = image->crop(crop_roi);
        if (cropped_image_vec.empty() || cropped_image_vec[0].empty())
            return;

        // Convert to BGR if needed for saving
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
        
        // Create output directory
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
        
        // Save image
        char filename[512];
        std::snprintf(filename, sizeof(filename), "%s/%s_%05d.jpg", sub_dir.c_str(), prefix.c_str(), id);
        cv::imwrite(filename, bgr_crop);
        
        lpr_dbg("SAVED: %s (%dx%d)", filename, bgr_crop.cols, bgr_crop.rows);
    }
    catch (const std::exception& e)
    {
        lpr_dbg("Failed to save crop: %s", e.what());
    }
}

/**
 * @brief Returns the calculate the variance of edges.
 *
 * @param image  -  cv::Mat
 *        The original image.
 *
 * @param roi  -  HailoBBox
 *        The ROI to read from the image
 *
 * @param crop_ratio  -  float
 *        The percent of the image to crop in from the edges (default 10%).
 *
 * @return float
 *         The variance of edges in the image.
 */
float quality_estimation(std::shared_ptr<HailoMat> hailo_mat, const HailoBBox &roi, const float crop_ratio = 0.1)
{
    lpr_dbg("  quality_estimation: roi=[%.3f,%.3f,%.3f,%.3f] crop_ratio=%.2f", 
            roi.xmin(), roi.ymin(), roi.width(), roi.height(), crop_ratio);
    
    // Crop the center of the roi from the image, avoid cropping out of bounds
    float roi_width = roi.width();
    float roi_height = roi.height();
    float roi_xmin = roi.xmin();
    float roi_ymin = roi.ymin();
    float roi_xmax = roi.xmax();
    float roi_ymax = roi.ymax();
    float x_offset = roi_width * crop_ratio;
    float y_offset = roi_height * crop_ratio;
    float cropped_xmin = CLAMP(roi_xmin + x_offset, 0, 1);
    float cropped_ymin = CLAMP(roi_ymin + y_offset, 0, 1);
    float cropped_xmax = CLAMP(roi_xmax - x_offset, cropped_xmin, 1);
    float cropped_ymax = CLAMP(roi_ymax - y_offset, cropped_ymin, 1);
    float cropped_width_n = cropped_xmax - cropped_xmin;
    float cropped_height_n = cropped_ymax - cropped_ymin;
    int cropped_width = int(cropped_width_n * hailo_mat->native_width());
    int cropped_height = int(cropped_height_n * hailo_mat->native_height());
    
    lpr_dbg("  quality_estimation: crop size=%dx%d (limits: w>%d, h>%d)", 
            cropped_width, cropped_height, CROP_WIDTH_LIMIT, CROP_HEIGHT_LIMIT);

    // If the cropepd image is too small then quality is zero
    if (cropped_width <= CROP_WIDTH_LIMIT || cropped_height <= CROP_HEIGHT_LIMIT)
    {
        lpr_dbg("  quality_estimation: FAIL - crop too small => returning -1.0");
        return -1.0;
    }

    // If it is not too small then we can make the crop
    HailoROIPtr crop_roi = std::make_shared<HailoROI>(HailoBBox(cropped_xmin, cropped_ymin, cropped_width_n, cropped_height_n));
    std::vector<cv::Mat> cropped_image_vec = hailo_mat->crop(crop_roi);
    if (cropped_image_vec.empty())
    {
        lpr_dbg("  quality_estimation: FAIL - empty crop => returning -1.0");
        return -1.0f;
    }

    // Convert image to BGR
    cv::Mat bgr_image;
    switch (hailo_mat->get_type())
    {
    case HAILO_MAT_YUY2:
    {
        cv::Mat cropped_image = cropped_image_vec[0];
        cv::Mat yuy2_image = cv::Mat(cropped_image.rows, cropped_image.cols * 2, CV_8UC2, (char *)cropped_image.data, cropped_image.step);
        cv::cvtColor(yuy2_image, bgr_image, cv::COLOR_YUV2BGR_YUY2);
        break;
    }
    case HAILO_MAT_NV12:
    {
        cv::Mat full_mat = cv::Mat(cropped_image_vec[0].rows + cropped_image_vec[1].rows, cropped_image_vec[0].cols, CV_8UC1);
        memcpy(full_mat.data, cropped_image_vec[0].data, cropped_image_vec[0].rows * cropped_image_vec[0].cols);
        memcpy(full_mat.data + cropped_image_vec[0].rows * cropped_image_vec[0].cols, cropped_image_vec[1].data, cropped_image_vec[1].rows * cropped_image_vec[1].cols);
        cv::cvtColor(full_mat, bgr_image, cv::COLOR_YUV2BGR_NV12);

        break;
    }
    default:
        bgr_image = cropped_image_vec[0];
        break;
    }

    if (bgr_image.empty() || bgr_image.cols <= 0 || bgr_image.rows <= 0)
    {
        lpr_dbg("  quality_estimation: FAIL - empty bgr_image => returning -1.0");
        return -1.0f;
    }

    // Resize the frame
    cv::Mat resized_image;
    cv::resize(bgr_image, resized_image, cv::Size(200, 40), 0, 0, cv::INTER_AREA);

    // Gaussian Blur
    cv::Mat gaussian_image;
    cv::GaussianBlur(resized_image, gaussian_image, cv::Size(3, 3), 0);

    // Convert to grayscale
    cv::Mat gray_image;
    cv::Mat gray_image_normalized;
    cv::cvtColor(gaussian_image, gray_image, cv::COLOR_BGR2GRAY);
    cv::normalize(gray_image, gray_image_normalized, 255, 0, cv::NORM_INF);

    // Compute the Laplacian of the gray image
    cv::Mat laplacian_image;
    cv::Laplacian(gray_image_normalized, laplacian_image, CV_64F);

    // Calculate the variance of edges
    cv::Scalar mean, stddev;
    cv::meanStdDev(laplacian_image, mean, stddev, cv::Mat());
    float variance = stddev.val[0] * stddev.val[0];
    return variance;
}

/**
 * @brief Returns a vector of HailoROIPtr to crop and resize.
 *        Specific to LPR pipelines, this function assumes that
 *        license plate ROIs are nested inside vehicle detection ROIs.
 *
 * @param image  -  cv::Mat
 *        The original image.
 *
 * @param roi  -  HailoROIPtr
 *        The main ROI of this picture.
 *
 * @return std::vector<HailoROIPtr>
 *         vector of ROI's to crop and resize.
 */
std::vector<HailoROIPtr> license_plate_quality_estimation(std::shared_ptr<HailoMat> image, HailoROIPtr roi)
{
    std::vector<HailoROIPtr> crop_rois;
    float variance;
    lpr_log_settings();
    lpr_dbg("========== license_plate_quality_estimation: ENTER ==========");
    if (!image || !roi)
    {
        lpr_dbg("license_plate_quality_estimation: null image=%d roi=%d => EXIT", image ? 1 : 0, roi ? 1 : 0);
        return crop_rois;
    }
    lpr_dbg("license_plate_quality_estimation: image size=%dx%d, QUALITY_THRESHOLD=%.1f", 
            image->width(), image->height(), QUALITY_THRESHOLD);
    
    // Get all detections.
    std::vector<HailoDetectionPtr> vehicle_ptrs = hailo_common::get_hailo_detections(roi);
    lpr_dbg("license_plate_quality_estimation: total detections=%zu (looking for vehicles)", vehicle_ptrs.size());
    
    int veh_idx = 0;
    for (HailoDetectionPtr &vehicle : vehicle_ptrs)
    {
        std::string veh_label = vehicle->get_label();
        lpr_dbg("license_plate_quality_estimation: [veh %d] label='%s' conf=%.3f", 
                veh_idx, veh_label.c_str(), vehicle->get_confidence());
        
        if (!is_vehicle_label(veh_label))
        {
            lpr_dbg("license_plate_quality_estimation: [veh %d] SKIP - not a vehicle", veh_idx);
            veh_idx++;
            continue;
        }
        
        // For each detection, check the inner detections
        std::vector<HailoDetectionPtr> license_plate_ptrs = hailo_common::get_hailo_detections(vehicle);
        lpr_dbg("license_plate_quality_estimation: [veh %d] nested detections=%zu (looking for LICENSE_PLATE_LABEL='%s')", 
                veh_idx, license_plate_ptrs.size(), LICENSE_PLATE_LABEL);
        
        int lp_idx = 0;
        for (HailoDetectionPtr &license_plate : license_plate_ptrs)
        {
            std::string lp_label = license_plate->get_label();
            float lp_conf = license_plate->get_confidence();
            HailoBBox lp_bbox = license_plate->get_bbox();
            
            lpr_dbg("license_plate_quality_estimation: [veh %d][lp %d] label='%s' conf=%.3f bbox=[%.3f,%.3f,%.3f,%.3f]", 
                    veh_idx, lp_idx, lp_label.c_str(), lp_conf,
                    lp_bbox.xmin(), lp_bbox.ymin(), lp_bbox.width(), lp_bbox.height());
            
            if (LICENSE_PLATE_LABEL != lp_label)
            {
                lpr_dbg("license_plate_quality_estimation: [veh %d][lp %d] SKIP - label mismatch (got '%s', expected '%s')", 
                        veh_idx, lp_idx, lp_label.c_str(), LICENSE_PLATE_LABEL);
                lp_idx++;
                continue;
            }
            
            HailoBBox license_plate_box = hailo_common::create_flattened_bbox(license_plate->get_bbox(), license_plate->get_scaling_bbox());
            lpr_dbg("license_plate_quality_estimation: [veh %d][lp %d] flattened bbox=[%.3f,%.3f,%.3f,%.3f]", 
                    veh_idx, lp_idx, license_plate_box.xmin(), license_plate_box.ymin(), 
                    license_plate_box.width(), license_plate_box.height());

            // Get the variance of the image, only add ROIs that are above threshold.
            variance = quality_estimation(image, license_plate_box, CROP_RATIO);
            lpr_dbg("license_plate_quality_estimation: [veh %d][lp %d] quality variance=%.3f (threshold=%.1f)", 
                    veh_idx, lp_idx, variance, QUALITY_THRESHOLD);

            if (variance >= QUALITY_THRESHOLD)
            {
                lpr_dbg("license_plate_quality_estimation: [veh %d][lp %d] KEEP - good quality, sending to OCR", veh_idx, lp_idx);
                int track_id = get_tracking_id(vehicle);
                int crop_id = g_lp_crop_counter.fetch_add(1);
                save_crop_image(image, license_plate_box, "lp_to_ocr", crop_id, track_id);
                track_ocr_lp_to_ocr(track_id);
                crop_rois.emplace_back(license_plate);
            }
            else
            {
                lpr_dbg("license_plate_quality_estimation: [veh %d][lp %d] REMOVE - quality too low (%.3f < %.1f)", 
                        veh_idx, lp_idx, variance, QUALITY_THRESHOLD);
                vehicle->remove_object(license_plate); // If it is not a good license plate, then remove it!
            }
            lp_idx++;
        }
        veh_idx++;
    }
    lpr_dbg("license_plate_quality_estimation: result crop_rois=%zu (plates to send to OCR)", crop_rois.size());
    lpr_dbg("========== license_plate_quality_estimation: EXIT ==========");
    return crop_rois;
}

/**
 * @brief Returns a vector of HailoROIPtr to crop and resize - all license plates
 *        without any quality filtering. This is a simplified version of
 *        license_plate_quality_estimation that sends all detected plates to OCR.
 *
 * @param image  -  cv::Mat
 *        The original image.
 *
 * @param roi  -  HailoROIPtr
 *        The main ROI of this picture.
 *
 * @return std::vector<HailoROIPtr>
 *         vector of ROI's to crop and resize.
 */
std::vector<HailoROIPtr> license_plate_no_quality(std::shared_ptr<HailoMat> image, HailoROIPtr roi)
{
    lpr_log_settings();
    std::vector<HailoROIPtr> crop_rois;
    lpr_dbg("========== license_plate_no_quality: ENTER ==========");
    if (!image || !roi)
    {
        lpr_dbg("license_plate_no_quality: null image=%d roi=%d => EXIT", image ? 1 : 0, roi ? 1 : 0);
        return crop_rois;
    }
    lpr_dbg("license_plate_no_quality: image size=%dx%d", image->width(), image->height());

    for (auto &entry : g_lp_track_age)
    {
        entry.second++;
    }

    // Get all detections (vehicles).
    std::vector<HailoDetectionPtr> vehicle_ptrs = hailo_common::get_hailo_detections(roi);
    lpr_dbg("license_plate_no_quality: total detections=%zu (looking for vehicles)", vehicle_ptrs.size());
    
    int veh_idx = 0;
    for (HailoDetectionPtr &vehicle : vehicle_ptrs)
    {
        std::string veh_label = vehicle->get_label();
        lpr_dbg("license_plate_no_quality: [veh %d] label='%s' conf=%.3f", 
                veh_idx, veh_label.c_str(), vehicle->get_confidence());
        
        if (!is_vehicle_label(veh_label))
        {
            lpr_dbg("license_plate_no_quality: [veh %d] SKIP - not a vehicle", veh_idx);
            veh_idx++;
            continue;
        }

        int track_id = get_tracking_id(vehicle);
        int track_age = LP_TRACK_COOLDOWN_FRAMES;
        if (track_id >= 0)
        {
            std::string plate;
            if (track_has_lpr(track_id, &plate))
            {
                lpr_dbg("license_plate_no_quality: [veh %d] SKIP - track_id=%d already has LP '%s'", veh_idx, track_id, plate.c_str());
                veh_idx++;
                continue;
            }

            // If tracker carried forward a final LP classification, honor it once and skip.
            bool tracker_has_lp = false;
            for (HailoClassificationPtr &cls : hailo_common::get_hailo_classifications(vehicle))
            {
                if (cls && cls->get_classification_type() == OCR_RESULT_LABEL)
                {
                    mark_track_lpr(track_id, cls->get_label());
                    track_ocr_result(track_id, cls->get_label());
                    lpr_dbg("license_plate_no_quality: [veh %d] SKIP - vehicle already classified with LP '%s'", veh_idx, cls->get_label().c_str());
                    tracker_has_lp = true;
                    break;
                }
            }
            if (tracker_has_lp)
            {
                veh_idx++;
                continue;
            }

            auto it_age = g_lp_track_age.find(track_id);
            track_age = (it_age != g_lp_track_age.end()) ? it_age->second : LP_TRACK_COOLDOWN_FRAMES;
            if (track_age < LP_TRACK_COOLDOWN_FRAMES)
            {
                lpr_dbg("license_plate_no_quality: [veh %d] SKIP - cooldown not met (age=%d/%d) for track_id=%d",
                        veh_idx, track_age, LP_TRACK_COOLDOWN_FRAMES, track_id);
                veh_idx++;
                continue;
            }
        }

        float vehicle_area = vehicle->get_bbox().width() * vehicle->get_bbox().height();
        HailoDetectionPtr best_plate;
        HailoBBox best_flat_bbox(0.0f, 0.0f, 0.0f, 0.0f);
        float best_blur = -1.0f;
        float best_rel_area = 0.0f;

        // For each vehicle, get all nested detections (license plates)
        std::vector<HailoDetectionPtr> license_plate_ptrs = hailo_common::get_hailo_detections(vehicle);
        lpr_dbg("license_plate_no_quality: [veh %d] nested detections=%zu (looking for LICENSE_PLATE_LABEL='%s')", 
                veh_idx, license_plate_ptrs.size(), LICENSE_PLATE_LABEL);
        
        int lp_idx = 0;
        for (HailoDetectionPtr &license_plate : license_plate_ptrs)
        {
            std::string lp_label = license_plate->get_label();
            float lp_conf = license_plate->get_confidence();
            HailoBBox lp_bbox = license_plate->get_bbox();
            
            lpr_dbg("license_plate_no_quality: [veh %d][lp %d] label='%s' conf=%.3f bbox=[%.3f,%.3f,%.3f,%.3f]", 
                    veh_idx, lp_idx, lp_label.c_str(), lp_conf,
                    lp_bbox.xmin(), lp_bbox.ymin(), lp_bbox.width(), lp_bbox.height());
            
            if (LICENSE_PLATE_LABEL != lp_label)
            {
                lpr_dbg("license_plate_no_quality: [veh %d][lp %d] SKIP - label mismatch (got '%s', expected '%s')", 
                        veh_idx, lp_idx, lp_label.c_str(), LICENSE_PLATE_LABEL);
                lp_idx++;
                continue;
            }

            HailoBBox lp_flat_bbox = hailo_common::create_flattened_bbox(lp_bbox, license_plate->get_scaling_bbox());
            float lp_area = lp_flat_bbox.width() * lp_flat_bbox.height();
            float rel_area = (vehicle_area > 0.0f) ? (lp_area / vehicle_area) : 0.0f;
            if (rel_area < MIN_LP_REL_AREA)
            {
                lpr_dbg("license_plate_no_quality: [veh %d][lp %d] SKIP - plate too small relative to vehicle (rel_area=%.4f < %.4f)",
                        veh_idx, lp_idx, rel_area, MIN_LP_REL_AREA);
                lp_idx++;
                continue;
            }

            float blur_score = quality_estimation(image, lp_flat_bbox, CROP_RATIO);
            if (blur_score < QUALITY_THRESHOLD)
            {
                lpr_dbg("license_plate_no_quality: [veh %d][lp %d] SKIP - blur variance too low (%.3f < %.1f)", 
                        veh_idx, lp_idx, blur_score, QUALITY_THRESHOLD);
                lp_idx++;
                continue;
            }

            bool better_candidate = (blur_score > best_blur) || ((blur_score == best_blur) && (rel_area > best_rel_area));
            if (better_candidate)
            {
                best_plate = license_plate;
                best_flat_bbox = lp_flat_bbox;
                best_blur = blur_score;
                best_rel_area = rel_area;
            }
            lp_idx++;
        }

        if (best_plate)
        {
            lpr_dbg("license_plate_no_quality: [veh %d] KEEP best LP - blur=%.3f rel_area=%.4f track_age=%d track_id=%d", 
                    veh_idx, best_blur, best_rel_area, track_age, track_id);
            attach_tracking_id_if_missing(best_plate, track_id);

            int crop_id = g_lp_crop_counter.fetch_add(1);
            save_crop_image(image, best_flat_bbox, "lp_to_ocr", crop_id, track_id);
            track_ocr_lp_to_ocr(track_id);
            crop_rois.emplace_back(best_plate);

            if (track_id >= 0)
                g_lp_track_age[track_id] = 0;
        }
        else if (track_id >= 0 && g_lp_track_age.find(track_id) == g_lp_track_age.end())
        {
            track_ocr_check_missing(track_id, "no_lp_to_ocr");
            // Track was seen but had no valid LP - start its age so it can be revisited.
            g_lp_track_age[track_id] = LP_TRACK_COOLDOWN_FRAMES;
        }
        veh_idx++;
    }
    lpr_dbg("license_plate_no_quality: result crop_rois=%zu (plates to send to OCR)", crop_rois.size());
    lpr_dbg("========== license_plate_no_quality: EXIT ==========");
    return crop_rois;
}

std::vector<HailoROIPtr> license_plate_no_quality_op(std::shared_ptr<HailoMat> image, HailoROIPtr roi)
{
    return license_plate_no_quality(image, roi);
}

/**
 * @brief Returns a vector of HailoROIPtr to crop and resize - all license plates
 *        without cooldown or blur filtering. Intended for debug runs where every
 *        possible LP crop should reach OCR.
 *
 * @param image  -  cv::Mat
 *        The original image.
 *
 * @param roi  -  HailoROIPtr
 *        The main ROI of this picture.
 *
 * @return std::vector<HailoROIPtr>
 *         vector of ROI's to crop and resize.
 */
std::vector<HailoROIPtr> license_plate_no_quality_no_gates(std::shared_ptr<HailoMat> image, HailoROIPtr roi)
{
    lpr_log_settings();
    std::vector<HailoROIPtr> crop_rois;
    lpr_dbg("========== license_plate_no_quality_no_gates: ENTER ==========");
    if (!image || !roi)
    {
        lpr_dbg("license_plate_no_quality_no_gates: null image=%d roi=%d => EXIT", image ? 1 : 0, roi ? 1 : 0);
        return crop_rois;
    }
    lpr_dbg("license_plate_no_quality_no_gates: image size=%dx%d", image->width(), image->height());

    // Get all detections (vehicles).
    std::vector<HailoDetectionPtr> vehicle_ptrs = hailo_common::get_hailo_detections(roi);
    lpr_dbg("license_plate_no_quality_no_gates: total detections=%zu (looking for vehicles)", vehicle_ptrs.size());

    int veh_idx = 0;
    for (HailoDetectionPtr &vehicle : vehicle_ptrs)
    {
        std::string veh_label = vehicle->get_label();
        lpr_dbg("license_plate_no_quality_no_gates: [veh %d] label='%s' conf=%.3f",
                veh_idx, veh_label.c_str(), vehicle->get_confidence());

        if (!is_vehicle_label(veh_label))
        {
            lpr_dbg("license_plate_no_quality_no_gates: [veh %d] SKIP - not a vehicle", veh_idx);
            veh_idx++;
            continue;
        }

        int track_id = get_tracking_id(vehicle);
        if (track_id >= 0)
        {
            std::string plate;
            if (track_has_lpr(track_id, &plate))
            {
                lpr_dbg("license_plate_no_quality_no_gates: [veh %d] SKIP - track_id=%d already has LP '%s'",
                        veh_idx, track_id, plate.c_str());
                veh_idx++;
                continue;
            }
        }

        float vehicle_area = vehicle->get_bbox().width() * vehicle->get_bbox().height();
        HailoDetectionPtr best_plate;
        HailoBBox best_flat_bbox(0.0f, 0.0f, 0.0f, 0.0f);
        float best_rel_area = 0.0f;

        // For each vehicle, get all nested detections (license plates)
        std::vector<HailoDetectionPtr> license_plate_ptrs = hailo_common::get_hailo_detections(vehicle);
        lpr_dbg("license_plate_no_quality_no_gates: [veh %d] nested detections=%zu (looking for LICENSE_PLATE_LABEL='%s')",
                veh_idx, license_plate_ptrs.size(), LICENSE_PLATE_LABEL);

        int lp_idx = 0;
        for (HailoDetectionPtr &license_plate : license_plate_ptrs)
        {
            std::string lp_label = license_plate->get_label();
            float lp_conf = license_plate->get_confidence();
            HailoBBox lp_bbox = license_plate->get_bbox();

            lpr_dbg("license_plate_no_quality_no_gates: [veh %d][lp %d] label='%s' conf=%.3f bbox=[%.3f,%.3f,%.3f,%.3f]",
                    veh_idx, lp_idx, lp_label.c_str(), lp_conf,
                    lp_bbox.xmin(), lp_bbox.ymin(), lp_bbox.width(), lp_bbox.height());

            if (LICENSE_PLATE_LABEL != lp_label)
            {
                lpr_dbg("license_plate_no_quality_no_gates: [veh %d][lp %d] SKIP - label mismatch (got '%s', expected '%s')",
                        veh_idx, lp_idx, lp_label.c_str(), LICENSE_PLATE_LABEL);
                lp_idx++;
                continue;
            }

            HailoBBox lp_flat_bbox = hailo_common::create_flattened_bbox(lp_bbox, license_plate->get_scaling_bbox());
            float lp_area = lp_flat_bbox.width() * lp_flat_bbox.height();
            float rel_area = (vehicle_area > 0.0f) ? (lp_area / vehicle_area) : 0.0f;
            if (rel_area < MIN_LP_REL_AREA)
            {
                lpr_dbg("license_plate_no_quality_no_gates: [veh %d][lp %d] SKIP - plate too small relative to vehicle (rel_area=%.4f < %.4f)",
                        veh_idx, lp_idx, rel_area, MIN_LP_REL_AREA);
                lp_idx++;
                continue;
            }

            bool better_candidate = rel_area > best_rel_area;
            if (better_candidate)
            {
                best_plate = license_plate;
                best_flat_bbox = lp_flat_bbox;
                best_rel_area = rel_area;
            }
            lp_idx++;
        }

        if (best_plate)
        {
            lpr_dbg("license_plate_no_quality_no_gates: [veh %d] KEEP best LP - rel_area=%.4f track_id=%d",
                    veh_idx, best_rel_area, track_id);
            attach_tracking_id_if_missing(best_plate, track_id);

            int crop_id = g_lp_crop_counter.fetch_add(1);
            save_crop_image(image, best_flat_bbox, "lp_to_ocr", crop_id, track_id);
            track_ocr_lp_to_ocr(track_id);
            crop_rois.emplace_back(best_plate);
        }
        veh_idx++;
    }
    lpr_dbg("license_plate_no_quality_no_gates: result crop_rois=%zu (plates to send to OCR)", crop_rois.size());
    lpr_dbg("========== license_plate_no_quality_no_gates: EXIT ==========");
    return crop_rois;
}

std::vector<HailoROIPtr> license_plate_no_quality_no_gates_op(std::shared_ptr<HailoMat> image, HailoROIPtr roi)
{
    return license_plate_no_quality_no_gates(image, roi);
}

/**
 * @brief Returns a vector of HailoROIPtr to crop and resize.
 *        Specific to LP-only pipelines, this function uses top-level
 *        license plate detections (no vehicles required).
 *
 * @param image  -  cv::Mat
 *        The original image.
 *
 * @param roi  -  HailoROIPtr
 *        The main ROI of this picture.
 *
 * @return std::vector<HailoROIPtr>
 *         vector of ROI's to crop and resize.
 */
std::vector<HailoROIPtr> license_plate_fullframe(std::shared_ptr<HailoMat> image, HailoROIPtr roi)
{
    lpr_log_settings();
    std::vector<HailoROIPtr> crop_rois;
    lpr_dbg("========== license_plate_fullframe: ENTER ==========");
    if (!image || !roi)
    {
        lpr_dbg("license_plate_fullframe: null image=%d roi=%d => EXIT", image ? 1 : 0, roi ? 1 : 0);
        return crop_rois;
    }
    lpr_dbg("license_plate_fullframe: image size=%dx%d", image->width(), image->height());

    // Top-level detections are expected to be license plates.
    std::vector<HailoDetectionPtr> detections_ptrs = hailo_common::get_hailo_detections(roi);
    lpr_dbg("license_plate_fullframe: total detections=%zu", detections_ptrs.size());

    int lp_idx = 0;
    for (HailoDetectionPtr &license_plate : detections_ptrs)
    {
        std::string lp_label = license_plate->get_label();
        float lp_conf = license_plate->get_confidence();
        HailoBBox lp_bbox = license_plate->get_bbox();

        lpr_dbg("license_plate_fullframe: [lp %d] label='%s' conf=%.3f bbox=[%.3f,%.3f,%.3f,%.3f]",
                lp_idx, lp_label.c_str(), lp_conf,
                lp_bbox.xmin(), lp_bbox.ymin(), lp_bbox.width(), lp_bbox.height());

        if (LICENSE_PLATE_LABEL != lp_label)
        {
            lpr_dbg("license_plate_fullframe: [lp %d] SKIP - label mismatch (got '%s', expected '%s')",
                    lp_idx, lp_label.c_str(), LICENSE_PLATE_LABEL);
            lp_idx++;
            continue;
        }

        int track_id = get_tracking_id(license_plate);
        std::string plate_text;
        if (track_has_lpr(track_id, &plate_text))
        {
            lpr_dbg("license_plate_fullframe: [lp %d] SKIP - track_id=%d already has LP '%s'", lp_idx, track_id, plate_text.c_str());
            lp_idx++;
            continue;
        }

        bool has_found_lp = false;
        for (auto &obj : license_plate->get_objects_typed(HAILO_CLASSIFICATION))
        {
            auto cls = std::dynamic_pointer_cast<HailoClassification>(obj);
            if (cls && cls->get_classification_type() == "found_lp")
            {
                has_found_lp = true;
                break;
            }
        }
        if (has_found_lp)
        {
            lpr_dbg("license_plate_fullframe: [lp %d] SKIP - already has found_lp", lp_idx);
            lp_idx++;
            continue;
        }

        float pad_x = lp_bbox.width() * FULLFRAME_PAD_RATIO;
        float pad_y = lp_bbox.height() * FULLFRAME_PAD_RATIO;
        float xmin = std::max(0.0f, lp_bbox.xmin() - pad_x);
        float ymin = std::max(0.0f, lp_bbox.ymin() - pad_y);
        float xmax = std::min(1.0f, lp_bbox.xmax() + pad_x);
        float ymax = std::min(1.0f, lp_bbox.ymax() + pad_y);
        float padded_w = std::max(0.0f, xmax - xmin);
        float padded_h = std::max(0.0f, ymax - ymin);
        HailoBBox padded_bbox = HailoBBox(xmin, ymin, padded_w, padded_h);
        license_plate->set_bbox(padded_bbox);
        lpr_dbg(
            "license_plate_fullframe: [lp %d] padded bbox=[%.3f,%.3f,%.3f,%.3f]",
            lp_idx, padded_bbox.xmin(), padded_bbox.ymin(), padded_bbox.width(), padded_bbox.height());
        track_id = get_tracking_id(license_plate);
        int crop_id = g_lp_crop_counter.fetch_add(1);
        save_crop_image(image, padded_bbox, "lp_fullframe", crop_id, track_id);
        track_ocr_lp_to_ocr(track_id);
        crop_rois.emplace_back(license_plate);
        lp_idx++;
    }

    lpr_dbg("license_plate_fullframe: result crop_rois=%zu (plates to send to OCR)", crop_rois.size());
    lpr_dbg("========== license_plate_fullframe: EXIT ==========");
    return crop_rois;
}

/**
 * @brief Returns a vector of HailoROIPtr to crop and resize.
 *        Specific to LPR pipelines, this function searches if
 *        a detected vehicle has an OCR classification. If not,
 *        then it is submitted for cropping.
 *        This function also throws out car detections that are not yet
 *        fully in the image.
 *
 * @param image  -  cv::Mat
 *        The original image.
 *
 * @param roi  -  HailoROIPtr
 *        The main ROI of this picture.
 *
 * @return std::vector<HailoROIPtr>
 *         vector of ROI's to crop and resize.
 */
std::vector<HailoROIPtr> vehicles_without_ocr(std::shared_ptr<HailoMat> image, HailoROIPtr roi)
{
    std::vector<HailoROIPtr> crop_rois;
    bool has_ocr = false;
    lpr_log_settings();
    lpr_dbg("========== vehicles_without_ocr: ENTER ==========");
    if (!image || !roi)
    {
        lpr_dbg("vehicles_without_ocr: null image=%d roi=%d => EXIT", image ? 1 : 0, roi ? 1 : 0);
        return crop_rois;
    }
    lpr_dbg("vehicles_without_ocr: image size=%dx%d", image->width(), image->height());
    
    // Get all detections.
    std::vector<HailoDetectionPtr> detections_ptrs = hailo_common::get_hailo_detections(roi);
    lpr_dbg("vehicles_without_ocr: total detections=%zu", detections_ptrs.size());
    
    int det_idx = 0;
    for (HailoDetectionPtr &detection : detections_ptrs)
    {
        std::string label = detection->get_label();
        
        if (!is_vehicle_label(label))
        {
            det_idx++;
            continue;
        }
        
        HailoBBox vehicle_bbox = detection->get_bbox();

        if (!camera_angle_accepts_vehicle(vehicle_bbox))
        {
            lpr_dbg("vehicles_without_ocr: [%d] SKIP - camera angle rejects top-third vehicle (center_y=%.3f)", 
                    det_idx, (vehicle_bbox.ymin() + vehicle_bbox.ymax()) * 0.5f);
            det_idx++;
            continue;
        }

        // If the bbox is not yet in the image, then throw it out
        if ((vehicle_bbox.xmin() < 0.0) ||
            (vehicle_bbox.xmax() > 1.0) ||
            (vehicle_bbox.ymin() < 0.0) ||
            (vehicle_bbox.ymax() > 1.0))
        {
            lpr_dbg("vehicles_without_ocr: [%d] SKIP - bbox out of bounds [xmin=%.3f,xmax=%.3f,ymin=%.3f,ymax=%.3f]", 
                    det_idx, vehicle_bbox.xmin(), vehicle_bbox.xmax(), vehicle_bbox.ymin(), vehicle_bbox.ymax());
            det_idx++;
            continue;
        }

        int track_id = get_tracking_id(detection);
        if (track_id >= 0)
        {
            std::string plate;
            if (track_has_lpr(track_id, &plate))
            {
                lpr_dbg("vehicles_without_ocr: [%d] SKIP - track_id=%d already has LP '%s'", det_idx, track_id, plate.c_str());
                det_idx++;
                continue;
            }

            int seen = ++g_vehicle_track_seen[track_id];
            if (seen <= VEHICLE_WARMUP_FRAMES)
            {
                lpr_dbg("vehicles_without_ocr: [%d] SKIP - warmup frame %d/%d for track_id=%d",
                        det_idx, seen, VEHICLE_WARMUP_FRAMES, track_id);
                det_idx++;
                continue;
            }
        }

        has_ocr = false;
        // For each detection, check the classifications
        std::vector<HailoClassificationPtr> vehicle_classifications = hailo_common::get_hailo_classifications(detection);
        
        for (HailoClassificationPtr &classification : vehicle_classifications)
        {
            std::string cls_type = classification->get_classification_type();
            if (OCR_RESULT_LABEL == cls_type)
            {
                mark_track_lpr(track_id, classification->get_label());
                track_ocr_result(track_id, classification->get_label());
                has_ocr = true;
                break;
            }
        }
        
        if (!has_ocr)
        {
            lpr_dbg("vehicles_without_ocr: [%d] ENQUEUE - vehicle needs LP detection", det_idx);
            
            // Save vehicle crop for debugging (before it goes to LP detection)
            int crop_id = g_vehicle_crop_counter.fetch_add(1);
            track_ocr_vehicle_crop(track_id);
            save_crop_image(image, vehicle_bbox, "vehicle_to_lp_det", crop_id, track_id);
            
            crop_rois.emplace_back(detection);
        }
        else
        {
        }
        det_idx++;
    }
    lpr_dbg("vehicles_without_ocr: result crop_rois=%zu", crop_rois.size());
    lpr_dbg("========== vehicles_without_ocr: EXIT ==========");
    return crop_rois;
}

std::vector<HailoROIPtr> vehicles_without_ocr_op(std::shared_ptr<HailoMat> image, HailoROIPtr roi)
{
    return vehicles_without_ocr(image, roi);
}

/**
 * @brief Returns a vector of HailoROIPtr to crop and resize.
 *        Same as vehicles_without_ocr, but also gates vehicles by a configurable ROI.
 *
 * @param image  -  cv::Mat
 *        The original image.
 *
 * @param roi  -  HailoROIPtr
 *        The main ROI of this picture.
 *
 * @return std::vector<HailoROIPtr>
 *         vector of ROI's to crop and resize.
 */
std::vector<HailoROIPtr> vehicles_without_ocr_roi(std::shared_ptr<HailoMat> image, HailoROIPtr roi)
{
    std::vector<HailoROIPtr> crop_rois;
    bool has_ocr = false;
    lpr_log_settings();
    lpr_dbg("========== vehicles_without_ocr_roi: ENTER ==========");
    if (!image || !roi)
    {
        lpr_dbg("vehicles_without_ocr_roi: null image=%d roi=%d => EXIT", image ? 1 : 0, roi ? 1 : 0);
        return crop_rois;
    }
    lpr_dbg("vehicles_without_ocr_roi: image size=%dx%d", image->width(), image->height());

    // Get all detections.
    std::vector<HailoDetectionPtr> detections_ptrs = hailo_common::get_hailo_detections(roi);
    lpr_dbg("vehicles_without_ocr_roi: total detections=%zu", detections_ptrs.size());

    int det_idx = 0;
    for (HailoDetectionPtr &detection : detections_ptrs)
    {
        std::string label = detection->get_label();

        if (!is_vehicle_label(label))
        {
            det_idx++;
            continue;
        }

        HailoBBox vehicle_bbox = detection->get_bbox();

        if (!camera_angle_accepts_vehicle(vehicle_bbox))
        {
            lpr_dbg("vehicles_without_ocr_roi: [%d] SKIP - camera angle rejects top-third vehicle (center_y=%.3f)",
                    det_idx, (vehicle_bbox.ymin() + vehicle_bbox.ymax()) * 0.5f);
            det_idx++;
            continue;
        }

        if (!vehicle_roi_accepts_bbox(vehicle_bbox))
        {
            lpr_dbg("vehicles_without_ocr_roi: [%d] SKIP - ROI gate rejected vehicle", det_idx);
            det_idx++;
            continue;
        }

        // If the bbox is not yet in the image, then throw it out
        if ((vehicle_bbox.xmin() < 0.0) ||
            (vehicle_bbox.xmax() > 1.0) ||
            (vehicle_bbox.ymin() < 0.0) ||
            (vehicle_bbox.ymax() > 1.0))
        {
            lpr_dbg("vehicles_without_ocr_roi: [%d] SKIP - bbox out of bounds [xmin=%.3f,xmax=%.3f,ymin=%.3f,ymax=%.3f]",
                    det_idx, vehicle_bbox.xmin(), vehicle_bbox.xmax(), vehicle_bbox.ymin(), vehicle_bbox.ymax());
            det_idx++;
            continue;
        }

        int track_id = get_tracking_id(detection);
        if (track_id >= 0)
        {
            std::string plate;
            if (track_has_lpr(track_id, &plate))
            {
                lpr_dbg("vehicles_without_ocr_roi: [%d] SKIP - track_id=%d already has LP '%s'", det_idx, track_id, plate.c_str());
                det_idx++;
                continue;
            }

            int seen = ++g_vehicle_track_seen[track_id];
            if (seen <= VEHICLE_WARMUP_FRAMES)
            {
                lpr_dbg("vehicles_without_ocr_roi: [%d] SKIP - warmup frame %d/%d for track_id=%d",
                        det_idx, seen, VEHICLE_WARMUP_FRAMES, track_id);
                det_idx++;
                continue;
            }
        }

        has_ocr = false;
        // For each detection, check the classifications
        std::vector<HailoClassificationPtr> vehicle_classifications = hailo_common::get_hailo_classifications(detection);

        for (HailoClassificationPtr &classification : vehicle_classifications)
        {
            std::string cls_type = classification->get_classification_type();
            if (OCR_RESULT_LABEL == cls_type)
            {
                mark_track_lpr(track_id, classification->get_label());
                track_ocr_result(track_id, classification->get_label());
                has_ocr = true;
                break;
            }
        }

        if (!has_ocr)
        {
            lpr_dbg("vehicles_without_ocr_roi: [%d] ENQUEUE - vehicle needs LP detection", det_idx);

            // Save vehicle crop for debugging (before it goes to LP detection)
            int crop_id = g_vehicle_crop_counter.fetch_add(1);
            track_ocr_vehicle_crop(track_id);
            save_crop_image(image, vehicle_bbox, "vehicle_to_lp_det", crop_id, track_id);

            crop_rois.emplace_back(detection);
        }
        det_idx++;
    }
    lpr_dbg("vehicles_without_ocr_roi: result crop_rois=%zu", crop_rois.size());
    lpr_dbg("========== vehicles_without_ocr_roi: EXIT ==========");
    return crop_rois;
}
