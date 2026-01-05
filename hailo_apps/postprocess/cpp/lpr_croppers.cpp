/**
 * Copyright (c) 2021-2022 Hailo Technologies Ltd. All rights reserved.
 * Distributed under the LGPL license (https://www.gnu.org/licenses/old-licenses/lgpl-2.1.txt)
 **/
#include "lpr_croppers.hpp"
#include "lpr_roi.hpp"
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cctype>
#include <cmath>
#include <fstream>
#include <iostream>
#include <mutex>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>
#include <sys/stat.h>
#include <fcntl.h>
#include <sys/file.h>
#include <unistd.h>
#if __GNUC__ > 8
#include <filesystem>
namespace fs = std::filesystem;
#else
#include <experimental/filesystem>
namespace fs = std::experimental::filesystem;
#endif

#define VEHICLE_LABEL "vehicle"
#define LICENSE_PLATE_LABEL "license_plate"
#define OCR_RESULT_LABEL "lpr_result"

static constexpr float DEFAULT_MIN_VEHICLE_AREA = 0.01f;  // 1% of frame area

// LP Quality Check Defaults
static constexpr float DEFAULT_LP_MIN_WIDTH_PX = 20.0f;       // Minimum LP width in pixels
static constexpr float DEFAULT_LP_MIN_HEIGHT_PX = 8.0f;      // Minimum LP height in pixels
static constexpr float DEFAULT_LP_MAX_WIDTH_PX = 800.0f;      // Maximum LP width in pixels
static constexpr float DEFAULT_LP_MAX_HEIGHT_PX = 300.0f;     // Maximum LP height in pixels
static constexpr float DEFAULT_LP_MIN_ASPECT = 1.1f;          // Min aspect ratio (width/height) - typical LP is 2-5
static constexpr float DEFAULT_LP_MAX_ASPECT = 8.0f;          // Max aspect ratio
static constexpr float DEFAULT_LP_BLUR_THRESHOLD = 50.0f;     // Laplacian variance threshold (lower = blurry)
static constexpr float DEFAULT_LP_MIN_BRIGHTNESS = 20.0f;     // Min mean brightness (0-255), below = too dark
static constexpr float DEFAULT_LP_MAX_BRIGHTNESS = 235.0f;    // Max mean brightness (0-255), above = too bright
static constexpr float DEFAULT_LP_MIN_CONTRAST = 30.0f;       // Min std deviation of brightness
static constexpr float DEFAULT_LP_MIN_EDGE_DENSITY = 0.05f;   // Min edge pixel ratio (0-1)
static constexpr float DEFAULT_LP_PAD_X = 0.1f;
static constexpr float DEFAULT_LP_PAD_TOP = 0.2f;
static constexpr float DEFAULT_LP_PAD_BOTTOM = 0.5f;
static constexpr float MIN_LP_REL_AREA = 0.001f;  // Minimum LP area relative to vehicle area (0.1%)

static void lpr_dbg(const char *fmt, ...);

// Quality check result reasons
enum class LpQualityRejectReason
{
    PASSED = 0,
    TOO_SMALL,
    TOO_LARGE,
    BAD_ASPECT_RATIO,
    TOO_BLURRY,
    TOO_DARK,
    TOO_BRIGHT,
    LOW_CONTRAST,
    LOW_EDGE_DENSITY,
    OUTSIDE_ROI,
    EMPTY_CROP
};

static const char* quality_reason_str(LpQualityRejectReason reason)
{
    switch (reason)
    {
    case LpQualityRejectReason::PASSED: return "passed";
    case LpQualityRejectReason::TOO_SMALL: return "too_small";
    case LpQualityRejectReason::TOO_LARGE: return "too_large";
    case LpQualityRejectReason::BAD_ASPECT_RATIO: return "bad_aspect_ratio";
    case LpQualityRejectReason::TOO_BLURRY: return "too_blurry";
    case LpQualityRejectReason::TOO_DARK: return "too_dark";
    case LpQualityRejectReason::TOO_BRIGHT: return "too_bright";
    case LpQualityRejectReason::LOW_CONTRAST: return "low_contrast";
    case LpQualityRejectReason::LOW_EDGE_DENSITY: return "low_edge_density";
    case LpQualityRejectReason::OUTSIDE_ROI: return "outside_roi";
    case LpQualityRejectReason::EMPTY_CROP: return "empty_crop";
    default: return "unknown";
    }
}

struct LpQualityConfig
{
    // Size thresholds (in pixels)
    float min_width_px;
    float min_height_px;
    float max_width_px;
    float max_height_px;

    // Aspect ratio (width/height)
    float min_aspect;
    float max_aspect;

    // Blur detection (Laplacian variance)
    float blur_threshold;
    bool blur_check_enabled;

    // Exposure checks (brightness 0-255)
    float min_brightness;
    float max_brightness;
    bool exposure_check_enabled;

    // Contrast check (std deviation of brightness)
    float min_contrast;
    bool contrast_check_enabled;

    // Edge density check
    float min_edge_density;
    bool edge_check_enabled;

    // ROI check
    bool roi_check_enabled;

    // Padding for OCR
    float pad_x;
    float pad_top;
    float pad_bottom;

    // Master enable
    bool enabled;
};

struct LpQualityResult
{
    bool passed;
    LpQualityRejectReason reason;
    float blur_score;
    float brightness;
    float contrast;
    float edge_density;
    float aspect_ratio;
    int width_px;
    int height_px;
};

// Frame counters for unique filenames
static std::atomic<int> g_vehicle_crop_counter{0};
static std::atomic<int> g_lp_crop_counter{0};
static std::atomic<int> g_lp_frame_counter{0};

static std::unordered_map<int, std::string> g_lp_db; // track_id -> plate text
static std::mutex g_lp_db_mutex;
static std::unordered_set<int> g_lp_tracks_seen;
static bool g_lp_state_loaded = false;
static std::streamoff g_lpr_json_pos = 0;
static std::mutex g_lpr_json_read_mutex;
static std::string g_lpr_json_path;

static std::string json_escape(const std::string &in)
{
    std::string out;
    out.reserve(in.size());
    for (char c : in)
    {
        if (c == '"' || c == '\\')
            out.push_back('\\');
        out.push_back(c);
    }
    return out;
}

static std::string get_lpr_json_path()
{
    static std::once_flag init_flag;
    std::call_once(init_flag, []() {
        const char *env_path = std::getenv("HAILO_LPR_JSON");
        if (env_path && std::strlen(env_path) > 0)
        {
            g_lpr_json_path = env_path;
        }
        else
        {
            g_lpr_json_path = "hailo_apps/python/pipeline_apps/license_plate_recognition/lpr_database/lpr_tracks.jsonl";
        }
        try
        {
            fs::create_directories(fs::path(g_lpr_json_path).parent_path());
        }
        catch (...)
        {
        }
    });
    return g_lpr_json_path;
}

static void append_track_event(int track_id, bool has_lpr, const std::string &plate)
{
    if (track_id < 0)
        return;
    const std::string path = get_lpr_json_path();
    if (path.empty())
        return;

    int fd = ::open(path.c_str(), O_WRONLY | O_CREAT | O_APPEND, 0644);
    if (fd < 0)
        return;

    if (flock(fd, LOCK_EX) != 0)
    {
        ::close(fd);
        return;
    }

    FILE *f = fdopen(fd, "a");
    if (!f)
    {
        flock(fd, LOCK_UN);
        ::close(fd);
        return;
    }

    auto now_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                      std::chrono::system_clock::now().time_since_epoch())
                      .count();
    std::string escaped_plate = json_escape(plate);
    std::fprintf(f,
                 R"({"event":"upsert","track_id":%d,"has_lpr":%s,"lpr_result":"%s","timestamp":%lld})"
                 "\n",
                 track_id,
                 has_lpr ? "true" : "false",
                 escaped_plate.c_str(),
                 static_cast<long long>(now_ms));
    std::fflush(f);
    ::fsync(fileno(f));
    flock(fd, LOCK_UN);
    std::fclose(f); // closes fd
}

static bool parse_jsonl_int(const std::string &line, const std::string &key, int &out)
{
    auto pos = line.find("\"" + key + "\"");
    if (pos == std::string::npos)
        return false;
    pos = line.find(":", pos);
    if (pos == std::string::npos)
        return false;
    pos++;
    while (pos < line.size() && std::isspace(static_cast<unsigned char>(line[pos])))
        pos++;
    char *end = nullptr;
    long val = std::strtol(line.c_str() + pos, &end, 10);
    if (end == line.c_str() + pos)
        return false;
    out = static_cast<int>(val);
    return true;
}

static bool parse_jsonl_bool(const std::string &line, const std::string &key, bool &out)
{
    auto pos = line.find("\"" + key + "\"");
    if (pos == std::string::npos)
        return false;
    pos = line.find(":", pos);
    if (pos == std::string::npos)
        return false;
    pos++;
    while (pos < line.size() && std::isspace(static_cast<unsigned char>(line[pos])))
        pos++;
    if (line.compare(pos, 4, "true") == 0)
    {
        out = true;
        return true;
    }
    if (line.compare(pos, 5, "false") == 0)
    {
        out = false;
        return true;
    }
    return false;
}

static bool parse_jsonl_string(const std::string &line, const std::string &key, std::string &out)
{
    auto pos = line.find("\"" + key + "\"");
    if (pos == std::string::npos)
        return false;
    pos = line.find(":", pos);
    if (pos == std::string::npos)
        return false;
    pos = line.find("\"", pos);
    if (pos == std::string::npos)
        return false;
    pos++;
    auto end = line.find("\"", pos);
    if (end == std::string::npos)
        return false;
    out = line.substr(pos, end - pos);
    return true;
}

static void apply_jsonl_event(const std::string &line)
{
    std::string evt;
    if (!parse_jsonl_string(line, "event", evt))
        return;

    if (evt == "clear")
    {
        std::lock_guard<std::mutex> lock(g_lp_db_mutex);
        g_lp_db.clear();
        g_lp_tracks_seen.clear();
        return;
    }

    int track_id = -1;
    if (!parse_jsonl_int(line, "track_id", track_id))
        return;

    if (evt == "delete")
    {
        std::lock_guard<std::mutex> lock(g_lp_db_mutex);
        g_lp_db.erase(track_id);
        g_lp_tracks_seen.erase(track_id);
        return;
    }

    if (evt == "upsert")
    {
        bool has_lpr = false;
        parse_jsonl_bool(line, "has_lpr", has_lpr);
        std::string plate;
        parse_jsonl_string(line, "lpr_result", plate);
        std::lock_guard<std::mutex> lock(g_lp_db_mutex);
        g_lp_tracks_seen.insert(track_id);
        if (has_lpr)
        {
            g_lp_db[track_id] = plate;
        }
        return;
    }
}

static void load_lpr_state_from_jsonl()
{
    if (g_lp_state_loaded)
        return;
    g_lp_state_loaded = true;
    const std::string path = get_lpr_json_path();
    std::ifstream f(path);
    if (!f.is_open())
        return;
    std::string line;
    while (std::getline(f, line))
    {
        apply_jsonl_event(line);
    }
}

static void refresh_lpr_state_from_jsonl()
{
    const std::string path = get_lpr_json_path();
    std::lock_guard<std::mutex> lock(g_lpr_json_read_mutex);
    std::ifstream f(path);
    if (!f.is_open())
        return;
    if (g_lpr_json_pos > 0)
    {
        f.seekg(g_lpr_json_pos);
    }
    std::string line;
    while (std::getline(f, line))
    {
        apply_jsonl_event(line);
    }
    std::streamoff pos = f.tellg();
    if (pos != -1)
    {
        g_lpr_json_pos = pos;
    }
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

static bool track_seen(int track_id)
{
    std::lock_guard<std::mutex> lock(g_lp_db_mutex);
    return g_lp_tracks_seen.find(track_id) != g_lp_tracks_seen.end();
}

static void mark_track_seen(int track_id)
{
    if (track_id < 0)
        return;
    std::lock_guard<std::mutex> lock(g_lp_db_mutex);
    auto inserted = g_lp_tracks_seen.insert(track_id);
    if (inserted.second)
    {
        append_track_event(track_id, false, "");
    }
}

static bool point_in_polygon(float x, float y, const std::array<LprRoiPoint, 4> &polygon)
{
    bool inside = false;
    size_t count = polygon.size();
    for (size_t i = 0, j = count - 1; i < count; j = i++)
    {
        float xi = polygon[i].x;
        float yi = polygon[i].y;
        float xj = polygon[j].x;
        float yj = polygon[j].y;
        bool intersect = ((yi > y) != (yj > y)) &&
                         (x < (xj - xi) * (y - yi) / (yj - yi + 1e-6f) + xi);
        if (intersect)
            inside = !inside;
    }
    return inside;
}

static bool bbox_fully_inside_polygon(const HailoBBox &bbox, const std::array<LprRoiPoint, 4> &polygon)
{
    return point_in_polygon(bbox.xmin(), bbox.ymin(), polygon) &&
           point_in_polygon(bbox.xmax(), bbox.ymin(), polygon) &&
           point_in_polygon(bbox.xmax(), bbox.ymax(), polygon) &&
           point_in_polygon(bbox.xmin(), bbox.ymax(), polygon);
}

static bool vehicle_inside_roi(const HailoBBox &vehicle_bbox)
{
    LprRoiConfig config = get_lpr_vehicle_roi_config();
    if (!config.enabled)
        return true;
    return bbox_fully_inside_polygon(vehicle_bbox, lpr_rect_to_polygon(config.rect));
}

static bool lpr_debug_enabled()
{
    static int enabled = -1;
    if (enabled == -1)
    {
        const char *val = std::getenv("HAILO_LPR_DEBUG");
        // Default OFF unless explicitly enabled
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

static float get_min_vehicle_area()
{
    static float min_area = -1.0f;
    if (min_area < 0.0f)
    {
        const char *val = std::getenv("HAILO_LPR_MIN_VEHICLE_AREA");
        if (val && val[0] != '\0')
        {
            char *end = nullptr;
            float parsed = std::strtof(val, &end);
            min_area = (end != val && parsed >= 0.0f) ? parsed : DEFAULT_MIN_VEHICLE_AREA;
        }
        else
        {
            min_area = DEFAULT_MIN_VEHICLE_AREA;
        }
    }
    return min_area;
}

static float parse_env_float(const char *env_name, float default_val)
{
    const char *val = std::getenv(env_name);
    if (val && val[0] != '\0')
    {
        char *end = nullptr;
        float parsed = std::strtof(val, &end);
        if (end != val)
            return parsed;
    }
    return default_val;
}

static bool parse_env_bool(const char *env_name, bool default_val)
{
    const char *val = std::getenv(env_name);
    if (val && val[0] != '\0')
    {
        if (val[0] == '1' || val[0] == 't' || val[0] == 'T' || val[0] == 'y' || val[0] == 'Y')
            return true;
        if (val[0] == '0' || val[0] == 'f' || val[0] == 'F' || val[0] == 'n' || val[0] == 'N')
            return false;
    }
    return default_val;
}

static LpQualityConfig get_lp_quality_config()
{
    static bool initialized = false;
    static LpQualityConfig config;
    if (!initialized)
    {
        // Size thresholds
        config.min_width_px = parse_env_float("HAILO_LP_MIN_WIDTH_PX", DEFAULT_LP_MIN_WIDTH_PX);
        config.min_height_px = parse_env_float("HAILO_LP_MIN_HEIGHT_PX", DEFAULT_LP_MIN_HEIGHT_PX);
        config.max_width_px = parse_env_float("HAILO_LP_MAX_WIDTH_PX", DEFAULT_LP_MAX_WIDTH_PX);
        config.max_height_px = parse_env_float("HAILO_LP_MAX_HEIGHT_PX", DEFAULT_LP_MAX_HEIGHT_PX);

        // Aspect ratio
        config.min_aspect = parse_env_float("HAILO_LP_MIN_ASPECT", DEFAULT_LP_MIN_ASPECT);
        config.max_aspect = parse_env_float("HAILO_LP_MAX_ASPECT", DEFAULT_LP_MAX_ASPECT);

        // Blur detection
        config.blur_threshold = parse_env_float("HAILO_LP_BLUR_THRESHOLD", DEFAULT_LP_BLUR_THRESHOLD);
        config.blur_check_enabled = parse_env_bool("HAILO_LP_BLUR_CHECK", true);

        // Exposure checks
        config.min_brightness = parse_env_float("HAILO_LP_MIN_BRIGHTNESS", DEFAULT_LP_MIN_BRIGHTNESS);
        config.max_brightness = parse_env_float("HAILO_LP_MAX_BRIGHTNESS", DEFAULT_LP_MAX_BRIGHTNESS);
        config.exposure_check_enabled = parse_env_bool("HAILO_LP_EXPOSURE_CHECK", true);

        // Contrast check
        config.min_contrast = parse_env_float("HAILO_LP_MIN_CONTRAST", DEFAULT_LP_MIN_CONTRAST);
        config.contrast_check_enabled = parse_env_bool("HAILO_LP_CONTRAST_CHECK", true);

        // Edge density check
        config.min_edge_density = parse_env_float("HAILO_LP_MIN_EDGE_DENSITY", DEFAULT_LP_MIN_EDGE_DENSITY);
        config.edge_check_enabled = parse_env_bool("HAILO_LP_EDGE_CHECK", true);

        // ROI check
        config.roi_check_enabled = parse_env_bool("HAILO_LP_ROI_CHECK", true);

        // Padding
        config.pad_x = parse_env_float("HAILO_LP_PAD_X", DEFAULT_LP_PAD_X);
        config.pad_top = parse_env_float("HAILO_LP_PAD_TOP", DEFAULT_LP_PAD_TOP);
        config.pad_bottom = parse_env_float("HAILO_LP_PAD_BOTTOM", DEFAULT_LP_PAD_BOTTOM);

        // Master enable - defaults to true now
        config.enabled = parse_env_bool("HAILO_LP_QUALITY_ENABLED", true);

        initialized = true;
    }
    return config;
}

// ============================================================================
// LP Quality Check Functions
// ============================================================================

/**
 * Calculate blur score using Laplacian variance.
 * Higher value = sharper image, lower value = blurry.
 */
static float calculate_blur_score(const cv::Mat &gray_image)
{
    if (gray_image.empty())
        return 0.0f;

    cv::Mat laplacian;
    cv::Laplacian(gray_image, laplacian, CV_64F);

    cv::Scalar mean, stddev;
    cv::meanStdDev(laplacian, mean, stddev);

    // Variance of Laplacian
    return static_cast<float>(stddev[0] * stddev[0]);
}

/**
 * Calculate mean brightness (0-255).
 */
static float calculate_brightness(const cv::Mat &gray_image)
{
    if (gray_image.empty())
        return 0.0f;

    cv::Scalar mean = cv::mean(gray_image);
    return static_cast<float>(mean[0]);
}

/**
 * Calculate contrast as standard deviation of pixel values.
 */
static float calculate_contrast(const cv::Mat &gray_image)
{
    if (gray_image.empty())
        return 0.0f;

    cv::Scalar mean, stddev;
    cv::meanStdDev(gray_image, mean, stddev);
    return static_cast<float>(stddev[0]);
}

/**
 * Calculate edge density using Canny edge detection.
 * Returns ratio of edge pixels to total pixels (0-1).
 */
static float calculate_edge_density(const cv::Mat &gray_image)
{
    if (gray_image.empty())
        return 0.0f;

    cv::Mat edges;
    cv::Canny(gray_image, edges, 50, 150);

    int edge_pixels = cv::countNonZero(edges);
    int total_pixels = gray_image.rows * gray_image.cols;

    if (total_pixels == 0)
        return 0.0f;

    return static_cast<float>(edge_pixels) / static_cast<float>(total_pixels);
}

/**
 * Convert image crop to grayscale for quality analysis.
 */
static cv::Mat get_gray_crop(std::shared_ptr<HailoMat> image, const HailoBBox &bbox)
{
    cv::Mat gray;
    if (!image)
        return gray;

    const float xmin = std::max(0.0f, std::min(1.0f, bbox.xmin()));
    const float ymin = std::max(0.0f, std::min(1.0f, bbox.ymin()));
    const float xmax = std::max(xmin, std::min(1.0f, bbox.xmax()));
    const float ymax = std::max(ymin, std::min(1.0f, bbox.ymax()));

    if (xmax <= xmin || ymax <= ymin)
        return gray;

    try
    {
        auto crop_roi = std::make_shared<HailoROI>(HailoBBox(xmin, ymin, (xmax - xmin), (ymax - ymin)));
        std::vector<cv::Mat> cropped = image->crop(crop_roi);
        if (cropped.empty() || cropped[0].empty())
            return gray;

        cv::Mat bgr_crop;
        switch (image->get_type())
        {
        case HAILO_MAT_RGB:
            cv::cvtColor(cropped[0], bgr_crop, cv::COLOR_RGB2BGR);
            break;
        case HAILO_MAT_YUY2:
            cv::cvtColor(cropped[0], bgr_crop, cv::COLOR_YUV2BGR_YUY2);
            break;
        case HAILO_MAT_NV12:
            if (cropped.size() < 2)
                return gray;
            cv::cvtColorTwoPlane(cropped[0], cropped[1], bgr_crop, cv::COLOR_YUV2BGR_NV12);
            break;
        default:
            bgr_crop = cropped[0];
            break;
        }

        cv::cvtColor(bgr_crop, gray, cv::COLOR_BGR2GRAY);
    }
    catch (const std::exception &e)
    {
        lpr_dbg("get_gray_crop exception: %s", e.what());
    }

    return gray;
}

/**
 * Check if LP bounding box is inside the configured ROI.
 */
static bool lp_inside_roi(const HailoBBox &lp_bbox)
{
    LprRoiConfig config = get_lpr_vehicle_roi_config();
    if (!config.enabled)
        return true;

    // Check if LP center is inside ROI
    float cx = lp_bbox.xmin() + 0.5f * lp_bbox.width();
    float cy = lp_bbox.ymin() + 0.5f * lp_bbox.height();

    return point_in_polygon(cx, cy, lpr_rect_to_polygon(config.rect));
}

/**
 * Perform comprehensive quality check on a license plate crop.
 */
static LpQualityResult check_lp_quality(
    std::shared_ptr<HailoMat> image,
    const HailoBBox &lp_bbox,
    const LpQualityConfig &config)
{
    LpQualityResult result = {};
    result.passed = false;
    result.reason = LpQualityRejectReason::PASSED;
    result.blur_score = 0.0f;
    result.brightness = 0.0f;
    result.contrast = 0.0f;
    result.edge_density = 0.0f;
    result.aspect_ratio = 0.0f;
    result.width_px = 0;
    result.height_px = 0;

    if (!image)
    {
        result.reason = LpQualityRejectReason::EMPTY_CROP;
        return result;
    }

    // Calculate pixel dimensions
    result.width_px = static_cast<int>(lp_bbox.width() * image->width());
    result.height_px = static_cast<int>(lp_bbox.height() * image->height());

    // Size check
    if (result.width_px < config.min_width_px || result.height_px < config.min_height_px)
    {
        result.reason = LpQualityRejectReason::TOO_SMALL;
        return result;
    }

    if (result.width_px > config.max_width_px || result.height_px > config.max_height_px)
    {
        result.reason = LpQualityRejectReason::TOO_LARGE;
        return result;
    }

    // Aspect ratio check
    if (result.height_px > 0)
    {
        result.aspect_ratio = static_cast<float>(result.width_px) / static_cast<float>(result.height_px);
        if (result.aspect_ratio < config.min_aspect || result.aspect_ratio > config.max_aspect)
        {
            result.reason = LpQualityRejectReason::BAD_ASPECT_RATIO;
            return result;
        }
    }

    // ROI check
    if (config.roi_check_enabled && !lp_inside_roi(lp_bbox))
    {
        result.reason = LpQualityRejectReason::OUTSIDE_ROI;
        return result;
    }

    // Get grayscale crop for image quality checks
    cv::Mat gray = get_gray_crop(image, lp_bbox);
    if (gray.empty())
    {
        result.reason = LpQualityRejectReason::EMPTY_CROP;
        return result;
    }

    // Blur check
    if (config.blur_check_enabled)
    {
        result.blur_score = calculate_blur_score(gray);
        if (result.blur_score < config.blur_threshold)
        {
            result.reason = LpQualityRejectReason::TOO_BLURRY;
            return result;
        }
    }

    // Exposure check (brightness)
    if (config.exposure_check_enabled)
    {
        result.brightness = calculate_brightness(gray);
        if (result.brightness < config.min_brightness)
        {
            result.reason = LpQualityRejectReason::TOO_DARK;
            return result;
        }
        if (result.brightness > config.max_brightness)
        {
            result.reason = LpQualityRejectReason::TOO_BRIGHT;
            return result;
        }
    }

    // Contrast check
    if (config.contrast_check_enabled)
    {
        result.contrast = calculate_contrast(gray);
        if (result.contrast < config.min_contrast)
        {
            result.reason = LpQualityRejectReason::LOW_CONTRAST;
            return result;
        }
    }

    // Edge density check
    if (config.edge_check_enabled)
    {
        result.edge_density = calculate_edge_density(gray);
        if (result.edge_density < config.min_edge_density)
        {
            result.reason = LpQualityRejectReason::LOW_EDGE_DENSITY;
            return result;
        }
    }

    // All checks passed
    result.passed = true;
    result.reason = LpQualityRejectReason::PASSED;
    return result;
}

static void log_quality_result(const char *prefix, int veh_idx, int lp_idx, int track_id,
                                const LpQualityResult &result, const HailoBBox &bbox)
{
    lpr_dbg("%s veh=%d lp=%d track_id=%d reason=%s size_px=%dx%d aspect=%.2f "
            "blur=%.1f bright=%.1f contrast=%.1f edges=%.3f bbox=[%.3f,%.3f,%.3f,%.3f]",
            prefix, veh_idx, lp_idx, track_id,
            quality_reason_str(result.reason),
            result.width_px, result.height_px, result.aspect_ratio,
            result.blur_score, result.brightness, result.contrast, result.edge_density,
            bbox.xmin(), bbox.ymin(), bbox.width(), bbox.height());
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

static void lpr_log_settings()
{
    static int logged = 0;
    if (logged || !lpr_debug_enabled())
        return;
    logged = 1;
    lpr_dbg("settings: HAILO_LPR_SAVE_CROPS=%d crops_dir='%s' OCR_RESULT_LABEL='%s'",
            lpr_save_crops_enabled() ? 1 : 0,
            get_crops_dir(),
            OCR_RESULT_LABEL);
}

static void track_ocr_vehicle_crop(int track_id)
{
    if (track_id < 0 || !lpr_debug_enabled())
        return;
    lpr_dbg("track_debug: track_id=%d event=vehicle_crop->lp", track_id);
}

static void track_ocr_lp_to_ocr(int track_id)
{
    if (track_id < 0 || !lpr_debug_enabled())
        return;
    lpr_dbg("track_debug: track_id=%d event=lp_crop->ocr", track_id);
}

static bool is_vehicle_label(const std::string &label)
{
    return label == VEHICLE_LABEL;
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

static void save_crop_image(std::shared_ptr<HailoMat> image, const HailoBBox &bbox,
                            const std::string &prefix, int id, int track_id)
{
    if (!lpr_save_crops_enabled() || !image)
        return;

    try
    {
        lpr_dbg("save_crop_image: prefix='%s' track_id=%d img=%dx%d type=%d bbox=[%.4f,%.4f,%.4f,%.4f]",
                prefix.c_str(), track_id, image->width(), image->height(), static_cast<int>(image->get_type()),
                bbox.xmin(), bbox.ymin(), bbox.width(), bbox.height());
        const float xmin = std::max(0.0f, std::min(1.0f, bbox.xmin()));
        const float ymin = std::max(0.0f, std::min(1.0f, bbox.ymin()));
        const float xmax = std::max(xmin, std::min(1.0f, bbox.xmax()));
        const float ymax = std::max(ymin, std::min(1.0f, bbox.ymax()));

        if (xmax <= xmin || ymax <= ymin)
        {
            lpr_dbg("save_crop_image: invalid bbox after clamp (xmin=%.3f xmax=%.3f ymin=%.3f ymax=%.3f)", xmin, xmax, ymin, ymax);
            return;
        }

        auto crop_roi = std::make_shared<HailoROI>(HailoBBox(xmin, ymin, (xmax - xmin), (ymax - ymin)));
        std::vector<cv::Mat> cropped_image_vec = image->crop(crop_roi);
        if (cropped_image_vec.empty() || cropped_image_vec[0].empty())
        {
            if (lpr_debug_enabled())
            {
                std::fprintf(stderr,
                             "[lpr_croppers] save_crop_image: EMPTY crop vec_size=%zu image_type=%d bbox=[%.4f,%.4f,%.4f,%.4f] img=%dx%d\n",
                             cropped_image_vec.size(), static_cast<int>(image->get_type()),
                             xmin, ymin, (xmax - xmin), (ymax - ymin), image->width(), image->height());
                std::fflush(stderr);
            }
            return;
        }
        lpr_dbg("save_crop_image: cropped mats=%zu first=%dx%d type=%d",
                cropped_image_vec.size(),
                cropped_image_vec[0].cols,
                cropped_image_vec[0].rows,
                cropped_image_vec[0].type());

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

        lpr_dbg("SAVED: %s (%dx%d)", filename, bgr_crop.cols, bgr_crop.rows);
    }
    catch (const std::exception &e)
    {
        lpr_dbg("Failed to save crop: %s", e.what());
    }
}

static void attach_crop_meta(const HailoDetectionPtr &detection, int crop_id, int frame_id)
{
    if (!detection)
        return;
    std::string label = "crop_id=" + std::to_string(crop_id) + " frame=" + std::to_string(frame_id);
    detection->add_object(std::make_shared<HailoClassification>("lp_crop_meta", label, 1.0f));
}

static bool is_nonempty_crop(std::shared_ptr<HailoMat> image, const HailoBBox &bbox)
{
    if (!image)
        return false;

    const float xmin = std::max(0.0f, std::min(1.0f, bbox.xmin()));
    const float ymin = std::max(0.0f, std::min(1.0f, bbox.ymin()));
    const float xmax = std::max(xmin, std::min(1.0f, bbox.xmax()));
    const float ymax = std::max(ymin, std::min(1.0f, bbox.ymax()));
    if (xmax <= xmin || ymax <= ymin)
        return false;

    auto crop_roi = std::make_shared<HailoROI>(HailoBBox(xmin, ymin, (xmax - xmin), (ymax - ymin)));
    std::vector<cv::Mat> cropped = image->crop(crop_roi);
    if (cropped.empty() || cropped[0].empty())
        return false;
    if (cropped[0].cols <= 0 || cropped[0].rows <= 0)
        return false;
    if (image->get_type() == HAILO_MAT_NV12)
    {
        if (cropped.size() < 2 || cropped[1].empty() || cropped[1].cols <= 0 || cropped[1].rows <= 0)
            return false;
    }
    return true;
}

static bool get_crop_dims(std::shared_ptr<HailoMat> image, const HailoBBox &bbox, int &w, int &h)
{
    w = 0;
    h = 0;
    if (!image)
        return false;

    const float xmin = std::max(0.0f, std::min(1.0f, bbox.xmin()));
    const float ymin = std::max(0.0f, std::min(1.0f, bbox.ymin()));
    const float xmax = std::max(xmin, std::min(1.0f, bbox.xmax()));
    const float ymax = std::max(ymin, std::min(1.0f, bbox.ymax()));
    if (xmax <= xmin || ymax <= ymin)
        return false;

    auto crop_roi = std::make_shared<HailoROI>(HailoBBox(xmin, ymin, (xmax - xmin), (ymax - ymin)));
    std::vector<cv::Mat> cropped = image->crop(crop_roi);
    if (cropped.empty() || cropped[0].empty())
        return false;
    if (cropped[0].cols <= 0 || cropped[0].rows <= 0)
        return false;
    if (image->get_type() == HAILO_MAT_NV12)
    {
        if (cropped.size() < 2 || cropped[1].empty() || cropped[1].cols <= 0 || cropped[1].rows <= 0)
            return false;
    }
    w = cropped[0].cols;
    h = cropped[0].rows;
    return true;
}

static bool clamp_bbox_to_pixels(const HailoBBox &in, int img_w, int img_h,
                                 HailoBBox &out, int &w_px, int &h_px)
{
    if (img_w <= 0 || img_h <= 0)
        return false;

    float xmin_f = std::max(0.0f, std::min(1.0f, in.xmin()));
    float ymin_f = std::max(0.0f, std::min(1.0f, in.ymin()));
    float xmax_f = std::max(xmin_f, std::min(1.0f, in.xmax()));
    float ymax_f = std::max(ymin_f, std::min(1.0f, in.ymax()));

    int xmin_px = std::max(0, std::min(img_w - 1, static_cast<int>(std::floor(xmin_f * img_w))));
    int ymin_px = std::max(0, std::min(img_h - 1, static_cast<int>(std::floor(ymin_f * img_h))));
    int xmax_px = std::max(0, std::min(img_w, static_cast<int>(std::ceil(xmax_f * img_w))));
    int ymax_px = std::max(0, std::min(img_h, static_cast<int>(std::ceil(ymax_f * img_h))));

    w_px = xmax_px - xmin_px;
    h_px = ymax_px - ymin_px;
    if (w_px <= 0 || h_px <= 0)
        return false;

    // Ensure even-sized crops to avoid NV12 resize issues.
    if ((w_px % 2) != 0)
        w_px -= 1;
    if ((h_px % 2) != 0)
        h_px -= 1;
    if (w_px <= 0 || h_px <= 0)
        return false;

    out = HailoBBox(static_cast<float>(xmin_px) / img_w,
                    static_cast<float>(ymin_px) / img_h,
                    static_cast<float>(w_px) / img_w,
                    static_cast<float>(h_px) / img_h);
    return true;
}

static HailoBBox apply_lp_padding(const HailoBBox &lp_bbox, const LpQualityConfig &config)
{
    float w = lp_bbox.width();
    float h = lp_bbox.height();

    float pad_left = w * config.pad_x;
    float pad_right = w * config.pad_x;
    float pad_top = h * config.pad_top;
    float pad_bottom = h * config.pad_bottom;

    float xmin = std::max(0.0f, lp_bbox.xmin() - pad_left);
    float ymin = std::max(0.0f, lp_bbox.ymin() - pad_top);
    float xmax = std::min(1.0f, lp_bbox.xmax() + pad_right);
    float ymax = std::min(1.0f, lp_bbox.ymax() + pad_bottom);

    return HailoBBox(xmin, ymin, xmax - xmin, ymax - ymin);
}

std::vector<HailoROIPtr> vehicles_roi_cropper(std::shared_ptr<HailoMat> image, HailoROIPtr roi)
{
    std::vector<HailoROIPtr> crop_rois;
    if (!image || !roi)
    {
        return crop_rois;
    }

    load_lpr_state_from_jsonl();
    refresh_lpr_state_from_jsonl();
    std::vector<HailoDetectionPtr> detections_ptrs = hailo_common::get_hailo_detections(roi);
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

        if (!vehicle_inside_roi(vehicle_bbox))
        {
            det_idx++;
            continue;
        }

        if ((vehicle_bbox.xmin() < 0.0) ||
            (vehicle_bbox.xmax() > 1.0) ||
            (vehicle_bbox.ymin() < 0.0) ||
            (vehicle_bbox.ymax() > 1.0))
        {
            det_idx++;
            continue;
        }

        float vxmin = std::max(0.0f, std::min(1.0f, vehicle_bbox.xmin()));
        float vymin = std::max(0.0f, std::min(1.0f, vehicle_bbox.ymin()));
        float vxmax = std::max(vxmin, std::min(1.0f, vehicle_bbox.xmax()));
        float vymax = std::max(vymin, std::min(1.0f, vehicle_bbox.ymax()));
        HailoBBox clamped_vehicle_bbox(vxmin, vymin, vxmax - vxmin, vymax - vymin);
        const float v_w_px = clamped_vehicle_bbox.width() * image->width();
        const float v_h_px = clamped_vehicle_bbox.height() * image->height();
        if (v_w_px < 10.0f || v_h_px < 10.0f)
        {
            lpr_dbg("vehicles_roi_cropper: SKIP tiny vehicle bbox px=%.2fx%.2f", v_w_px, v_h_px);
            det_idx++;
            continue;
        }
        if (!is_nonempty_crop(image, clamped_vehicle_bbox))
        {
            lpr_dbg("vehicles_roi_cropper: SKIP empty crop bbox=[%.3f,%.3f,%.3f,%.3f]",
                    clamped_vehicle_bbox.xmin(), clamped_vehicle_bbox.ymin(),
                    clamped_vehicle_bbox.width(), clamped_vehicle_bbox.height());
            det_idx++;
            continue;
        }

        detection->set_bbox(clamped_vehicle_bbox);
        detection->set_scaling_bbox(HailoBBox(0.0f, 0.0f, 1.0f, 1.0f));

        float vehicle_area = vehicle_bbox.width() * vehicle_bbox.height();
        float min_area = get_min_vehicle_area();
        if (vehicle_area < min_area)
        {
            det_idx++;
            continue;
        }

        int track_id = get_tracking_id(detection);
        if (track_id >= 0)
        {
            if (!track_seen(track_id))
            {
                mark_track_seen(track_id);
            }
            else
            {
                std::string plate;
                if (track_has_lpr(track_id, &plate))
                {
                    det_idx++;
                    continue;
                }
            }
        }

        int crop_id = g_vehicle_crop_counter.fetch_add(1);
        track_ocr_vehicle_crop(track_id);
        save_crop_image(image, vehicle_bbox, "vehicle_to_lp_det", crop_id, track_id);

        crop_rois.emplace_back(detection);
        det_idx++;
    }

    return crop_rois;
}

std::vector<HailoROIPtr> license_plate_with_quality(std::shared_ptr<HailoMat> image, HailoROIPtr roi)
{
    lpr_log_settings();
    std::vector<HailoROIPtr> crop_rois;
    LpQualityConfig config = get_lp_quality_config();
    const bool debug = lpr_debug_enabled();
    const int frame_id = g_lp_frame_counter.fetch_add(1);
    const char *crop_name = "lp_quality_ocr";
    const char *sent_prefix = "SENT_lp_quality_ocr";
    const char *reject_prefix = "REJECT_lp_quality_ocr";

    if (debug)
    {
        std::cout << "[LP_QUALITY] ========== ENTER ==========" << std::endl;
        std::cout << "[LP_QUALITY] Config: enabled=" << config.enabled
                  << " blur_check=" << config.blur_check_enabled << " (thresh=" << config.blur_threshold << ")"
                  << " exposure_check=" << config.exposure_check_enabled
                  << " (min_bright=" << config.min_brightness << ", max_bright=" << config.max_brightness << ")"
                  << " contrast_check=" << config.contrast_check_enabled << " (min=" << config.min_contrast << ")"
                  << " edge_check=" << config.edge_check_enabled << " (min=" << config.min_edge_density << ")"
                  << " roi_check=" << config.roi_check_enabled
                  << " size_px=[" << config.min_width_px << "-" << config.max_width_px << "]x["
                  << config.min_height_px << "-" << config.max_height_px << "]"
                  << " aspect=[" << config.min_aspect << "-" << config.max_aspect << "]"
                  << std::endl << std::flush;
    }

    if (!image || !roi)
    {
        if (debug)
        {
            std::cout << "[LP_QUALITY] ERROR: null image or roi => EXIT" << std::endl << std::flush;
        }
        return crop_rois;
    }
    if (debug)
    {
        std::cout << "[LP_QUALITY] Image size: " << image->width() << "x" << image->height() << std::endl << std::flush;
    }

    std::vector<HailoDetectionPtr> vehicle_ptrs = hailo_common::get_hailo_detections(roi);
    std::vector<HailoDetectionPtr> top_lp_ptrs;
    for (auto &det : vehicle_ptrs)
    {
        if (det && det->get_label() == LICENSE_PLATE_LABEL)
        {
            top_lp_ptrs.push_back(det);
        }
    }
    if (debug)
    {
        std::cout << "[LP_QUALITY] Found " << vehicle_ptrs.size() << " top-level detections, "
                  << top_lp_ptrs.size() << " standalone LPs" << std::endl << std::flush;
    }

    int veh_idx = 0;
    for (HailoDetectionPtr &vehicle : vehicle_ptrs)
    {
        std::string veh_label = vehicle->get_label();
        if (debug)
        {
            std::cout << "[LP_QUALITY] [" << veh_idx << "] label='" << veh_label << "'" << std::endl << std::flush;
        }

        if (!is_vehicle_label(veh_label))
        {
            if (debug)
            {
                std::cout << "[LP_QUALITY] [" << veh_idx << "] SKIP - not vehicle" << std::endl << std::flush;
            }
            veh_idx++;
            continue;
        }

        int track_id = get_tracking_id(vehicle);

        std::vector<HailoDetectionPtr> license_plate_ptrs = hailo_common::get_hailo_detections(vehicle);
        if (license_plate_ptrs.empty() && !top_lp_ptrs.empty())
        {
            HailoBBox v_bbox = hailo_common::create_flattened_bbox(vehicle->get_bbox(), vehicle->get_scaling_bbox());
            for (auto &lp_det : top_lp_ptrs)
            {
                if (lp_det->get_label() != LICENSE_PLATE_LABEL)
                    continue;
                HailoBBox lp_flat = hailo_common::create_flattened_bbox(lp_det->get_bbox(), lp_det->get_scaling_bbox());
                float cx = lp_flat.xmin() + 0.5f * lp_flat.width();
                float cy = lp_flat.ymin() + 0.5f * lp_flat.height();
                bool center_inside = (cx >= v_bbox.xmin() && cx <= v_bbox.xmax() && cy >= v_bbox.ymin() && cy <= v_bbox.ymax());
                if (center_inside)
                {
                    license_plate_ptrs.push_back(lp_det);
                    break;
                }
            }
        }
        if (debug)
        {
            std::cout << "[LP_QUALITY] [" << veh_idx << "] Found " << license_plate_ptrs.size() << " LP detections" << std::endl << std::flush;
        }

        int lp_idx = 0;
        for (HailoDetectionPtr &license_plate : license_plate_ptrs)
        {
            std::string lp_label = license_plate->get_label();
            float lp_conf = license_plate->get_confidence();

            HailoBBox lp_flat_bbox = hailo_common::create_flattened_bbox(
                license_plate->get_bbox(),
                license_plate->get_scaling_bbox());

            if (debug)
            {
                std::cout << "[LP_QUALITY] [" << veh_idx << "][" << lp_idx << "] label='" << lp_label
                          << "' conf=" << lp_conf << std::endl << std::flush;
            }

            if (LICENSE_PLATE_LABEL != lp_label)
            {
                if (debug)
                {
                    std::cout << "[LP_QUALITY] [" << veh_idx << "][" << lp_idx << "] SKIP - not LP" << std::endl << std::flush;
                }
                lpr_dbg("%s REJECT reason=label veh=%d lp=%d label='%s'", crop_name, veh_idx, lp_idx, lp_label.c_str());
                int crop_id = g_lp_crop_counter.fetch_add(1);
                save_crop_image(image, lp_flat_bbox, reject_prefix, crop_id, track_id);
                lp_idx++;
                continue;
            }

            // Apply padding before quality checks
            HailoBBox padded_bbox = apply_lp_padding(lp_flat_bbox, config);

            // Perform comprehensive quality check if enabled
            if (config.enabled)
            {
                LpQualityResult quality = check_lp_quality(image, lp_flat_bbox, config);

                if (!quality.passed)
                {
                    if (debug)
                    {
                        std::cout << "[LP_QUALITY] [" << veh_idx << "][" << lp_idx << "] REJECTED: "
                                  << quality_reason_str(quality.reason)
                                  << " (size=" << quality.width_px << "x" << quality.height_px
                                  << " aspect=" << quality.aspect_ratio
                                  << " blur=" << quality.blur_score
                                  << " bright=" << quality.brightness
                                  << " contrast=" << quality.contrast
                                  << " edges=" << quality.edge_density << ")"
                                  << std::endl << std::flush;
                    }
                    log_quality_result((std::string(crop_name) + " REJECT").c_str(),
                                       veh_idx, lp_idx, track_id, quality, lp_flat_bbox);
                    int crop_id = g_lp_crop_counter.fetch_add(1);
                    save_crop_image(image, padded_bbox, reject_prefix, crop_id, track_id);
                    lp_idx++;
                    continue;
                }

                if (debug)
                {
                    std::cout << "[LP_QUALITY] [" << veh_idx << "][" << lp_idx << "] PASSED quality checks"
                              << " (size=" << quality.width_px << "x" << quality.height_px
                              << " aspect=" << quality.aspect_ratio
                              << " blur=" << quality.blur_score
                              << " bright=" << quality.brightness
                              << " contrast=" << quality.contrast
                              << " edges=" << quality.edge_density << ")"
                              << std::endl << std::flush;
                }
            }

            // Basic size check even if quality disabled
            const float lp_px_w = padded_bbox.width() * image->width();
            const float lp_px_h = padded_bbox.height() * image->height();
            if (padded_bbox.width() <= 0.0f || padded_bbox.height() <= 0.0f ||
                lp_px_w < 35.0f || lp_px_h < 20.0f)
            {
                if (debug)
                {
                    std::cout << "[LP_QUALITY] [" << veh_idx << "][" << lp_idx << "] SKIP - LP too small after padding ("
                             << lp_px_w << "x" << lp_px_h << " px)" << std::endl << std::flush;
                }
                lpr_dbg("%s REJECT reason=too_small_padded veh=%d lp=%d size_px=%.1fx%.1f bbox=[%.3f,%.3f,%.3f,%.3f]",
                        crop_name, veh_idx, lp_idx, lp_px_w, lp_px_h,
                        padded_bbox.xmin(), padded_bbox.ymin(), padded_bbox.width(), padded_bbox.height());
                int crop_id = g_lp_crop_counter.fetch_add(1);
                save_crop_image(image, padded_bbox, reject_prefix, crop_id, track_id);
                lp_idx++;
                continue;
            }

            if (debug)
            {
                std::cout << "[LP_QUALITY] [" << veh_idx << "][" << lp_idx << "] SENDING TO OCR - padded=["
                          << padded_bbox.xmin() << "," << padded_bbox.ymin()
                          << "," << padded_bbox.width() << "," << padded_bbox.height() << "]" << std::endl << std::flush;
            }

            license_plate->set_bbox(padded_bbox);
            license_plate->set_scaling_bbox(HailoBBox(0.0f, 0.0f, 1.0f, 1.0f));
            attach_tracking_id_if_missing(license_plate, track_id);
            lpr_dbg("%s SEND veh=%d lp=%d track_id=%d bbox=[%.3f,%.3f,%.3f,%.3f] size_px=%.1fx%.1f",
                    crop_name, veh_idx, lp_idx, track_id,
                    padded_bbox.xmin(), padded_bbox.ymin(), padded_bbox.width(), padded_bbox.height(),
                    lp_px_w, lp_px_h);

            int crop_id = g_lp_crop_counter.fetch_add(1);
            save_crop_image(image, padded_bbox, sent_prefix, crop_id, track_id);
            attach_crop_meta(license_plate, crop_id, frame_id);
            crop_rois.emplace_back(license_plate);

            if (debug)
            {
                std::cout << "[LP_QUALITY] [" << veh_idx << "][" << lp_idx << "] ADDED (total=" << crop_rois.size() << ")" << std::endl << std::flush;
            }
            lp_idx++;
        }

        if (license_plate_ptrs.empty())
        {
            if (debug)
            {
                std::cout << "[LP_QUALITY] [" << veh_idx << "] No nested LP detections" << std::endl << std::flush;
            }
        }
        veh_idx++;
    }

    if (debug)
    {
        std::cout << "[LP_QUALITY] RESULT: " << crop_rois.size() << " LP(s) to OCR" << std::endl << std::flush;
        std::cout << "[LP_QUALITY] ========== EXIT ==========" << std::endl << std::flush;
    }
    return crop_rois;
}

std::vector<HailoROIPtr> license_plate_no_quality(std::shared_ptr<HailoMat> image, HailoROIPtr roi)
{
    lpr_log_settings();
    std::vector<HailoROIPtr> crop_rois;
    const char *crop_name = "lp_no_quality_ocr";
    const char *sent_prefix = "SENT_lp_no_quality_ocr";
    const char *reject_prefix = "REJECT_lp_no_quality_ocr";
    const int frame_id = g_lp_frame_counter.fetch_add(1);

    load_lpr_state_from_jsonl();
    refresh_lpr_state_from_jsonl();

    if (!image || !roi)
    {
        lpr_dbg("%s REJECT reason=null_input", crop_name);
        return crop_rois;
    }

    const int img_w = image->width();
    const int img_h = image->height();
    if (img_w <= 0 || img_h <= 0)
    {
        lpr_dbg("%s REJECT reason=invalid_image_size size=%dx%d", crop_name, img_w, img_h);
        return crop_rois;
    }

    std::vector<HailoDetectionPtr> detections = hailo_common::get_hailo_detections(roi);
    std::vector<HailoDetectionPtr> vehicles;
    std::vector<HailoDetectionPtr> top_lp_ptrs;
    for (auto &det : detections)
    {
        if (!det)
            continue;
        if (is_vehicle_label(det->get_label()))
            vehicles.push_back(det);
        if (det->get_label() == LICENSE_PLATE_LABEL)
            top_lp_ptrs.push_back(det);
    }

    int veh_idx = 0;
    for (HailoDetectionPtr &vehicle : vehicles)
    {
        if (!vehicle)
        {
            veh_idx++;
            continue;
        }

        HailoBBox vehicle_bbox = vehicle->get_bbox();
        if (!vehicle_inside_roi(vehicle_bbox))
        {
            lpr_dbg("%s REJECT reason=vehicle_outside_roi veh=%d", crop_name, veh_idx);
            veh_idx++;
            continue;
        }

        int track_id = get_tracking_id(vehicle);

        // Skip if this track already has an LPR result
        if (track_id >= 0)
        {
            std::string plate;
            if (track_has_lpr(track_id, &plate))
            {
                lpr_dbg("%s SKIP veh=%d track_id=%d already has LP '%s'",
                        crop_name, veh_idx, track_id, plate.c_str());
                veh_idx++;
                continue;
            }
        }

        HailoBBox v_bbox = vehicle->get_bbox();
        float vehicle_area = v_bbox.width() * v_bbox.height();

        std::vector<HailoDetectionPtr> license_plate_ptrs = hailo_common::get_hailo_detections(vehicle);
        if (license_plate_ptrs.empty() && !top_lp_ptrs.empty())
        {
            for (auto &lp_det : top_lp_ptrs)
            {
                if (!lp_det || lp_det->get_label() != LICENSE_PLATE_LABEL)
                    continue;
                HailoBBox lp_bbox = lp_det->get_bbox();
                float cx = lp_bbox.xmin() + 0.5f * lp_bbox.width();
                float cy = lp_bbox.ymin() + 0.5f * lp_bbox.height();
                bool center_inside = (cx >= v_bbox.xmin() && cx <= v_bbox.xmax() &&
                                      cy >= v_bbox.ymin() && cy <= v_bbox.ymax());
                if (center_inside)
                {
                    license_plate_ptrs.push_back(lp_det);
                    break;
                }
            }
        }

        // Find the best plate for this vehicle based on relative area
        HailoDetectionPtr best_plate;
        HailoBBox best_clamped_bbox(0.0f, 0.0f, 0.0f, 0.0f);
        float best_rel_area = 0.0f;
        int best_crop_w = 0;
        int best_crop_h = 0;

        int lp_idx = 0;
        for (HailoDetectionPtr &license_plate : license_plate_ptrs)
        {
            if (!license_plate)
            {
                lp_idx++;
                continue;
            }

            std::string lp_label = license_plate->get_label();
            if (LICENSE_PLATE_LABEL != lp_label)
            {
                lpr_dbg("%s REJECT reason=label veh=%d lp=%d label='%s'", crop_name, veh_idx, lp_idx, lp_label.c_str());
                lp_idx++;
                continue;
            }

            HailoBBox lp_flat = license_plate->get_bbox();

            HailoBBox clamped_bbox(0.0f, 0.0f, 0.0f, 0.0f);
            int w_px = 0;
            int h_px = 0;
            if (!clamp_bbox_to_pixels(lp_flat, img_w, img_h, clamped_bbox, w_px, h_px))
            {
                lpr_dbg("%s REJECT reason=invalid_bbox veh=%d lp=%d", crop_name, veh_idx, lp_idx);
                lp_idx++;
                continue;
            }
            int crop_w = 0;
            int crop_h = 0;
            if (!get_crop_dims(image, clamped_bbox, crop_w, crop_h))
            {
                lpr_dbg("%s REJECT reason=empty_crop veh=%d lp=%d", crop_name, veh_idx, lp_idx);
                lp_idx++;
                continue;
            }
            if (crop_w < 10 || crop_h < 5)
            {
                lpr_dbg("%s REJECT reason=too_small_px veh=%d lp=%d size_px=%dx%d",
                        crop_name, veh_idx, lp_idx, crop_w, crop_h);
                lp_idx++;
                continue;
            }

            if (!vehicle_inside_roi(clamped_bbox))
            {
                lpr_dbg("%s REJECT reason=outside_roi veh=%d lp=%d", crop_name, veh_idx, lp_idx);
                int crop_id = g_lp_crop_counter.fetch_add(1);
                save_crop_image(image, clamped_bbox, reject_prefix, crop_id, track_id);
                lp_idx++;
                continue;
            }

            float cx = clamped_bbox.xmin() + 0.5f * clamped_bbox.width();
            float cy = clamped_bbox.ymin() + 0.5f * clamped_bbox.height();
            bool inside_vehicle = (cx >= v_bbox.xmin() && cx <= v_bbox.xmax() &&
                                   cy >= v_bbox.ymin() && cy <= v_bbox.ymax());
            if (!inside_vehicle)
            {
                lpr_dbg("%s REJECT reason=outside_vehicle veh=%d lp=%d", crop_name, veh_idx, lp_idx);
                int crop_id = g_lp_crop_counter.fetch_add(1);
                save_crop_image(image, clamped_bbox, reject_prefix, crop_id, track_id);
                lp_idx++;
                continue;
            }

            // Calculate relative area and check minimum threshold
            float lp_area = clamped_bbox.width() * clamped_bbox.height();
            float rel_area = (vehicle_area > 0.0f) ? (lp_area / vehicle_area) : 0.0f;
            if (rel_area < MIN_LP_REL_AREA)
            {
                lpr_dbg("%s REJECT reason=too_small_rel veh=%d lp=%d rel_area=%.4f < %.4f",
                        crop_name, veh_idx, lp_idx, rel_area, MIN_LP_REL_AREA);
                lp_idx++;
                continue;
            }

            // Keep track of the best plate (largest relative area)
            if (rel_area > best_rel_area)
            {
                best_plate = license_plate;
                best_clamped_bbox = clamped_bbox;
                best_rel_area = rel_area;
                best_crop_w = crop_w;
                best_crop_h = crop_h;
            }
            lp_idx++;
        }

        // Send the best plate to OCR
        if (best_plate)
        {
            best_plate->set_bbox(best_clamped_bbox);
            best_plate->set_scaling_bbox(HailoBBox(0.0f, 0.0f, 1.0f, 1.0f));
            attach_tracking_id_if_missing(best_plate, track_id);

            lpr_dbg("%s SEND veh=%d track_id=%d rel_area=%.4f bbox=[%.3f,%.3f,%.3f,%.3f] size_px=%dx%d img=%dx%d",
                    crop_name, veh_idx, track_id, best_rel_area,
                    best_clamped_bbox.xmin(), best_clamped_bbox.ymin(), best_clamped_bbox.width(), best_clamped_bbox.height(),
                    best_crop_w, best_crop_h, img_w, img_h);

            int crop_id = g_lp_crop_counter.fetch_add(1);
            save_crop_image(image, best_clamped_bbox, sent_prefix, crop_id, track_id);
            attach_crop_meta(best_plate, crop_id, frame_id);
            track_ocr_lp_to_ocr(track_id);
            crop_rois.emplace_back(best_plate);
        }
        veh_idx++;
    }

    // Fallback: if no plates found via vehicles, try top-level LPs
    if (crop_rois.empty() && !top_lp_ptrs.empty())
    {
        int lp_idx = 0;
        for (auto &lp_det : top_lp_ptrs)
        {
            if (!lp_det || lp_det->get_label() != LICENSE_PLATE_LABEL)
            {
                lp_idx++;
                continue;
            }
            HailoBBox lp_flat = lp_det->get_bbox();
            HailoBBox clamped_bbox(0.0f, 0.0f, 0.0f, 0.0f);
            int w_px = 0;
            int h_px = 0;
            if (!clamp_bbox_to_pixels(lp_flat, img_w, img_h, clamped_bbox, w_px, h_px))
            {
                lpr_dbg("%s REJECT reason=invalid_bbox lp=%d", crop_name, lp_idx);
                lp_idx++;
                continue;
            }
            int crop_w = 0;
            int crop_h = 0;
            if (!get_crop_dims(image, clamped_bbox, crop_w, crop_h))
            {
                lpr_dbg("%s REJECT reason=empty_crop lp=%d", crop_name, lp_idx);
                lp_idx++;
                continue;
            }
            if (crop_w < 10 || crop_h < 5)
            {
                lpr_dbg("%s REJECT reason=too_small_px lp=%d size_px=%dx%d",
                        crop_name, lp_idx, crop_w, crop_h);
                lp_idx++;
                continue;
            }
            if (!vehicle_inside_roi(clamped_bbox))
            {
                lpr_dbg("%s REJECT reason=outside_roi lp=%d", crop_name, lp_idx);
                int crop_id = g_lp_crop_counter.fetch_add(1);
                save_crop_image(image, clamped_bbox, reject_prefix, crop_id, -1);
                lp_idx++;
                continue;
            }
            lp_det->set_bbox(clamped_bbox);
            lp_det->set_scaling_bbox(HailoBBox(0.0f, 0.0f, 1.0f, 1.0f));
            int track_id = get_tracking_id(lp_det);
            lpr_dbg("%s SEND lp=%d track_id=%d bbox=[%.3f,%.3f,%.3f,%.3f] size_px=%dx%d img=%dx%d",
                    crop_name, lp_idx, track_id,
                    clamped_bbox.xmin(), clamped_bbox.ymin(),
                    clamped_bbox.width(), clamped_bbox.height(),
                    crop_w, crop_h, img_w, img_h);
            int crop_id = g_lp_crop_counter.fetch_add(1);
            save_crop_image(image, clamped_bbox, sent_prefix, crop_id, track_id);
            attach_crop_meta(lp_det, crop_id, frame_id);
            track_ocr_lp_to_ocr(track_id);
            crop_rois.emplace_back(lp_det);
            lp_idx++;
        }
    }

    return crop_rois;
}

std::vector<HailoROIPtr> license_plate_no_quality_two_best(std::shared_ptr<HailoMat> image, HailoROIPtr roi)
{
    lpr_log_settings();
    std::vector<HailoROIPtr> crop_rois;
    const char *crop_name = "lp_no_quality_two_best_ocr";
    const char *sent_prefix = "SENT_lp_no_quality_two_best_ocr";
    const char *reject_prefix = "REJECT_lp_no_quality_two_best_ocr";
    const int frame_id = g_lp_frame_counter.fetch_add(1);

    load_lpr_state_from_jsonl();
    refresh_lpr_state_from_jsonl();

    if (!image || !roi)
    {
        lpr_dbg("%s REJECT reason=null_input", crop_name);
        return crop_rois;
    }

    const int img_w = image->width();
    const int img_h = image->height();
    if (img_w <= 0 || img_h <= 0)
    {
        lpr_dbg("%s REJECT reason=invalid_image_size size=%dx%d", crop_name, img_w, img_h);
        return crop_rois;
    }

    std::vector<HailoDetectionPtr> detections = hailo_common::get_hailo_detections(roi);
    std::vector<HailoDetectionPtr> vehicles;
    std::vector<HailoDetectionPtr> top_lp_ptrs;
    for (auto &det : detections)
    {
        if (!det)
            continue;
        if (is_vehicle_label(det->get_label()))
            vehicles.push_back(det);
        if (det->get_label() == LICENSE_PLATE_LABEL)
            top_lp_ptrs.push_back(det);
    }

    int veh_idx = 0;
    for (HailoDetectionPtr &vehicle : vehicles)
    {
        if (!vehicle)
        {
            veh_idx++;
            continue;
        }

        HailoBBox vehicle_bbox = vehicle->get_bbox();
        if (!vehicle_inside_roi(vehicle_bbox))
        {
            lpr_dbg("%s REJECT reason=vehicle_outside_roi veh=%d", crop_name, veh_idx);
            veh_idx++;
            continue;
        }

        int track_id = get_tracking_id(vehicle);

        // Skip if this track already has an LPR result
        if (track_id >= 0)
        {
            std::string plate;
            if (track_has_lpr(track_id, &plate))
            {
                lpr_dbg("%s SKIP veh=%d track_id=%d already has LP '%s'",
                        crop_name, veh_idx, track_id, plate.c_str());
                veh_idx++;
                continue;
            }
        }

        HailoBBox v_bbox = vehicle->get_bbox();
        float vehicle_area = v_bbox.width() * v_bbox.height();

        std::vector<HailoDetectionPtr> license_plate_ptrs = hailo_common::get_hailo_detections(vehicle);
        if (license_plate_ptrs.empty() && !top_lp_ptrs.empty())
        {
            for (auto &lp_det : top_lp_ptrs)
            {
                if (!lp_det || lp_det->get_label() != LICENSE_PLATE_LABEL)
                    continue;
                HailoBBox lp_bbox = lp_det->get_bbox();
                float cx = lp_bbox.xmin() + 0.5f * lp_bbox.width();
                float cy = lp_bbox.ymin() + 0.5f * lp_bbox.height();
                bool center_inside = (cx >= v_bbox.xmin() && cx <= v_bbox.xmax() &&
                                      cy >= v_bbox.ymin() && cy <= v_bbox.ymax());
                if (center_inside)
                {
                    license_plate_ptrs.push_back(lp_det);
                }
            }
        }

        // Candidate structure for tracking best two plates
        struct LpCandidate
        {
            HailoDetectionPtr plate;
            HailoBBox clamped_bbox;
            float rel_area;
            int crop_w;
            int crop_h;
        };
        std::vector<LpCandidate> valid_candidates;

        int lp_idx = 0;
        for (HailoDetectionPtr &license_plate : license_plate_ptrs)
        {
            if (!license_plate)
            {
                lp_idx++;
                continue;
            }

            std::string lp_label = license_plate->get_label();
            if (LICENSE_PLATE_LABEL != lp_label)
            {
                lpr_dbg("%s REJECT reason=label veh=%d lp=%d label='%s'", crop_name, veh_idx, lp_idx, lp_label.c_str());
                lp_idx++;
                continue;
            }

            HailoBBox lp_flat = license_plate->get_bbox();

            HailoBBox clamped_bbox(0.0f, 0.0f, 0.0f, 0.0f);
            int w_px = 0;
            int h_px = 0;
            if (!clamp_bbox_to_pixels(lp_flat, img_w, img_h, clamped_bbox, w_px, h_px))
            {
                lpr_dbg("%s REJECT reason=invalid_bbox veh=%d lp=%d", crop_name, veh_idx, lp_idx);
                lp_idx++;
                continue;
            }
            int crop_w = 0;
            int crop_h = 0;
            if (!get_crop_dims(image, clamped_bbox, crop_w, crop_h))
            {
                lpr_dbg("%s REJECT reason=empty_crop veh=%d lp=%d", crop_name, veh_idx, lp_idx);
                lp_idx++;
                continue;
            }
            if (crop_w < 10 || crop_h < 5)
            {
                lpr_dbg("%s REJECT reason=too_small_px veh=%d lp=%d size_px=%dx%d",
                        crop_name, veh_idx, lp_idx, crop_w, crop_h);
                lp_idx++;
                continue;
            }

            if (!vehicle_inside_roi(clamped_bbox))
            {
                lpr_dbg("%s REJECT reason=outside_roi veh=%d lp=%d", crop_name, veh_idx, lp_idx);
                int crop_id = g_lp_crop_counter.fetch_add(1);
                save_crop_image(image, clamped_bbox, reject_prefix, crop_id, track_id);
                lp_idx++;
                continue;
            }

            float cx = clamped_bbox.xmin() + 0.5f * clamped_bbox.width();
            float cy = clamped_bbox.ymin() + 0.5f * clamped_bbox.height();
            bool inside_vehicle = (cx >= v_bbox.xmin() && cx <= v_bbox.xmax() &&
                                   cy >= v_bbox.ymin() && cy <= v_bbox.ymax());
            if (!inside_vehicle)
            {
                lpr_dbg("%s REJECT reason=outside_vehicle veh=%d lp=%d", crop_name, veh_idx, lp_idx);
                int crop_id = g_lp_crop_counter.fetch_add(1);
                save_crop_image(image, clamped_bbox, reject_prefix, crop_id, track_id);
                lp_idx++;
                continue;
            }

            // Calculate relative area and check minimum threshold
            float lp_area = clamped_bbox.width() * clamped_bbox.height();
            float rel_area = (vehicle_area > 0.0f) ? (lp_area / vehicle_area) : 0.0f;
            if (rel_area < MIN_LP_REL_AREA)
            {
                lpr_dbg("%s REJECT reason=too_small_rel veh=%d lp=%d rel_area=%.4f < %.4f",
                        crop_name, veh_idx, lp_idx, rel_area, MIN_LP_REL_AREA);
                lp_idx++;
                continue;
            }

            // Add to valid candidates
            valid_candidates.push_back({license_plate, clamped_bbox, rel_area, crop_w, crop_h});
            lp_idx++;
        }

        // Sort candidates by relative area (descending) and take top 2
        std::sort(valid_candidates.begin(), valid_candidates.end(),
                  [](const LpCandidate &a, const LpCandidate &b) { return a.rel_area > b.rel_area; });

        size_t num_to_send = std::min(valid_candidates.size(), static_cast<size_t>(2));
        for (size_t i = 0; i < num_to_send; i++)
        {
            LpCandidate &candidate = valid_candidates[i];

            candidate.plate->set_bbox(candidate.clamped_bbox);
            candidate.plate->set_scaling_bbox(HailoBBox(0.0f, 0.0f, 1.0f, 1.0f));
            attach_tracking_id_if_missing(candidate.plate, track_id);

            lpr_dbg("%s SEND veh=%d rank=%zu track_id=%d rel_area=%.4f bbox=[%.3f,%.3f,%.3f,%.3f] size_px=%dx%d img=%dx%d",
                    crop_name, veh_idx, i + 1, track_id, candidate.rel_area,
                    candidate.clamped_bbox.xmin(), candidate.clamped_bbox.ymin(),
                    candidate.clamped_bbox.width(), candidate.clamped_bbox.height(),
                    candidate.crop_w, candidate.crop_h, img_w, img_h);

            int crop_id = g_lp_crop_counter.fetch_add(1);
            save_crop_image(image, candidate.clamped_bbox, sent_prefix, crop_id, track_id);
            attach_crop_meta(candidate.plate, crop_id, frame_id);
            track_ocr_lp_to_ocr(track_id);
            crop_rois.emplace_back(candidate.plate);
        }
        veh_idx++;
    }

    // Fallback: if no plates found via vehicles, try top-level LPs (send up to 2)
    if (crop_rois.empty() && !top_lp_ptrs.empty())
    {
        struct LpCandidate
        {
            HailoDetectionPtr plate;
            HailoBBox clamped_bbox;
            int crop_w;
            int crop_h;
        };
        std::vector<LpCandidate> valid_top_lps;

        int lp_idx = 0;
        for (auto &lp_det : top_lp_ptrs)
        {
            if (!lp_det || lp_det->get_label() != LICENSE_PLATE_LABEL)
            {
                lp_idx++;
                continue;
            }
            HailoBBox lp_flat = lp_det->get_bbox();
            HailoBBox clamped_bbox(0.0f, 0.0f, 0.0f, 0.0f);
            int w_px = 0;
            int h_px = 0;
            if (!clamp_bbox_to_pixels(lp_flat, img_w, img_h, clamped_bbox, w_px, h_px))
            {
                lpr_dbg("%s REJECT reason=invalid_bbox lp=%d", crop_name, lp_idx);
                lp_idx++;
                continue;
            }
            int crop_w = 0;
            int crop_h = 0;
            if (!get_crop_dims(image, clamped_bbox, crop_w, crop_h))
            {
                lpr_dbg("%s REJECT reason=empty_crop lp=%d", crop_name, lp_idx);
                lp_idx++;
                continue;
            }
            if (crop_w < 10 || crop_h < 5)
            {
                lpr_dbg("%s REJECT reason=too_small_px lp=%d size_px=%dx%d",
                        crop_name, lp_idx, crop_w, crop_h);
                lp_idx++;
                continue;
            }
            if (!vehicle_inside_roi(clamped_bbox))
            {
                lpr_dbg("%s REJECT reason=outside_roi lp=%d", crop_name, lp_idx);
                int crop_id = g_lp_crop_counter.fetch_add(1);
                save_crop_image(image, clamped_bbox, reject_prefix, crop_id, -1);
                lp_idx++;
                continue;
            }
            valid_top_lps.push_back({lp_det, clamped_bbox, crop_w, crop_h});
            lp_idx++;
        }

        // Sort by crop size (area) descending and take top 2
        std::sort(valid_top_lps.begin(), valid_top_lps.end(),
                  [](const LpCandidate &a, const LpCandidate &b) {
                      return (a.crop_w * a.crop_h) > (b.crop_w * b.crop_h);
                  });

        size_t num_to_send = std::min(valid_top_lps.size(), static_cast<size_t>(2));
        for (size_t i = 0; i < num_to_send; i++)
        {
            LpCandidate &candidate = valid_top_lps[i];
            candidate.plate->set_bbox(candidate.clamped_bbox);
            candidate.plate->set_scaling_bbox(HailoBBox(0.0f, 0.0f, 1.0f, 1.0f));
            int track_id = get_tracking_id(candidate.plate);
            lpr_dbg("%s SEND lp=%zu track_id=%d bbox=[%.3f,%.3f,%.3f,%.3f] size_px=%dx%d img=%dx%d",
                    crop_name, i, track_id,
                    candidate.clamped_bbox.xmin(), candidate.clamped_bbox.ymin(),
                    candidate.clamped_bbox.width(), candidate.clamped_bbox.height(),
                    candidate.crop_w, candidate.crop_h, img_w, img_h);
            int crop_id = g_lp_crop_counter.fetch_add(1);
            save_crop_image(image, candidate.clamped_bbox, sent_prefix, crop_id, track_id);
            attach_crop_meta(candidate.plate, crop_id, frame_id);
            track_ocr_lp_to_ocr(track_id);
            crop_rois.emplace_back(candidate.plate);
        }
    }

    return crop_rois;
}
