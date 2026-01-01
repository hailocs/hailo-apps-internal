/**
 * Shared ROI configuration for LPR postprocess components.
 */
#pragma once

#include <array>
#include <string>
#include <vector>
#include <sstream>
#include <fstream>
#include <cstdlib>
#include <cctype>
#include <algorithm>

struct LprRoiPoint
{
    float x;
    float y;
};

struct LprRoiRect
{
    float xmin;
    float ymin;
    float xmax;
    float ymax;
};

static constexpr float LPR_ROI_DEFAULT_MIN_INTERSECTION = 1.0f;

inline float lpr_clamp01(float value)
{
    return std::max(0.0f, std::min(1.0f, value));
}

inline std::array<LprRoiPoint, 4> lpr_default_vehicle_roi_polygon()
{
    return {
        LprRoiPoint{0.05f, 0.25f},
        LprRoiPoint{0.75f, 0.1f},
        LprRoiPoint{0.75f, 0.9f},
        LprRoiPoint{0.0f, 0.9f},
    };
}

inline LprRoiRect lpr_polygon_bounds(const std::array<LprRoiPoint, 4> &polygon)
{
    float xmin = 1.0f;
    float ymin = 1.0f;
    float xmax = 0.0f;
    float ymax = 0.0f;
    for (const auto &pt : polygon)
    {
        xmin = std::min(xmin, pt.x);
        ymin = std::min(ymin, pt.y);
        xmax = std::max(xmax, pt.x);
        ymax = std::max(ymax, pt.y);
    }
    xmin = lpr_clamp01(xmin);
    ymin = lpr_clamp01(ymin);
    xmax = lpr_clamp01(xmax);
    ymax = lpr_clamp01(ymax);
    if (xmax <= xmin || ymax <= ymin)
        return LprRoiRect{0.0f, 0.0f, 1.0f, 1.0f};
    return LprRoiRect{xmin, ymin, xmax, ymax};
}

inline std::array<LprRoiPoint, 4> lpr_rect_to_polygon(const LprRoiRect &rect)
{
    return {
        LprRoiPoint{rect.xmin, rect.ymin},
        LprRoiPoint{rect.xmax, rect.ymin},
        LprRoiPoint{rect.xmax, rect.ymax},
        LprRoiPoint{rect.xmin, rect.ymax},
    };
}

inline bool lpr_parse_roi_list(const std::string &value, float &xmin, float &ymin, float &xmax, float &ymax, float &min_intersection)
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

inline bool lpr_extract_key_float(const std::string &text, const std::string &key, float &out)
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

inline bool lpr_parse_roi_from_text(const std::string &text, float &xmin, float &ymin, float &xmax, float &ymax, float &min_intersection)
{
    bool has_key = false;

    has_key |= lpr_extract_key_float(text, "xmin", xmin);
    has_key |= lpr_extract_key_float(text, "ymin", ymin);
    has_key |= lpr_extract_key_float(text, "xmax", xmax);
    has_key |= lpr_extract_key_float(text, "ymax", ymax);
    lpr_extract_key_float(text, "min_intersection", min_intersection);
    lpr_extract_key_float(text, "min_intersection_ratio", min_intersection);

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

    xmin = lpr_clamp01(xmin);
    ymin = lpr_clamp01(ymin);
    xmax = lpr_clamp01(xmax);
    ymax = lpr_clamp01(ymax);
    if (xmax <= xmin || ymax <= ymin)
        return false;
    min_intersection = lpr_clamp01(min_intersection);
    return true;
}

struct LprRoiConfig
{
    bool enabled = true;
    bool polygon_enabled = true;
    float min_intersection_ratio = LPR_ROI_DEFAULT_MIN_INTERSECTION;
    std::array<LprRoiPoint, 4> polygon = lpr_default_vehicle_roi_polygon();
    LprRoiRect rect = lpr_polygon_bounds(polygon);
    std::string source = "default";
};

inline LprRoiConfig get_lpr_vehicle_roi_config()
{
    static int initialized = 0;
    static LprRoiConfig config;
    if (initialized == 1)
        return config;

    LprRoiConfig local;
    local.polygon = lpr_default_vehicle_roi_polygon();
    local.rect = lpr_polygon_bounds(local.polygon);
    local.min_intersection_ratio = LPR_ROI_DEFAULT_MIN_INTERSECTION;
    local.polygon_enabled = true;
    local.enabled = true;
    local.source = "default";

    const char *env_roi = std::getenv("HAILO_LPR_VEHICLE_ROI");
    if (env_roi && env_roi[0] != '\0')
    {
        float xmin = 0.0f, ymin = 0.0f, xmax = 1.0f, ymax = 1.0f;
        float min_intersection = LPR_ROI_DEFAULT_MIN_INTERSECTION;
        if (lpr_parse_roi_list(env_roi, xmin, ymin, xmax, ymax, min_intersection))
        {
            float cxmin = lpr_clamp01(xmin);
            float cymin = lpr_clamp01(ymin);
            float cxmax = lpr_clamp01(xmax);
            float cymax = lpr_clamp01(ymax);
            if (cxmax > cxmin && cymax > cymin)
            {
                local.enabled = true;
                local.polygon_enabled = false;
                local.rect = LprRoiRect{cxmin, cymin, cxmax, cymax};
                local.polygon = lpr_rect_to_polygon(local.rect);
                local.min_intersection_ratio = lpr_clamp01(min_intersection);
                local.source = "HAILO_LPR_VEHICLE_ROI";
            }
        }
    }

    const char *env_path = std::getenv("HAILO_LPR_VEHICLE_ROI_CONFIG");
    if (local.source == "default" && env_path && env_path[0] != '\0')
    {
        std::ifstream file(env_path);
        if (file)
        {
            std::stringstream buffer;
            buffer << file.rdbuf();
            float xmin = 0.0f, ymin = 0.0f, xmax = 1.0f, ymax = 1.0f;
            float min_intersection = LPR_ROI_DEFAULT_MIN_INTERSECTION;
            if (lpr_parse_roi_from_text(buffer.str(), xmin, ymin, xmax, ymax, min_intersection))
            {
                local.enabled = true;
                local.polygon_enabled = false;
                local.rect = LprRoiRect{xmin, ymin, xmax, ymax};
                local.polygon = lpr_rect_to_polygon(local.rect);
                local.min_intersection_ratio = lpr_clamp01(min_intersection);
                local.source = env_path;
            }
        }
    }

    config = local;
    initialized = 1;
    return config;
}
