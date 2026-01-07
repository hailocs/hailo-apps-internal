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

static constexpr float DEFAULT_MIN_VEHICLE_AREA = 0.03f;  // 1% of frame area

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
static constexpr float DEFAULT_LP_PAD_X = 0.03f;       // 3% padding on each side (was 10%)
static constexpr float DEFAULT_LP_PAD_TOP = 0.05f;     // 5% padding at top (was 20%)
static constexpr float DEFAULT_LP_PAD_BOTTOM = 0.08f;  // 8% padding at bottom (was 35%)
static constexpr float MIN_LP_REL_AREA = 0.001f;  // Minimum LP area relative to vehicle area (0.1%)
static constexpr float MAX_LP_REL_AREA = 0.25f;   // Maximum LP area relative to vehicle area (25%)
static constexpr float LP_SIMPLE_MIN_ASPECT = 1.5f;
static constexpr float LP_SIMPLE_MAX_ASPECT = 6.0f;
static constexpr float LP_SIMPLE_MIN_INSIDE_RATIO = 0.6f;
static constexpr int DEFAULT_LP_SIMPLE_MIN_WIDTH_PX = 10;
static constexpr int DEFAULT_LP_SIMPLE_MIN_HEIGHT_PX = 5;
static constexpr float DEFAULT_MIN_VEHICLE_CONFIDENCE = 0.7f;

// Minimum vehicle size in pixels for OCR to work well
// Vehicles smaller than this will be skipped (LP crops would be too small for OCR)
static constexpr int DEFAULT_MIN_VEHICLE_WIDTH_PX = 200;   // Minimum vehicle width in pixels
static constexpr int DEFAULT_MIN_VEHICLE_HEIGHT_PX = 150;  // Minimum vehicle height in pixels

// Lightweight validation thresholds for license_plate_no_quality cropper
static constexpr int LP_NO_QUALITY_MIN_WIDTH_PX = 40;
static constexpr int LP_NO_QUALITY_MIN_HEIGHT_PX = 15;
static constexpr float LP_NO_QUALITY_MIN_BRIGHTNESS = 30.0f;
static constexpr float LP_NO_QUALITY_MAX_BRIGHTNESS = 220.0f;
static constexpr float LP_NO_QUALITY_MIN_CONTRAST = 15.0f;

// Quality estimation defaults (from sda.txt)
static constexpr float CROP_RATIO = 0.1f;  // Crop ratio for quality estimation
static constexpr float QUALITY_THRESHOLD = 50.0f;  // Variance threshold for quality check

static void lpr_dbg(const char *fmt, ...);
static bool lpr_no_skip_enabled();

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
static std::unordered_map<int, float> g_vehicle_last_area;
static std::mutex g_vehicle_motion_mutex;

enum class VehicleMotion
{
    UNKNOWN = 0,
    APPROACHING,
    RECEDING
};

static const char *vehicle_motion_to_string(VehicleMotion motion)
{
    switch (motion)
    {
    case VehicleMotion::APPROACHING:
        return "approaching";
    case VehicleMotion::RECEDING:
        return "receding";
    default:
        return "unknown";
    }
}

static VehicleMotion update_vehicle_motion(int track_id, const HailoBBox &bbox)
{
    if (track_id < 0)
        return VehicleMotion::UNKNOWN;

    constexpr float AREA_RATIO_THRESHOLD = 0.05f;
    const float area = bbox.width() * bbox.height();
    if (area <= 0.0f)
        return VehicleMotion::UNKNOWN;

    std::lock_guard<std::mutex> lock(g_vehicle_motion_mutex);
    auto it = g_vehicle_last_area.find(track_id);
    if (it == g_vehicle_last_area.end())
    {
        g_vehicle_last_area[track_id] = area;
        return VehicleMotion::UNKNOWN;
    }

    const float prev_area = it->second;
    it->second = area;
    if (prev_area <= 0.0f)
        return VehicleMotion::UNKNOWN;

    const float ratio = area / prev_area;
    if (ratio > (1.0f + AREA_RATIO_THRESHOLD))
        return VehicleMotion::APPROACHING;
    if (ratio < (1.0f - AREA_RATIO_THRESHOLD))
        return VehicleMotion::RECEDING;
    return VehicleMotion::UNKNOWN;
}

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
    if (lpr_no_skip_enabled())
        return false;
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

/**
 * @brief Check if a detection has a classification of a specific type
 * 
 * @param detection The detection object to check
 * @param classification_type The classification type to look for (empty string = any classification)
 * @param label Optional pointer to store the classification label
 * @return true if classification found, false otherwise
 */
static bool detection_has_classification(const HailoDetectionPtr &detection, 
                                         const std::string &classification_type = "",
                                         std::string *label = nullptr)
{
    if (lpr_no_skip_enabled())
        return false;
    if (!detection)
        return false;
    
    auto classifications = detection->get_objects_typed(HAILO_CLASSIFICATION);
    if (classifications.empty())
        return false;
    
    for (auto &obj : classifications)
    {
        auto cls = std::dynamic_pointer_cast<HailoClassification>(obj);
        if (!cls)
            continue;
        
        if (classification_type.empty() || 
            cls->get_classification_type() == classification_type)
        {
            if (label)
                *label = cls->get_label();
            return true;
        }
    }
    return false;
}

static bool track_seen(int track_id)
{
    if (lpr_no_skip_enabled())
        return false;
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

static bool lpr_debug_all_frames()
{
    static int enabled = -1;
    if (enabled == -1)
    {
        const char *val = std::getenv("HAILO_LPR_DEBUG_ALL_FRAMES");
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

static bool lpr_no_skip_enabled()
{
    static int enabled = -1;
    if (enabled == -1)
    {
        const char *val = std::getenv("HAILO_LPR_NO_SKIP");
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
        if (lpr_debug_all_frames())
            return 1;
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

static float get_min_vehicle_confidence()
{
    static float min_conf = -1.0f;
    if (min_conf < 0.0f)
    {
        min_conf = parse_env_float("HAILO_LPR_MIN_VEHICLE_CONFIDENCE", DEFAULT_MIN_VEHICLE_CONFIDENCE);
        if (min_conf < 0.0f)
            min_conf = DEFAULT_MIN_VEHICLE_CONFIDENCE;
    }
    return min_conf;
}

static int parse_env_int(const char *env_name, int default_val)
{
    const char *val = std::getenv(env_name);
    if (val && val[0] != '\0')
    {
        char *end = nullptr;
        long parsed = std::strtol(val, &end, 10);
        if (end != val)
            return static_cast<int>(parsed);
    }
    return default_val;
}

static int get_min_vehicle_width_px()
{
    static int min_width = -1;
    if (min_width < 0)
    {
        min_width = parse_env_int("HAILO_LPR_MIN_VEHICLE_WIDTH_PX", DEFAULT_MIN_VEHICLE_WIDTH_PX);
        if (min_width < 0)
            min_width = DEFAULT_MIN_VEHICLE_WIDTH_PX;
    }
    return min_width;
}

static int get_min_vehicle_height_px()
{
    static int min_height = -1;
    if (min_height < 0)
    {
        min_height = parse_env_int("HAILO_LPR_MIN_VEHICLE_HEIGHT_PX", DEFAULT_MIN_VEHICLE_HEIGHT_PX);
        if (min_height < 0)
            min_height = DEFAULT_MIN_VEHICLE_HEIGHT_PX;
    }
    return min_height;
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
 * Lightweight validation for license_plate_no_quality cropper.
 * Performs basic size, brightness, and contrast checks without expensive operations.
 *
 * @param image The full image
 * @param bbox The license plate bounding box (normalized 0-1)
 * @param crop_w Width in pixels (already calculated)
 * @param crop_h Height in pixels (already calculated)
 * @param reject_reason Output parameter for rejection reason string
 * @return true if validation passes, false otherwise
 */
static bool validate_lp_crop_lightweight(
    std::shared_ptr<HailoMat> image,
    const HailoBBox &bbox,
    int crop_w,
    int crop_h,
    const char **reject_reason)
{
    // Size validation (updated from 10x5 to 40x15)
    if (crop_w < LP_NO_QUALITY_MIN_WIDTH_PX || crop_h < LP_NO_QUALITY_MIN_HEIGHT_PX)
    {
        *reject_reason = "too_small_px";
        return false;
    }

    // Get grayscale crop for image quality checks
    cv::Mat gray = get_gray_crop(image, bbox);
    if (gray.empty())
    {
        *reject_reason = "empty_gray_crop";
        return false;
    }

    // Brightness validation
    float brightness = calculate_brightness(gray);
    if (brightness < LP_NO_QUALITY_MIN_BRIGHTNESS)
    {
        *reject_reason = "too_dark";
        return false;
    }
    if (brightness > LP_NO_QUALITY_MAX_BRIGHTNESS)
    {
        *reject_reason = "too_bright";
        return false;
    }

    // Contrast validation
    float contrast = calculate_contrast(gray);
    if (contrast < LP_NO_QUALITY_MIN_CONTRAST)
    {
        *reject_reason = "low_contrast";
        return false;
    }

    return true;
}

/**
 * @brief Calculate the variance of edges in the image.
 *        This is a simpler quality estimation method that calculates
 *        the variance of Laplacian (edge variance) for quality assessment.
 *
 * @param hailo_mat  -  std::shared_ptr<HailoMat>
 *        The image to analyze.
 *
 * @param roi  -  HailoBBox
 *        The bounding box of the region of interest (license plate).
 *
 * @param crop_ratio  -  float
 *        The crop ratio to apply around the ROI (default 0.1).
 *
 * @return float
 *         The variance of edges in the image (higher = sharper/better quality).
 */
static float quality_estimation(std::shared_ptr<HailoMat> hailo_mat, const HailoBBox &roi, const float crop_ratio = 0.1f)
{
    if (!hailo_mat)
        return 0.0f;

    // Apply crop ratio to expand the ROI slightly for better edge detection
    float w = roi.width();
    float h = roi.height();
    float pad_x = w * crop_ratio;
    float pad_y = h * crop_ratio;

    float xmin = std::max(0.0f, roi.xmin() - pad_x);
    float ymin = std::max(0.0f, roi.ymin() - pad_y);
    float xmax = std::min(1.0f, roi.xmax() + pad_x);
    float ymax = std::min(1.0f, roi.ymax() + pad_y);

    if (xmax <= xmin || ymax <= ymin)
        return 0.0f;

    // Get grayscale crop
    cv::Mat gray = get_gray_crop(hailo_mat, HailoBBox(xmin, ymin, xmax - xmin, ymax - ymin));
    if (gray.empty())
        return 0.0f;

    // Calculate Laplacian variance (same as blur score)
    return calculate_blur_score(gray);
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
        return true;  // Enabled by default for debugging - set HAILO_LPR_SAVE_CROPS=0 to disable
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

static float bbox_intersection_area(const HailoBBox &a, const HailoBBox &b)
{
    float xmin = std::max(a.xmin(), b.xmin());
    float ymin = std::max(a.ymin(), b.ymin());
    float xmax = std::min(a.xmax(), b.xmax());
    float ymax = std::min(a.ymax(), b.ymax());
    if (xmax <= xmin || ymax <= ymin)
        return 0.0f;
    return (xmax - xmin) * (ymax - ymin);
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
    // Always output to stderr to confirm function is called
    static std::atomic<int> s_vehicle_cropper_calls{0};
    int call_id = s_vehicle_cropper_calls.fetch_add(1) + 1;
    // Silenced: std::cerr << "[veh_crop_entry] call=" << call_id << std::flush;
    
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


        if (detection->get_confidence() < get_min_vehicle_confidence())
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
        const int v_w_px = static_cast<int>(clamped_vehicle_bbox.width() * image->width());
        const int v_h_px = static_cast<int>(clamped_vehicle_bbox.height() * image->height());
        
        // Check minimum vehicle size in pixels (for OCR to work well)
        const int min_veh_w = get_min_vehicle_width_px();
        const int min_veh_h = get_min_vehicle_height_px();
        if (v_w_px < min_veh_w || v_h_px < min_veh_h)
        {
            // Debug: show skipped small vehicles
            static std::atomic<int> s_small_vehicle_count{0};
            int skip_count = s_small_vehicle_count.fetch_add(1) + 1;
            if (skip_count <= 20 || (skip_count % 100) == 0)
            {
                // Silenced: std::cerr << "[veh_skip_small] ...";
            }
            det_idx++;
            continue;
        }
        if (!is_nonempty_crop(image, clamped_vehicle_bbox))
        {
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
                // Check if vehicle detection has a classification
                // Example: Check for any classification
                if (detection_has_classification(detection))
                {
                    std::string cls_label;
                    detection_has_classification(detection, "", &cls_label);
                    // You can add logic here to skip or process differently
                    det_idx++;
                    continue;
                }
                // Example: Check for a specific classification type
                // if (detection_has_classification(detection, "vehicle_classification"))
                // {
                //     // Handle specific classification type
                // }
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
            if (!is_nonempty_crop(image, padded_bbox))
            {
                lpr_dbg("%s REJECT reason=empty_crop veh=%d lp=%d size_px=%.1fx%.1f bbox=[%.3f,%.3f,%.3f,%.3f]",
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
    lpr_dbg("%s ENTER frame_id=%d detections=%zu vehicles=%zu top_lp=%zu",
            crop_name, frame_id, detections.size(), vehicles.size(), top_lp_ptrs.size());

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

        // Check if vehicle has a classification - if so, remove all LPs for this vehicle
        if (detection_has_classification(vehicle))
        {
            std::string cls_label;
            detection_has_classification(vehicle, "", &cls_label);
            lpr_dbg("%s SKIP veh=%d track_id=%d has classification '%s' - removing all LPs",
                    crop_name, veh_idx, track_id, cls_label.c_str());
            
            // Remove all license plates from this vehicle
            std::vector<HailoDetectionPtr> lp_detections = hailo_common::get_hailo_detections(vehicle);
            for (auto &lp_det : lp_detections)
            {
                if (lp_det && lp_det->get_label() == LICENSE_PLATE_LABEL)
                {
                    vehicle->remove_object(lp_det);
                }
            }
            veh_idx++;
            continue;
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

            // Flatten LP bbox from vehicle crop coordinates to full frame coordinates
            HailoBBox lp_flat = hailo_common::create_flattened_bbox(
                license_plate->get_bbox(),
                license_plate->get_scaling_bbox());

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
            const char *reject_reason = nullptr;
            if (!validate_lp_crop_lightweight(image, clamped_bbox, crop_w, crop_h, &reject_reason))
            {
                lpr_dbg("%s REJECT reason=%s veh=%d lp=%d size_px=%dx%d",
                        crop_name, reject_reason, veh_idx, lp_idx, crop_w, crop_h);
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
            const char *reject_reason = nullptr;
            if (!validate_lp_crop_lightweight(image, clamped_bbox, crop_w, crop_h, &reject_reason))
            {
                lpr_dbg("%s REJECT reason=%s lp=%d size_px=%dx%d",
                        crop_name, reject_reason, lp_idx, crop_w, crop_h);
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

std::vector<HailoROIPtr> lp_simple_cropper(std::shared_ptr<HailoMat> image, HailoROIPtr roi)
{
    lpr_log_settings();
    std::vector<HailoROIPtr> crop_rois;
    const char *crop_name = "lp_simple_ocr";
    const char *sent_prefix = "SENT_lp_simple_ocr";
    const char *reject_prefix = "REJECT_lp_simple_ocr";
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
    lpr_dbg("%s ENTER frame_id=%d detections=%zu vehicles=%zu top_lp=%zu",
            crop_name, frame_id, detections.size(), vehicles.size(), top_lp_ptrs.size());

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

        if (detection_has_classification(vehicle))
        {
            std::string cls_label;
            detection_has_classification(vehicle, "", &cls_label);
            lpr_dbg("%s SKIP veh=%d track_id=%d has classification '%s' - removing all LPs",
                    crop_name, veh_idx, track_id, cls_label.c_str());

            std::vector<HailoDetectionPtr> lp_detections = hailo_common::get_hailo_detections(vehicle);
            for (auto &lp_det : lp_detections)
            {
                if (lp_det && lp_det->get_label() == LICENSE_PLATE_LABEL)
                {
                    vehicle->remove_object(lp_det);
                }
            }
            veh_idx++;
            continue;
        }

        HailoBBox v_bbox = vehicle->get_bbox();
        HailoBBox v_clamped(0.0f, 0.0f, 0.0f, 0.0f);
        int v_w_px = 0;
        int v_h_px = 0;
        if (!clamp_bbox_to_pixels(v_bbox, img_w, img_h, v_clamped, v_w_px, v_h_px))
        {
            lpr_dbg("%s REJECT reason=invalid_vehicle_bbox veh=%d", crop_name, veh_idx);
            veh_idx++;
            continue;
        }
        float vehicle_area_px = static_cast<float>(v_w_px) * static_cast<float>(v_h_px);

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

        HailoDetectionPtr best_plate;
        HailoBBox best_clamped_bbox(0.0f, 0.0f, 0.0f, 0.0f);
        float best_rel_area = 0.0f;
        float best_score = 0.0f;
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

            // Use exact LP coordinates with proper flattening (no padding/expansion)
            HailoBBox lp_flat = hailo_common::create_flattened_bbox(
                license_plate->get_bbox(),
                license_plate->get_scaling_bbox());

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
            const char *reject_reason = nullptr;
            if (!validate_lp_crop_lightweight(image, clamped_bbox, crop_w, crop_h, &reject_reason))
            {
                lpr_dbg("%s REJECT reason=%s veh=%d lp=%d size_px=%dx%d",
                        crop_name, reject_reason, veh_idx, lp_idx, crop_w, crop_h);
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

            float aspect = (crop_h > 0) ? (static_cast<float>(crop_w) / crop_h) : 0.0f;
            if (aspect < LP_SIMPLE_MIN_ASPECT || aspect > LP_SIMPLE_MAX_ASPECT)
            {
                lpr_dbg("%s REJECT reason=bad_aspect veh=%d lp=%d aspect=%.2f",
                        crop_name, veh_idx, lp_idx, aspect);
                lp_idx++;
                continue;
            }

            float lp_area_px = static_cast<float>(w_px) * static_cast<float>(h_px);
            float rel_area = (vehicle_area_px > 0.0f) ? (lp_area_px / vehicle_area_px) : 0.0f;
            if (rel_area < MIN_LP_REL_AREA || rel_area > MAX_LP_REL_AREA)
            {
                lpr_dbg("%s REJECT reason=rel_area veh=%d lp=%d rel_area=%.4f",
                        crop_name, veh_idx, lp_idx, rel_area);
                lp_idx++;
                continue;
            }

            float lp_area_norm = clamped_bbox.width() * clamped_bbox.height();
            float inter_area = bbox_intersection_area(clamped_bbox, v_clamped);
            float inside_ratio = (lp_area_norm > 0.0f) ? (inter_area / lp_area_norm) : 0.0f;
            if (inside_ratio < LP_SIMPLE_MIN_INSIDE_RATIO)
            {
                lpr_dbg("%s REJECT reason=outside_vehicle veh=%d lp=%d inside_ratio=%.2f",
                        crop_name, veh_idx, lp_idx, inside_ratio);
                lp_idx++;
                continue;
            }

            float score = rel_area;
            float conf = license_plate->get_confidence();
            if (conf > 0.0f)
                score *= conf;

            if (score > best_score)
            {
                best_plate = license_plate;
                best_clamped_bbox = clamped_bbox;
                best_rel_area = rel_area;
                best_score = score;
                best_crop_w = crop_w;
                best_crop_h = crop_h;
            }
            lp_idx++;
        }

        if (best_plate)
        {
            best_plate->set_bbox(best_clamped_bbox);
            best_plate->set_scaling_bbox(HailoBBox(0.0f, 0.0f, 1.0f, 1.0f));
            attach_tracking_id_if_missing(best_plate, track_id);

            lpr_dbg("%s SEND veh=%d track_id=%d rel_area=%.4f score=%.4f bbox=[%.3f,%.3f,%.3f,%.3f] size_px=%dx%d img=%dx%d",
                    crop_name, veh_idx, track_id, best_rel_area, best_score,
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

    return crop_rois;
}

std::vector<HailoROIPtr> license_plate_no_quality_simple(std::shared_ptr<HailoMat> image, HailoROIPtr roi)
{
    lpr_log_settings();
    std::vector<HailoROIPtr> crop_rois;
    const char *crop_name = "lp_no_quality_simple_ocr";
    const char *sent_prefix = "SENT_lp_no_quality_simple_ocr";
    const char *reject_prefix = "REJECT_lp_no_quality_simple_ocr";
    const int frame_id = g_lp_frame_counter.fetch_add(1);

    if (!image || !roi)
    {
        std::cout << "[LP_SIMPLE] REJECT null_input" << std::endl << std::flush;
        return crop_rois;
    }

    const int img_w = image->width();
    const int img_h = image->height();
    if (img_w <= 0 || img_h <= 0)
    {
        std::cout << "[LP_SIMPLE] REJECT invalid_image_size size=" << img_w << "x" << img_h
                  << std::endl << std::flush;
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

    std::unordered_set<const HailoDetection *> seen_lps;

    int veh_idx = 0;
    for (HailoDetectionPtr &vehicle : vehicles)
    {
        if (!vehicle)
        {
            veh_idx++;
            continue;
        }

        int track_id = get_tracking_id(vehicle);
        HailoBBox v_bbox = vehicle->get_bbox();
        float vehicle_area = v_bbox.width() * v_bbox.height();
        std::vector<HailoDetectionPtr> license_plate_ptrs = hailo_common::get_hailo_detections(vehicle);

        int lp_idx = 0;
        for (HailoDetectionPtr &license_plate : license_plate_ptrs)
        {
            if (!license_plate)
            {
                lp_idx++;
                continue;
            }
            if (seen_lps.find(license_plate.get()) != seen_lps.end())
            {
                lp_idx++;
                continue;
            }
            seen_lps.insert(license_plate.get());

            std::string lp_label = license_plate->get_label();
            if (LICENSE_PLATE_LABEL != lp_label)
            {
                std::cout << "[LP_SIMPLE] REJECT label veh=" << veh_idx
                          << " lp=" << lp_idx << " label='" << lp_label << "'" << std::endl << std::flush;
                lp_idx++;
                continue;
            }

            // Flatten LP bbox from vehicle crop coordinates to full frame coordinates
            HailoBBox lp_flat = hailo_common::create_flattened_bbox(
                license_plate->get_bbox(),
                license_plate->get_scaling_bbox());
            HailoBBox clamped_bbox(0.0f, 0.0f, 0.0f, 0.0f);
            int w_px = 0;
            int h_px = 0;
            if (!clamp_bbox_to_pixels(lp_flat, img_w, img_h, clamped_bbox, w_px, h_px))
            {
                std::cout << "[LP_SIMPLE] REJECT invalid_bbox veh=" << veh_idx
                          << " lp=" << lp_idx << std::endl << std::flush;
                lp_idx++;
                continue;
            }
            int crop_w = 0;
            int crop_h = 0;
            if (!get_crop_dims(image, clamped_bbox, crop_w, crop_h))
            {
                std::cout << "[LP_SIMPLE] REJECT empty_crop veh=" << veh_idx
                          << " lp=" << lp_idx << std::endl << std::flush;
                lp_idx++;
                continue;
            }
            if (crop_w < DEFAULT_LP_SIMPLE_MIN_WIDTH_PX || crop_h < DEFAULT_LP_SIMPLE_MIN_HEIGHT_PX)
            {
                std::cout << "[LP_SIMPLE] REJECT too_small_px veh=" << veh_idx
                          << " lp=" << lp_idx << " size_px=" << crop_w << "x" << crop_h
                          << std::endl << std::flush;
                lp_idx++;
                continue;
            }
            if (!vehicle_inside_roi(clamped_bbox))
            {
                std::cout << "[LP_SIMPLE] REJECT outside_roi veh=" << veh_idx
                          << " lp=" << lp_idx << std::endl << std::flush;
                int crop_id = g_lp_crop_counter.fetch_add(1);
                save_crop_image(image, clamped_bbox, reject_prefix, crop_id, track_id);
                lp_idx++;
                continue;
            }

            // Check if LP center is inside the vehicle bbox
            float cx = clamped_bbox.xmin() + 0.5f * clamped_bbox.width();
            float cy = clamped_bbox.ymin() + 0.5f * clamped_bbox.height();
            bool inside_vehicle = (cx >= v_bbox.xmin() && cx <= v_bbox.xmax() &&
                                   cy >= v_bbox.ymin() && cy <= v_bbox.ymax());
            if (!inside_vehicle)
            {
                std::cout << "[LP_SIMPLE] REJECT outside_vehicle veh=" << veh_idx
                          << " lp=" << lp_idx << std::endl << std::flush;
                int crop_id = g_lp_crop_counter.fetch_add(1);
                save_crop_image(image, clamped_bbox, reject_prefix, crop_id, track_id);
                lp_idx++;
                continue;
            }

            // Check relative area threshold
            float lp_area = clamped_bbox.width() * clamped_bbox.height();
            float rel_area = (vehicle_area > 0.0f) ? (lp_area / vehicle_area) : 0.0f;
            if (rel_area < MIN_LP_REL_AREA)
            {
                std::cout << "[LP_SIMPLE] REJECT too_small_rel veh=" << veh_idx
                          << " lp=" << lp_idx << " rel_area=" << rel_area << std::endl << std::flush;
                lp_idx++;
                continue;
            }

            license_plate->set_bbox(clamped_bbox);
            license_plate->set_scaling_bbox(HailoBBox(0.0f, 0.0f, 1.0f, 1.0f));
            attach_tracking_id_if_missing(license_plate, track_id);

            lpr_dbg("%s SEND veh=%d lp=%d track_id=%d bbox=[%.3f,%.3f,%.3f,%.3f] size_px=%dx%d img=%dx%d",
                    crop_name, veh_idx, lp_idx, track_id,
                    clamped_bbox.xmin(), clamped_bbox.ymin(), clamped_bbox.width(), clamped_bbox.height(),
                    crop_w, crop_h, img_w, img_h);
            std::cout << "[LP_SIMPLE] SEND veh=" << veh_idx << " lp=" << lp_idx
                      << " track_id=" << track_id << " size_px=" << crop_w << "x" << crop_h
                      << std::endl << std::flush;

            int crop_id = g_lp_crop_counter.fetch_add(1);
            save_crop_image(image, clamped_bbox, sent_prefix, crop_id, track_id);
            attach_crop_meta(license_plate, crop_id, frame_id);
            track_ocr_lp_to_ocr(track_id);
            crop_rois.emplace_back(license_plate);
            lp_idx++;
        }
        veh_idx++;
    }

    int lp_idx = 0;
    for (auto &lp_det : top_lp_ptrs)
    {
        if (!lp_det)
        {
            lp_idx++;
            continue;
        }
        if (seen_lps.find(lp_det.get()) != seen_lps.end())
        {
            lp_idx++;
            continue;
        }
        seen_lps.insert(lp_det.get());

        std::string lp_label = lp_det->get_label();
        if (LICENSE_PLATE_LABEL != lp_label)
        {
            std::cout << "[LP_SIMPLE] REJECT label veh=-1 lp=" << lp_idx
                      << " label='" << lp_label << "'" << std::endl << std::flush;
            lp_idx++;
            continue;
        }

        HailoBBox lp_flat = lp_det->get_bbox();
        HailoBBox clamped_bbox(0.0f, 0.0f, 0.0f, 0.0f);
        int w_px = 0;
        int h_px = 0;
        if (!clamp_bbox_to_pixels(lp_flat, img_w, img_h, clamped_bbox, w_px, h_px))
        {
            std::cout << "[LP_SIMPLE] REJECT invalid_bbox veh=-1 lp=" << lp_idx
                      << std::endl << std::flush;
            lp_idx++;
            continue;
        }
        int crop_w = 0;
        int crop_h = 0;
        if (!get_crop_dims(image, clamped_bbox, crop_w, crop_h))
        {
            std::cout << "[LP_SIMPLE] REJECT empty_crop veh=-1 lp=" << lp_idx
                      << std::endl << std::flush;
            lp_idx++;
            continue;
        }
        if (crop_w < DEFAULT_LP_SIMPLE_MIN_WIDTH_PX || crop_h < DEFAULT_LP_SIMPLE_MIN_HEIGHT_PX)
        {
            std::cout << "[LP_SIMPLE] REJECT too_small_px veh=-1 lp=" << lp_idx
                      << " size_px=" << crop_w << "x" << crop_h << std::endl << std::flush;
            lp_idx++;
            continue;
        }
        if (!vehicle_inside_roi(clamped_bbox))
        {
            int track_id = get_tracking_id(lp_det);
            std::cout << "[LP_SIMPLE] REJECT outside_roi veh=-1 lp=" << lp_idx
                      << std::endl << std::flush;
            int crop_id = g_lp_crop_counter.fetch_add(1);
            save_crop_image(image, clamped_bbox, reject_prefix, crop_id, track_id);
            lp_idx++;
            continue;
        }

        lp_det->set_bbox(clamped_bbox);
        lp_det->set_scaling_bbox(HailoBBox(0.0f, 0.0f, 1.0f, 1.0f));
        int track_id = get_tracking_id(lp_det);
        attach_tracking_id_if_missing(lp_det, track_id);

        lpr_dbg("%s SEND veh=-1 lp=%d track_id=%d bbox=[%.3f,%.3f,%.3f,%.3f] size_px=%dx%d img=%dx%d",
                crop_name, lp_idx, track_id,
                clamped_bbox.xmin(), clamped_bbox.ymin(), clamped_bbox.width(), clamped_bbox.height(),
                crop_w, crop_h, img_w, img_h);
        std::cout << "[LP_SIMPLE] SEND veh=-1 lp=" << lp_idx
                  << " track_id=" << track_id << " size_px=" << crop_w << "x" << crop_h
                  << std::endl << std::flush;

        int crop_id = g_lp_crop_counter.fetch_add(1);
        save_crop_image(image, clamped_bbox, sent_prefix, crop_id, track_id);
        attach_crop_meta(lp_det, crop_id, frame_id);
        track_ocr_lp_to_ocr(track_id);
        crop_rois.emplace_back(lp_det);
        lp_idx++;
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

            // Flatten LP bbox from vehicle crop coordinates to full frame coordinates
            HailoBBox lp_flat = hailo_common::create_flattened_bbox(
                license_plate->get_bbox(),
                license_plate->get_scaling_bbox());

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

std::vector<HailoROIPtr> license_plate_no_quality_four_best(std::shared_ptr<HailoMat> image, HailoROIPtr roi)
{
    lpr_log_settings();
    std::vector<HailoROIPtr> crop_rois;
    const char *crop_name = "lp_no_quality_four_best_ocr";
    const char *sent_prefix = "SENT_lp_no_quality_four_best_ocr";
    const char *reject_prefix = "REJECT_lp_no_quality_four_best_ocr";
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

        // Candidate structure for tracking best four plates
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
                // Try to save crop even with wrong label if bbox is valid
                // Flatten LP bbox from vehicle crop coordinates to full frame coordinates
                HailoBBox lp_flat = hailo_common::create_flattened_bbox(
                    license_plate->get_bbox(),
                    license_plate->get_scaling_bbox());
                HailoBBox clamped_bbox(0.0f, 0.0f, 0.0f, 0.0f);
                int w_px = 0;
                int h_px = 0;
                if (clamp_bbox_to_pixels(lp_flat, img_w, img_h, clamped_bbox, w_px, h_px))
                {
                    int crop_id = g_lp_crop_counter.fetch_add(1);
                    save_crop_image(image, clamped_bbox, reject_prefix, crop_id, track_id);
                }
                lp_idx++;
                continue;
            }

            // Flatten LP bbox from vehicle crop coordinates to full frame coordinates
            HailoBBox lp_flat = hailo_common::create_flattened_bbox(
                license_plate->get_bbox(),
                license_plate->get_scaling_bbox());

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
                int crop_id = g_lp_crop_counter.fetch_add(1);
                save_crop_image(image, clamped_bbox, reject_prefix, crop_id, track_id);
                lp_idx++;
                continue;
            }
            if (crop_w < 10 || crop_h < 5)
            {
                lpr_dbg("%s REJECT reason=too_small_px veh=%d lp=%d size_px=%dx%d",
                        crop_name, veh_idx, lp_idx, crop_w, crop_h);
                int crop_id = g_lp_crop_counter.fetch_add(1);
                save_crop_image(image, clamped_bbox, reject_prefix, crop_id, track_id);
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
                int crop_id = g_lp_crop_counter.fetch_add(1);
                save_crop_image(image, clamped_bbox, reject_prefix, crop_id, track_id);
                lp_idx++;
                continue;
            }

            // Add to valid candidates
            valid_candidates.push_back({license_plate, clamped_bbox, rel_area, crop_w, crop_h});
            lp_idx++;
        }

        // Sort candidates by relative area (descending) and take top 4
        std::sort(valid_candidates.begin(), valid_candidates.end(),
                  [](const LpCandidate &a, const LpCandidate &b) { return a.rel_area > b.rel_area; });

        size_t num_to_send = std::min(valid_candidates.size(), static_cast<size_t>(4));
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

        // Save crops for candidates that didn't make it into top 4 (rejected due to ranking)
        for (size_t i = num_to_send; i < valid_candidates.size(); i++)
        {
            LpCandidate &candidate = valid_candidates[i];
            int crop_id = g_lp_crop_counter.fetch_add(1);
            save_crop_image(image, candidate.clamped_bbox, reject_prefix, crop_id, track_id);
            lpr_dbg("%s REJECT reason=not_top4 veh=%d rank=%zu track_id=%d rel_area=%.4f",
                    crop_name, veh_idx, i + 1, track_id, candidate.rel_area);
        }
        veh_idx++;
    }

    // Fallback: if no plates found via vehicles, try top-level LPs (send up to 4)
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
                int crop_id = g_lp_crop_counter.fetch_add(1);
                int track_id = get_tracking_id(lp_det);
                save_crop_image(image, clamped_bbox, reject_prefix, crop_id, track_id);
                lp_idx++;
                continue;
            }
            if (crop_w < 10 || crop_h < 5)
            {
                lpr_dbg("%s REJECT reason=too_small_px lp=%d size_px=%dx%d",
                        crop_name, lp_idx, crop_w, crop_h);
                int crop_id = g_lp_crop_counter.fetch_add(1);
                int track_id = get_tracking_id(lp_det);
                save_crop_image(image, clamped_bbox, reject_prefix, crop_id, track_id);
                lp_idx++;
                continue;
            }
            if (!vehicle_inside_roi(clamped_bbox))
            {
                lpr_dbg("%s REJECT reason=outside_roi lp=%d", crop_name, lp_idx);
                int crop_id = g_lp_crop_counter.fetch_add(1);
                int track_id = get_tracking_id(lp_det);
                save_crop_image(image, clamped_bbox, reject_prefix, crop_id, track_id);
                lp_idx++;
                continue;
            }
            valid_top_lps.push_back({lp_det, clamped_bbox, crop_w, crop_h});
            lp_idx++;
        }

        // Sort by crop size (area) descending and take top 4
        std::sort(valid_top_lps.begin(), valid_top_lps.end(),
                  [](const LpCandidate &a, const LpCandidate &b) {
                      return (a.crop_w * a.crop_h) > (b.crop_w * b.crop_h);
                  });

        size_t num_to_send = std::min(valid_top_lps.size(), static_cast<size_t>(4));
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

        // Save crops for top-level LPs that didn't make it into top 4 (rejected due to ranking)
        for (size_t i = num_to_send; i < valid_top_lps.size(); i++)
        {
            LpCandidate &candidate = valid_top_lps[i];
            int track_id = get_tracking_id(candidate.plate);
            int crop_id = g_lp_crop_counter.fetch_add(1);
            save_crop_image(image, candidate.clamped_bbox, reject_prefix, crop_id, track_id);
            lpr_dbg("%s REJECT reason=not_top4 lp=%zu track_id=%d",
                    crop_name, i, track_id);
        }
    }

    return crop_rois;
}

/**
 * @brief Returns a vector of HailoROIPtr to crop and resize.
 *        Specific to LPR pipelines, this function assumes that
 *        license plate ROIs are nested inside vehicle detection ROIs.
 *        This function performs quality estimation using variance of edges
 *        and applies good padding before passing plates to OCR.
 *
 * @param image  -  std::shared_ptr<HailoMat>
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
    lpr_log_settings();
    std::vector<HailoROIPtr> crop_rois;
    float variance;
    LpQualityConfig config = get_lp_quality_config();
    const int frame_id = g_lp_frame_counter.fetch_add(1);
    const char *crop_name = "lp_quality_estimation_ocr";
    const char *sent_prefix = "SENT_lp_quality_estimation_ocr";
    const char *reject_prefix = "REJECT_lp_quality_estimation_ocr";

    // Log crop saving status
    const bool save_enabled = lpr_save_crops_enabled();
    lpr_dbg("%s ENTER save_crops=%d crops_dir='%s'", crop_name, save_enabled ? 1 : 0, get_crops_dir());

    if (!image || !roi)
    {
        lpr_dbg("%s REJECT reason=null_input", crop_name);
        return crop_rois;
    }

    load_lpr_state_from_jsonl();
    refresh_lpr_state_from_jsonl();

    // Get all detections.
    std::vector<HailoDetectionPtr> vehicle_ptrs = hailo_common::get_hailo_detections(roi);
    int veh_idx = 0;
    for (HailoDetectionPtr &vehicle : vehicle_ptrs)
    {
        if (VEHICLE_LABEL != vehicle->get_label())
        {
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

        // For each detection, check the inner detections
        std::vector<HailoDetectionPtr> license_plate_ptrs = hailo_common::get_hailo_detections(vehicle);
        int lp_idx = 0;
        for (HailoDetectionPtr &license_plate : license_plate_ptrs)
        {
            if (LICENSE_PLATE_LABEL != license_plate->get_label())
            {
                lp_idx++;
                continue;
            }

            HailoBBox license_plate_box = hailo_common::create_flattened_bbox(
                license_plate->get_bbox(),
                license_plate->get_scaling_bbox());

            // Get the variance of the image, only add ROIs that are above threshold.
            variance = quality_estimation(image, license_plate_box, CROP_RATIO);

            if (variance >= QUALITY_THRESHOLD)
            {
                // Apply good padding before sending to OCR
                HailoBBox padded_bbox = apply_lp_padding(license_plate_box, config);

                // Ensure padded bbox is valid
                const float lp_px_w = padded_bbox.width() * image->width();
                const float lp_px_h = padded_bbox.height() * image->height();
                if (padded_bbox.width() <= 0.0f || padded_bbox.height() <= 0.0f ||
                    lp_px_w < 35.0f || lp_px_h < 20.0f)
                {
                    lpr_dbg("%s REJECT reason=too_small_padded veh=%d lp=%d variance=%.2f size_px=%.1fx%.1f",
                            crop_name, veh_idx, lp_idx, variance, lp_px_w, lp_px_h);
                    int crop_id = g_lp_crop_counter.fetch_add(1);
                    save_crop_image(image, padded_bbox, reject_prefix, crop_id, track_id);
                    lp_idx++;
                    continue;
                }
                if (!is_nonempty_crop(image, padded_bbox))
                {
                    lpr_dbg("%s REJECT reason=empty_crop veh=%d lp=%d variance=%.2f size_px=%.1fx%.1f",
                            crop_name, veh_idx, lp_idx, variance, lp_px_w, lp_px_h);
                    int crop_id = g_lp_crop_counter.fetch_add(1);
                    save_crop_image(image, padded_bbox, reject_prefix, crop_id, track_id);
                    lp_idx++;
                    continue;
                }

                // Update the license plate bbox with padded version
                license_plate->set_bbox(padded_bbox);
                license_plate->set_scaling_bbox(HailoBBox(0.0f, 0.0f, 1.0f, 1.0f));
                attach_tracking_id_if_missing(license_plate, track_id);

                lpr_dbg("%s SEND veh=%d lp=%d track_id=%d variance=%.2f bbox=[%.3f,%.3f,%.3f,%.3f] size_px=%.1fx%.1f",
                        crop_name, veh_idx, lp_idx, track_id, variance,
                        padded_bbox.xmin(), padded_bbox.ymin(), padded_bbox.width(), padded_bbox.height(),
                        lp_px_w, lp_px_h);

                int crop_id = g_lp_crop_counter.fetch_add(1);
                save_crop_image(image, padded_bbox, sent_prefix, crop_id, track_id);
                attach_crop_meta(license_plate, crop_id, frame_id);
                crop_rois.emplace_back(license_plate);
            }
            else
            {
                // If it is not a good license plate, then remove it!
                lpr_dbg("%s REJECT reason=low_variance veh=%d lp=%d variance=%.2f < %.2f",
                        crop_name, veh_idx, lp_idx, variance, QUALITY_THRESHOLD);
                int crop_id = g_lp_crop_counter.fetch_add(1);
                save_crop_image(image, license_plate_box, reject_prefix, crop_id, track_id);
                vehicle->remove_object(license_plate);
            }
            lp_idx++;
        }
        veh_idx++;
    }
    return crop_rois;
}

/**
 * @brief Minimal license plate cropper - sends all valid LPs to OCR with minimal filtering.
 *
 * This cropper performs only essential validation:
 * - Non-null inputs
 * - Correct label ("license_plate")
 * - Valid bounding box (non-zero, within image bounds)
 * - Minimum pixel size (configurable via env, default 5x3)
 *
 * No quality checks, no ROI filtering, no track caching, no best-plate selection.
 * Sends ALL detected license plates to OCR.
 */
std::vector<HailoROIPtr> license_plate_minimal(
    std::shared_ptr<HailoMat> vehicle_crop,  // This is a vehicle crop, not full frame!
    HailoROIPtr roi)
{
    lpr_log_settings();
    std::vector<HailoROIPtr> crop_rois;
    const char *crop_name = "lp_minimal_ocr";
    const char *sent_prefix = "SENT_lp_minimal_ocr";
    const char *reject_prefix = "REJECT_lp_minimal_ocr";
    const int frame_id = g_lp_frame_counter.fetch_add(1);

    load_lpr_state_from_jsonl();
    refresh_lpr_state_from_jsonl();
    
    // Debug output silenced - only OCR debug is active
    if (!vehicle_crop || !roi)
        return crop_rois;

    // Image dimensions are the VEHICLE CROP dimensions
    const int crop_w = vehicle_crop->width();
    const int crop_h = vehicle_crop->height();
    if (crop_w <= 0 || crop_h <= 0)
        return crop_rois;

    // Check if ROI is a HailoDetection
    auto vehicle_detection = std::dynamic_pointer_cast<HailoDetection>(roi);

    // Get track ID from the ROI (this is the vehicle's track ID)
    int vehicle_track_id = -1;
    if (vehicle_detection)
        vehicle_track_id = get_tracking_id(vehicle_detection);

    // Check if this vehicle track already has a plate
    if (vehicle_track_id >= 0)
    {
        std::string plate;
        if (track_has_lpr(vehicle_track_id, &plate))
            return crop_rois;
    }

    // Get LP detections (already in vehicle crop coordinates!)
    std::vector<HailoDetectionPtr> lp_detections = hailo_common::get_hailo_detections(roi);
    
    lpr_dbg("%s ENTER frame_id=%d track_id=%d crop_size=%dx%d lp_count=%zu",
            crop_name, frame_id, vehicle_track_id, crop_w, crop_h, lp_detections.size());

    HailoDetectionPtr best_lp;
    HailoBBox best_bbox(0.0f, 0.0f, 0.0f, 0.0f);
    float best_score = 0.0f;
    int best_w_px = 0;
    int best_h_px = 0;

    int lp_idx = 0;
    for (auto& lp : lp_detections)
    {
        if (!lp)
        {
            lp_idx++;
            continue;
        }

        std::string lp_label = lp->get_label();
        if (LICENSE_PLATE_LABEL != lp_label)
        {
            lp_idx++;
            continue;
        }

        // Use LP bbox directly - it's already relative to the vehicle crop
        // DO NOT flatten with scaling_bbox - that would incorrectly shrink the bbox
        HailoBBox lp_bbox = lp->get_bbox();

        // Clamp to [0,1] normalized coordinates
        float xmin = std::max(0.0f, std::min(1.0f, lp_bbox.xmin()));
        float ymin = std::max(0.0f, std::min(1.0f, lp_bbox.ymin()));
        float xmax = std::max(xmin, std::min(1.0f, lp_bbox.xmax()));
        float ymax = std::max(ymin, std::min(1.0f, lp_bbox.ymax()));
        HailoBBox clamped_bbox(xmin, ymin, xmax - xmin, ymax - ymin);

        // Convert to pixels
        int lp_w_px = static_cast<int>(clamped_bbox.width() * crop_w);
        int lp_h_px = static_cast<int>(clamped_bbox.height() * crop_h);

        // Validate size - basic checks
        if (lp_w_px < 20 || lp_h_px < 10)
        {
            lp_idx++;
            continue;
        }

        // Validate with lightweight checks
        int crop_w_check = 0;
        int crop_h_check = 0;
        if (!get_crop_dims(vehicle_crop, clamped_bbox, crop_w_check, crop_h_check))
        {
            lp_idx++;
            continue;
        }

        const char *reject_reason = nullptr;
        if (!validate_lp_crop_lightweight(vehicle_crop, clamped_bbox, crop_w_check, crop_h_check, &reject_reason))
        {
            int crop_id = g_lp_crop_counter.fetch_add(1);
            save_crop_image(vehicle_crop, clamped_bbox, reject_prefix, crop_id, vehicle_track_id);
            lp_idx++;
            continue;
        }

        // Validate aspect ratio
        float aspect = (lp_h_px > 0) ? (static_cast<float>(lp_w_px) / lp_h_px) : 0.0f;
        if (aspect < LP_SIMPLE_MIN_ASPECT || aspect > LP_SIMPLE_MAX_ASPECT)
        {
            lp_idx++;
            continue;
        }

        // Relative area: LP area / entire vehicle crop area
        float lp_area = clamped_bbox.width() * clamped_bbox.height();

        // Looser thresholds since vehicle is already isolated
        if (lp_area < 0.001f || lp_area > 0.5f)
        {
            lp_idx++;
            continue;
        }

        // Score based on area and confidence
        float score = lp_area;
        float conf = lp->get_confidence();
        if (conf > 0.0f)
            score *= conf;

        // Keep the best LP based on score
        if (score > best_score)
        {
            best_lp = lp;
            best_bbox = clamped_bbox;
            best_score = score;
            best_w_px = crop_w_check;
            best_h_px = crop_h_check;
        }

        lp_idx++;
    }

    // Send the best LP for OCR
    if (best_lp)
    {
        // Add padding: 10% to top, 15% to bottom
        float lp_height = best_bbox.height();
        float top_pad = lp_height * 0.05f;    // 10% padding at top
        float bottom_pad = lp_height * 0.1f; // 15% padding at bottom

        // Expand bbox with padding, clamped to [0,1]
        float padded_xmin = best_bbox.xmin();
        float padded_ymin = std::max(0.0f, best_bbox.ymin() - top_pad);
        float padded_xmax = best_bbox.xmax();
        float padded_ymax = std::min(1.0f, best_bbox.ymax() + bottom_pad);

        HailoBBox padded_bbox(padded_xmin, padded_ymin,
                              padded_xmax - padded_xmin,
                              padded_ymax - padded_ymin);

        best_lp->set_bbox(padded_bbox);
        best_lp->set_scaling_bbox(HailoBBox(0.0f, 0.0f, 1.0f, 1.0f));
        attach_tracking_id_if_missing(best_lp, vehicle_track_id);

        lpr_dbg("%s SEND track_id=%d score=%.4f bbox=[%.3f,%.3f,%.3f,%.3f] padded=[%.3f,%.3f,%.3f,%.3f] size_px=%dx%d crop=%dx%d",
                crop_name, vehicle_track_id, best_score,
                best_bbox.xmin(), best_bbox.ymin(), best_bbox.width(), best_bbox.height(),
                padded_bbox.xmin(), padded_bbox.ymin(), padded_bbox.width(), padded_bbox.height(),
                best_w_px, best_h_px, crop_w, crop_h);

        int crop_id = g_lp_crop_counter.fetch_add(1);
        save_crop_image(vehicle_crop, padded_bbox, sent_prefix, crop_id, vehicle_track_id);
        attach_crop_meta(best_lp, crop_id, frame_id);
        track_ocr_lp_to_ocr(vehicle_track_id);
        crop_rois.push_back(best_lp);
    }
    
    return crop_rois;
}

/**
 * @brief License plate cropper for vehicle crops with validation like license_plate_minimal.
 *        This function is designed for sequential pipelines where lp_cropper receives
 *        vehicle crops (not full frame) from the vehicle_cropper.
 *
 *        Validation checks (same as license_plate_minimal):
 *        - Minimum size: 20x10 pixels
 *        - Aspect ratio: 1.5 - 6.0
 *        - Relative area: 0.1% - 50% of vehicle crop
 *        - Lightweight quality checks (brightness, contrast)
 *        - Adds padding (5% top, 10% bottom) before OCR
 *
 * @param vehicle_crop  -  std::shared_ptr<HailoMat>
 *        The vehicle crop image (NOT full frame).
 *
 * @param roi  -  HailoROIPtr
 *        The ROI containing license plate detections (relative to vehicle crop).
 *
 * @return std::vector<HailoROIPtr>
 *         Vector of LP ROIs to send to OCR.
 */
std::vector<HailoROIPtr> license_plate_vehicle_crop(
    std::shared_ptr<HailoMat> vehicle_crop,
    HailoROIPtr roi)
{
    lpr_log_settings();
    std::vector<HailoROIPtr> crop_rois;
    const char *crop_name = "lp_vehicle_crop_ocr";
    const char *sent_prefix = "SENT_lp_vehicle_crop_ocr";
    const char *reject_prefix = "REJECT_lp_vehicle_crop_ocr";
    const int frame_id = g_lp_frame_counter.fetch_add(1);

    load_lpr_state_from_jsonl();
    refresh_lpr_state_from_jsonl();

    if (!vehicle_crop || !roi)
    {
        lpr_dbg("%s REJECT reason=null_input", crop_name);
        return crop_rois;
    }

    // Image dimensions are the VEHICLE CROP dimensions
    const int crop_w = vehicle_crop->width();
    const int crop_h = vehicle_crop->height();
    if (crop_w <= 0 || crop_h <= 0)
    {
        lpr_dbg("%s REJECT reason=invalid_crop_size size=%dx%d", crop_name, crop_w, crop_h);
        return crop_rois;
    }

    // Check if ROI is a HailoDetection (vehicle)
    auto vehicle_detection = std::dynamic_pointer_cast<HailoDetection>(roi);

    // Get track ID from the ROI (this is the vehicle's track ID)
    int vehicle_track_id = -1;
    if (vehicle_detection)
        vehicle_track_id = get_tracking_id(vehicle_detection);

    // Check if this vehicle track already has a plate
    if (vehicle_track_id >= 0)
    {
        std::string plate;
        if (track_has_lpr(vehicle_track_id, &plate))
        {
            lpr_dbg("%s SKIP track_id=%d already has LP '%s'",
                    crop_name, vehicle_track_id, plate.c_str());
            return crop_rois;
        }
    }

    // Check if vehicle has a classification - if so, skip
    if (vehicle_detection && detection_has_classification(vehicle_detection))
    {
        std::string cls_label;
        detection_has_classification(vehicle_detection, "", &cls_label);
        lpr_dbg("%s SKIP track_id=%d has classification '%s'",
                crop_name, vehicle_track_id, cls_label.c_str());
        return crop_rois;
    }

    // Get LP detections (already in vehicle crop coordinates!)
    std::vector<HailoDetectionPtr> lp_detections = hailo_common::get_hailo_detections(roi);

    lpr_dbg("%s ENTER frame_id=%d track_id=%d crop_size=%dx%d lp_count=%zu",
            crop_name, frame_id, vehicle_track_id, crop_w, crop_h, lp_detections.size());

    // Structure to hold LP candidates with their scores
    struct LPCandidate {
        HailoDetectionPtr lp;
        HailoBBox clamped_bbox;
        float score;
        int w_px;
        int h_px;
    };
    std::vector<LPCandidate> valid_candidates;

    // Maximum number of LPs to send to OCR per vehicle
    const size_t MAX_LPS_PER_VEHICLE = 4;

    int lp_idx = 0;
    for (auto& lp : lp_detections)
    {
        if (!lp)
        {
            lp_idx++;
            continue;
        }

        std::string lp_label = lp->get_label();
        if (LICENSE_PLATE_LABEL != lp_label)
        {
            lpr_dbg("%s REJECT reason=label lp=%d label='%s'", crop_name, lp_idx, lp_label.c_str());
            lp_idx++;
            continue;
        }

        // Use LP bbox directly - it's already relative to the vehicle crop
        // DO NOT flatten with scaling_bbox - that would incorrectly shrink the bbox
        HailoBBox lp_bbox = lp->get_bbox();

        // Clamp to [0,1] normalized coordinates
        float xmin = std::max(0.0f, std::min(1.0f, lp_bbox.xmin()));
        float ymin = std::max(0.0f, std::min(1.0f, lp_bbox.ymin()));
        float xmax = std::max(xmin, std::min(1.0f, lp_bbox.xmax()));
        float ymax = std::max(ymin, std::min(1.0f, lp_bbox.ymax()));
        HailoBBox clamped_bbox(xmin, ymin, xmax - xmin, ymax - ymin);

        // Convert to pixels
        int lp_w_px = static_cast<int>(clamped_bbox.width() * crop_w);
        int lp_h_px = static_cast<int>(clamped_bbox.height() * crop_h);

        // Validate size - minimum 20x10 pixels (same as license_plate_minimal)
        if (lp_w_px < 20 || lp_h_px < 10)
        {
            lpr_dbg("%s REJECT reason=too_small_px lp=%d size=%dx%d", crop_name, lp_idx, lp_w_px, lp_h_px);
            lp_idx++;
            continue;
        }

        // Validate with lightweight checks (brightness, contrast)
        int crop_w_check = 0;
        int crop_h_check = 0;
        if (!get_crop_dims(vehicle_crop, clamped_bbox, crop_w_check, crop_h_check))
        {
            lpr_dbg("%s REJECT reason=empty_crop lp=%d", crop_name, lp_idx);
            lp_idx++;
            continue;
        }

        const char *reject_reason = nullptr;
        if (!validate_lp_crop_lightweight(vehicle_crop, clamped_bbox, crop_w_check, crop_h_check, &reject_reason))
        {
            lpr_dbg("%s REJECT reason=%s lp=%d size_px=%dx%d", crop_name, reject_reason, lp_idx, crop_w_check, crop_h_check);
            int crop_id = g_lp_crop_counter.fetch_add(1);
            save_crop_image(vehicle_crop, clamped_bbox, reject_prefix, crop_id, vehicle_track_id);
            lp_idx++;
            continue;
        }

        // Validate aspect ratio (same as license_plate_minimal: 1.5 - 6.0)
        float aspect = (lp_h_px > 0) ? (static_cast<float>(lp_w_px) / lp_h_px) : 0.0f;
        if (aspect < LP_SIMPLE_MIN_ASPECT || aspect > LP_SIMPLE_MAX_ASPECT)
        {
            lpr_dbg("%s REJECT reason=bad_aspect lp=%d aspect=%.2f", crop_name, lp_idx, aspect);
            lp_idx++;
            continue;
        }

        // Relative area: LP area / entire vehicle crop area (0.1% - 50%)
        float lp_area = clamped_bbox.width() * clamped_bbox.height();
        if (lp_area < 0.001f || lp_area > 0.5f)
        {
            lpr_dbg("%s REJECT reason=bad_rel_area lp=%d area=%.4f", crop_name, lp_idx, lp_area);
            lp_idx++;
            continue;
        }

        // Score based on area and confidence
        float score = lp_area;
        float conf = lp->get_confidence();
        if (conf > 0.0f)
            score *= conf;

        // Add to candidates list
        valid_candidates.push_back({lp, clamped_bbox, score, crop_w_check, crop_h_check});
        lpr_dbg("%s CANDIDATE lp=%d score=%.4f size_px=%dx%d", crop_name, lp_idx, score, crop_w_check, crop_h_check);

        lp_idx++;
    }

    // Sort candidates by score (descending) and keep top MAX_LPS_PER_VEHICLE
    std::sort(valid_candidates.begin(), valid_candidates.end(),
              [](const LPCandidate& a, const LPCandidate& b) { return a.score > b.score; });
    
    if (valid_candidates.size() > MAX_LPS_PER_VEHICLE)
    {
        lpr_dbg("%s FILTER keeping top %zu of %zu candidates", crop_name, MAX_LPS_PER_VEHICLE, valid_candidates.size());
        valid_candidates.erase(valid_candidates.begin() + MAX_LPS_PER_VEHICLE, valid_candidates.end());
    }

    // Send the best LPs (up to 4) for OCR
    const char *top_lp_prefix = "TOP_LP_to_ocr";  // Separate debug folder for chosen LPs
    int rank = 0;
    for (auto& candidate : valid_candidates)
    {
        // Add padding: 5% to top, 10% to bottom (same as license_plate_minimal)
        float lp_height = candidate.clamped_bbox.height();
        float top_pad = lp_height * 0.05f;
        float bottom_pad = lp_height * 0.1f;

        // Expand bbox with padding, clamped to [0,1]
        float padded_xmin = candidate.clamped_bbox.xmin();
        float padded_ymin = std::max(0.0f, candidate.clamped_bbox.ymin() - top_pad);
        float padded_xmax = candidate.clamped_bbox.xmax();
        float padded_ymax = std::min(1.0f, candidate.clamped_bbox.ymax() + bottom_pad);

        HailoBBox padded_bbox(padded_xmin, padded_ymin,
                              padded_xmax - padded_xmin,
                              padded_ymax - padded_ymin);

        candidate.lp->set_bbox(padded_bbox);
        candidate.lp->set_scaling_bbox(HailoBBox(0.0f, 0.0f, 1.0f, 1.0f));
        attach_tracking_id_if_missing(candidate.lp, vehicle_track_id);

        lpr_dbg("%s SEND rank=%d track_id=%d score=%.4f bbox=[%.3f,%.3f,%.3f,%.3f] padded=[%.3f,%.3f,%.3f,%.3f] size_px=%dx%d crop=%dx%d",
                crop_name, rank, vehicle_track_id, candidate.score,
                candidate.clamped_bbox.xmin(), candidate.clamped_bbox.ymin(), candidate.clamped_bbox.width(), candidate.clamped_bbox.height(),
                padded_bbox.xmin(), padded_bbox.ymin(), padded_bbox.width(), padded_bbox.height(),
                candidate.w_px, candidate.h_px, crop_w, crop_h);

        int crop_id = g_lp_crop_counter.fetch_add(1);
        // Save to regular sent folder
        save_crop_image(vehicle_crop, padded_bbox, sent_prefix, crop_id, vehicle_track_id);
        // Also save to separate debug folder for chosen top LPs
        save_crop_image(vehicle_crop, padded_bbox, top_lp_prefix, crop_id, vehicle_track_id);
        attach_crop_meta(candidate.lp, crop_id, frame_id);
        track_ocr_lp_to_ocr(vehicle_track_id);
        crop_rois.push_back(candidate.lp);
        rank++;
    }

    lpr_dbg("%s RESULT: %zu LP(s) sent to OCR for track_id=%d", crop_name, crop_rois.size(), vehicle_track_id);

    return crop_rois;
}
