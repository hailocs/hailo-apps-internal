/**
 * Copyright (c) 2021-2022 Hailo Technologies Ltd. All rights reserved.
 * Distributed under the LGPL license (https://www.gnu.org/licenses/old-licenses/lgpl-2.1.txt)
 **/

#include <gst/gst.h>
#include <gst/video/video-format.h>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <iomanip>
#include <map>
#include <algorithm>
#include <cctype>
#include <typeinfo>
#include <math.h>
#include <atomic>
#include <mutex>
#include <vector>
#include <string>

// Open source includes
#include <opencv2/opencv.hpp>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>
#include <opencv2/core.hpp>

// Hailo includes
#include "hailo_objects.hpp"
#include "hailo_common.hpp"
#include "hailomat.hpp"
#include "lpr_ocrsink.hpp"
#include "hailo_cv_singleton.hpp"
#include "hailo_tracker.hpp"
#include "image.hpp"

// General
#define MAP_LIMIT (5)              // Number of license plates to store at any time
#define OCR_SCORE_THRESHOLD (0.90) // OCR score threshold
int singleton_map_key = 0;
std::vector<int> seen_ocr_track_ids;
const gchar *OCR_LABEL_TYPE = "text_region";
const gchar *LPR_RESULT_LABEL_TYPE = "lpr_result";
std::string tracker_name = "hailo_tracker";
static std::atomic<unsigned long long> g_lpr_frame_counter{0};

static bool lpr_debug_enabled()
{
    static bool initialized = false;
    static bool enabled = false;
    if (!initialized)
    {
        const char *val = std::getenv("HAILO_LPR_OCRSINK_LOG");
        enabled = (val != nullptr && val[0] != '\0');
        initialized = true;
    }
    return enabled;
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

static void lpr_dbg_impl(const char *fmt, ...)
{
    static std::atomic<int> debug_counter{0};
    int every_n = lpr_debug_every_n();
    int count = debug_counter.fetch_add(1);
    if (every_n > 1 && (count % every_n) != 0)
        return;
    std::fprintf(stderr, "[lpr_ocrsink] ");
    va_list args;
    va_start(args, fmt);
    std::vfprintf(stderr, fmt, args);
    va_end(args);
    std::fprintf(stderr, "\n");
    std::fflush(stderr);
}

#define lpr_dbg(...)                   \
    do                                 \
    {                                  \
        if (lpr_debug_enabled())       \
        {                              \
            lpr_dbg_impl(__VA_ARGS__); \
        }                              \
    } while (0)

static const std::string &get_lpr_country()
{
    static const std::string country = []() -> std::string
    {
        const char *env = std::getenv("HAILO_LPR_COUNTRY");
        if (env && env[0] != '\0')
            return std::string(env);
        return std::string("default");
    }();
    return country;
}

static void lpr_log_settings()
{
    static int logged = 0;
    if (logged || !lpr_debug_enabled())
        return;
    logged = 1;
    lpr_dbg("settings: OCR_SCORE_THRESHOLD=%.2f OCR_LABEL_TYPE='%s' LPR_RESULT_LABEL_TYPE='%s' tracker_name='%s' country='%s'",
            OCR_SCORE_THRESHOLD, OCR_LABEL_TYPE, LPR_RESULT_LABEL_TYPE, tracker_name.c_str(), get_lpr_country().c_str());
}

static std::string extract_digits_only(const std::string &input)
{
    std::string digits;
    digits.reserve(input.size());
    for (unsigned char ch : input)
    {
        if (std::isdigit(ch))
            digits.push_back(static_cast<char>(ch));
    }
    return digits;
}

static bool normalize_ocr_label_default(const std::string &raw_label, std::string &normalized)
{
    normalized = extract_digits_only(raw_label);
    return (normalized.size() == 7 || normalized.size() == 8);
}

static bool normalize_ocr_label_for_country(const std::string &country, const std::string &raw_label, std::string &normalized)
{
    if (country == "default" || country.empty())
        return normalize_ocr_label_default(raw_label, normalized);

    bool ok = normalize_ocr_label_default(raw_label, normalized);
    lpr_dbg("ocr_normalize: country='%s' not implemented, using default rule (ok=%d)", country.c_str(), ok ? 1 : 0);
    return ok;
}

void catalog_nv12_mat(std::string text, std::vector<cv::Mat> &mat)
{
    if (mat.size() < 2 || mat[0].empty() || mat[1].empty() ||
        mat[0].cols <= 0 || mat[0].rows <= 0 || mat[1].cols <= 0 || mat[1].rows <= 0)
    {
        if (lpr_debug_enabled())
        {
            std::fprintf(stderr, "[lpr_ocrsink] catalog_nv12_mat: empty or invalid input (size=%zu y_empty=%d uv_empty=%d y=%dx%d uv=%dx%d)\n",
                         mat.size(),
                         mat.size() > 0 ? mat[0].empty() : 1,
                         mat.size() > 1 ? mat[1].empty() : 1,
                         mat.size() > 0 ? mat[0].cols : 0,
                         mat.size() > 0 ? mat[0].rows : 0,
                         mat.size() > 1 ? mat[1].cols : 0,
                         mat.size() > 1 ? mat[1].rows : 0);
            std::fflush(stderr);
        }
        return;
    }
    if (lpr_debug_enabled())
    {
        std::fprintf(stderr,
                     "[lpr_ocrsink] catalog_nv12_mat: pre-resize y=%dx%d uv=%dx%d y_type=%d uv_type=%d\n",
                     mat[0].cols, mat[0].rows, mat[1].cols, mat[1].rows,
                     mat[0].type(), mat[1].type());
        std::fflush(stderr);
    }
    // Resize the mat to a presentable size, add padding
    int target_h = 114;
    int target_w = 300;
    std::vector<cv::Mat> resized_nv12_vec;
    cv::Mat resized_nv12_y_mat = cv::Mat(target_h * 2 / 3, target_w, CV_8UC1);
    cv::Mat resized_nv12_uv_mat = cv::Mat(target_h / 3, target_w / 2, CV_8UC2);
    resized_nv12_vec.emplace_back(std::move(resized_nv12_y_mat));
    resized_nv12_vec.emplace_back(std::move(resized_nv12_uv_mat));

    resize_nv12(mat, resized_nv12_vec);

    // To make padding, prepare a padded mat and split channels from that mat
    int padded_h = target_h + 45;
    cv::Mat padded_nv12 = cv::Mat(padded_h, target_w, CV_8UC1, cv::Scalar(0));
    int padded_y_h = padded_h * 2 / 3;
    int padded_y_w = target_w;
    int padded_uv_h = padded_h / 3;
    int padded_uv_w = target_w / 2;
    cv::Mat padded_y_mat = cv::Mat(padded_y_h, padded_y_w, CV_8UC1, (char *)padded_nv12.data, padded_nv12.step);
    cv::Mat padded_uv_mat = cv::Mat(padded_uv_h, padded_uv_w, CV_8UC2, (char *)padded_nv12.data + (padded_y_h * padded_y_w), padded_nv12.step);

    // Fill the padded image with white padding
    cv::copyMakeBorder(resized_nv12_vec[0], padded_y_mat, 30, 0, 0, 0, cv::BORDER_CONSTANT, cv::Scalar(235));
    cv::copyMakeBorder(resized_nv12_vec[1], padded_uv_mat, 15, 0, 0, 0, cv::BORDER_CONSTANT, cv::Scalar(128, 128));

    // Draw text on the two channels
    cv::Point y_position = cv::Point(4, 24);
    cv::Point uv_position = cv::Point(2, 12);
    cv::putText(padded_y_mat, text, y_position, cv::FONT_HERSHEY_SIMPLEX, 1, cv::Scalar(65), 2);
    cv::putText(padded_uv_mat, text, uv_position, cv::FONT_HERSHEY_SIMPLEX, 0.5, cv::Scalar(110, 255), 1);

    CVMatSingleton::GetInstance().set_mat_at_key(singleton_map_key % MAP_LIMIT, padded_nv12);
    CVMatSingleton::GetInstance().set_mat_type(HAILO_MAT_NV12);
}

void catalog_yuy2_mat(std::string text, cv::Mat &mat)
{
    if (mat.empty() || mat.cols <= 0 || mat.rows <= 0)
    {
        if (lpr_debug_enabled())
        {
            std::fprintf(stderr, "[lpr_ocrsink] catalog_yuy2_mat: empty or invalid input (empty=%d cols=%d rows=%d)\n",
                         mat.empty(), mat.cols, mat.rows);
            std::fflush(stderr);
        }
        return;
    }
    if (lpr_debug_enabled())
    {
        std::fprintf(stderr, "[lpr_ocrsink] catalog_yuy2_mat: pre-resize %dx%d type=%d\n",
                     mat.cols, mat.rows, mat.type());
        std::fflush(stderr);
    }
    // Resize the mat to a presentable size, add padding
    cv::Mat padded_yuy2;
    cv::Mat resized_yuy2 = cv::Mat(75, 150, CV_8UC4);
    resize_yuy2(mat, resized_yuy2);

    // Add padding top, bottom, left, right, borderType
    cv::copyMakeBorder(resized_yuy2, padded_yuy2, 30, 0, 0, 0, cv::BORDER_CONSTANT, cv::Scalar(235, 128, 235, 128));

    // write the OCR text on that padding (view as 2 channel su the yuy2 draws correctly)
    cv::Mat image_2_channel = cv::Mat(padded_yuy2.rows, padded_yuy2.cols * 2, CV_8UC2, (char *)padded_yuy2.data, padded_yuy2.step);
    auto text_position = cv::Point(5, 25);
    cv::putText(image_2_channel, text, text_position, cv::FONT_HERSHEY_SIMPLEX, 1, cv::Scalar(81, 90, 81, 239), 2);

    // Set the new license plate in our CV Map singleton
    CVMatSingleton::GetInstance().set_mat_at_key(singleton_map_key % MAP_LIMIT, padded_yuy2);
    CVMatSingleton::GetInstance().set_mat_type(HAILO_MAT_YUY2);
}

void catalog_rgb_mat(std::string text, cv::Mat &mat)
{
    if (mat.empty() || mat.cols <= 0 || mat.rows <= 0)
    {
        if (lpr_debug_enabled())
        {
            std::fprintf(stderr, "[lpr_ocrsink] catalog_rgb_mat: empty or invalid input (empty=%d cols=%d rows=%d)\n",
                         mat.empty(), mat.cols, mat.rows);
            std::fflush(stderr);
        }
        return;
    }
    if (lpr_debug_enabled())
    {
        std::fprintf(stderr, "[lpr_ocrsink] catalog_rgb_mat: pre-resize %dx%d type=%d\n",
                     mat.cols, mat.rows, mat.type());
        std::fflush(stderr);
    }
    // Resize the mat to a presentable size, add padding
    cv::Mat resized_image;
    cv::Mat padded_image;
    cv::resize(mat, resized_image, cv::Size(300, 75), 0, 0, cv::INTER_AREA);

    // Add padding top, bottom, left, right, borderType
    cv::copyMakeBorder(resized_image, padded_image, 30, 0, 0, 0, cv::BORDER_CONSTANT, cv::Scalar(255, 255, 255));

    // write the OCR text on that padding
    auto text_position = cv::Point(10, 25);
    cv::putText(padded_image, text, text_position, cv::FONT_HERSHEY_SIMPLEX, 1, cv::Scalar(255, 0, 0), 2);

    // Set the new license plate in our CV Map singleton
    CVMatSingleton::GetInstance().set_mat_at_key(singleton_map_key % MAP_LIMIT, padded_image);
    CVMatSingleton::GetInstance().set_mat_type(HAILO_MAT_RGB);
}

void catalog_license_plate(std::string label, float confidence, HailoBBox license_plate_box, std::shared_ptr<HailoMat> hmat, HailoROIPtr crop_roi)
{
    if (!hmat)
    {
        lpr_dbg("catalog_license_plate: null HailoMat (label='%s')", label.c_str());
        return;
    }
    cv::Mat &mat = hmat->get_matrices()[0];
    // Prepare the cropped license plate and text
    std::string text = label + " " + std::to_string((int)(confidence * 100)) + "%";
    cv::Rect rect;
    rect.x = CLAMP(license_plate_box.xmin() * mat.cols, 0, mat.cols);
    rect.y = CLAMP(license_plate_box.ymin() * mat.rows, 0, mat.rows);
    rect.width = CLAMP(license_plate_box.width() * mat.cols, 0, mat.cols - rect.x);
    rect.height = CLAMP(license_plate_box.height() * mat.rows, 0, mat.rows - rect.y);
    if (rect.width == 0 || rect.height == 0)
    {
        lpr_dbg("catalog_license_plate: zero rect (label='%s' conf=%.3f)", label.c_str(), confidence);
        return;
    }

    const float xmin = CLAMP(license_plate_box.xmin(), 0.0f, 1.0f);
    const float ymin = CLAMP(license_plate_box.ymin(), 0.0f, 1.0f);
    const float xmax = CLAMP(license_plate_box.xmax(), xmin, 1.0f);
    const float ymax = CLAMP(license_plate_box.ymax(), ymin, 1.0f);
    auto safe_crop_roi = std::make_shared<HailoROI>(HailoBBox(xmin, ymin, (xmax - xmin), (ymax - ymin)));

    lpr_dbg(
        "catalog_license_plate: label='%s' conf=%.3f mat_type=%d bbox=[%.3f,%.3f,%.3f,%.3f] safe=[%.3f,%.3f,%.3f,%.3f] rect=[%d,%d,%d,%d]",
        label.c_str(),
        confidence,
        static_cast<int>(hmat->get_type()),
        license_plate_box.xmin(),
        license_plate_box.ymin(),
        license_plate_box.xmax(),
        license_plate_box.ymax(),
        xmin,
        ymin,
        xmax,
        ymax,
        rect.x,
        rect.y,
        rect.width,
        rect.height);

    std::vector<cv::Mat> cropped_image_vec;
    try
    {
        cropped_image_vec = hmat->crop(safe_crop_roi);
    }
    catch (const cv::Exception &e)
    {
        lpr_dbg("catalog_license_plate: cv::Exception during crop: %s", e.what());
        return;
    }
    catch (const std::exception &e)
    {
        lpr_dbg("catalog_license_plate: std::exception during crop: %s", e.what());
        return;
    }
    catch (...)
    {
        lpr_dbg("catalog_license_plate: unknown exception during crop");
        return;
    }

    if (cropped_image_vec.empty() || cropped_image_vec[0].empty() ||
        cropped_image_vec[0].cols <= 0 || cropped_image_vec[0].rows <= 0)
    {
        lpr_dbg("catalog_license_plate: crop returned empty/invalid mats (vec=%zu cols=%d rows=%d)",
                cropped_image_vec.size(),
                cropped_image_vec.empty() ? 0 : cropped_image_vec[0].cols,
                cropped_image_vec.empty() ? 0 : cropped_image_vec[0].rows);
        return;
    }

    switch (hmat->get_type())
    {
    case HAILO_MAT_YUY2:
    {
        catalog_yuy2_mat(text, cropped_image_vec[0]);
        break;
    }
    case HAILO_MAT_RGB:
    {
        catalog_rgb_mat(text, cropped_image_vec[0]);
        break;
    }
    case HAILO_MAT_NV12:
    {
        catalog_nv12_mat(text, cropped_image_vec);
        break;
    }
    default:
        break;
    }

    singleton_map_key++;
}

static bool parse_lp_crop_meta(const std::string &label, int &crop_id, int &frame_id)
{
    crop_id = -1;
    frame_id = -1;
    const std::string crop_key = "crop_id=";
    const std::string frame_key = "frame=";
    auto crop_pos = label.find(crop_key);
    auto frame_pos = label.find(frame_key);
    if (crop_pos == std::string::npos || frame_pos == std::string::npos)
        return false;
    crop_pos += crop_key.size();
    frame_pos += frame_key.size();
    char *end = nullptr;
    long crop_val = std::strtol(label.c_str() + crop_pos, &end, 10);
    if (end == label.c_str() + crop_pos)
        return false;
    long frame_val = std::strtol(label.c_str() + frame_pos, &end, 10);
    if (end == label.c_str() + frame_pos)
        return false;
    crop_id = static_cast<int>(crop_val);
    frame_id = static_cast<int>(frame_val);
    return true;
}

static bool get_lp_crop_meta(const HailoDetectionPtr &detection, int &crop_id, int &frame_id)
{
    if (!detection)
        return false;
    auto classifications = detection->get_objects_typed(HAILO_CLASSIFICATION);
    for (auto &obj : classifications)
    {
        auto cls = std::dynamic_pointer_cast<HailoClassification>(obj);
        if (!cls)
            continue;
        if (cls->get_classification_type() != "lp_crop_meta")
            continue;
        return parse_lp_crop_meta(cls->get_label(), crop_id, frame_id);
    }
    return false;
}

void ocr_sink(HailoROIPtr roi, std::shared_ptr<HailoMat> hmat, unsigned long long frame_id)
{
    lpr_dbg("========== ocr_sink: ENTER ==========");
    if (nullptr == roi)
    {
        lpr_dbg("ocr_sink: null ROI => EXIT");
        return;
    }
    if (!hmat)
    {
        lpr_dbg("ocr_sink: null HailoMat => EXIT");
        return;
    }

    std::vector<HailoDetectionPtr> vehicle_detections;   // The vehicle detections in the ROI
    std::vector<HailoUniqueIDPtr> unique_ids;            // The unique ids of those vehicle detections
    std::vector<HailoDetectionPtr> lp_detections;        // The license plate detections in those vehicle detections
    std::vector<HailoClassificationPtr> classifications; // The classifications of those license plate detections
    float confidence;                                    // The confidence of those classifications
    std::string license_plate_ocr_label;                 // The labels of those classifications
    std::string jde_tracker_name = tracker_name + "_" + roi->get_stream_id();
    const bool log_enabled = lpr_debug_enabled();
    const bool skip_tracks = !lpr_no_skip_enabled();

    // For each roi, check the detections
    vehicle_detections = hailo_common::get_hailo_detections(roi);
    bool plates_only_mode = false;
    if (vehicle_detections.empty())
    {
        plates_only_mode = true;
        vehicle_detections = hailo_common::get_hailo_detections(roi);
        if (log_enabled)
        {
            std::cout << "[LPR_OCSINK] frame=" << frame_id
                      << " plates_only_mode=true top_level_dets=" << vehicle_detections.size() << std::endl;
        }
    }
    else
    {
        if (log_enabled)
        {
            std::cout << "[LPR_OCSINK] frame=" << frame_id
                      << " vehicles=" << vehicle_detections.size() << std::endl;
        }
    }
    lpr_dbg("ocr_sink: frame_id=%llu stream_id='%s' total_vehicles=%zu OCR_LABEL_TYPE='%s'",
            frame_id, roi->get_stream_id().c_str(), vehicle_detections.size(), OCR_LABEL_TYPE);
    lpr_dbg("ocr_sink: seen_ocr_track_ids count=%zu", seen_ocr_track_ids.size());

    int veh_idx = 0;
    for (HailoDetectionPtr &vehicle_detection : vehicle_detections)
    {
        std::string veh_label = vehicle_detection->get_label();
        float veh_conf = vehicle_detection->get_confidence();
        lpr_dbg("ocr_sink: [veh %d] label='%s' conf=%.3f", veh_idx, veh_label.c_str(), veh_conf);

        // Get the unique id of the detection
        unique_ids = hailo_common::get_hailo_unique_id(vehicle_detection);
        int track_id = -1;
        if (!unique_ids.empty())
        {
            track_id = unique_ids[0]->get_id();
        }
        if (!plates_only_mode && unique_ids.empty())
        {
            lpr_dbg("ocr_sink: [veh %d] SKIP - no unique ID", veh_idx);
            veh_idx++;
            continue;
        }
        lpr_dbg("ocr_sink: [veh %d] track_id=%d", veh_idx, track_id);
        bool already_seen = std::find(seen_ocr_track_ids.begin(), seen_ocr_track_ids.end(), track_id) != seen_ocr_track_ids.end();
        if (already_seen && skip_tracks)
        {
            lpr_dbg("ocr_sink: [veh %d] SKIP - track_id=%d already has final OCR result", veh_idx, track_id);
            veh_idx++;
            continue;
        }

        // For each vehicle, get the license plate detection
        if (plates_only_mode)
        {
            lp_detections.clear();
            lp_detections.push_back(vehicle_detection);
        }
        else
        {
            lp_detections = hailo_common::get_hailo_detections(vehicle_detection);
        }
        lpr_dbg("ocr_sink: [veh %d] nested LP detections=%zu", veh_idx, lp_detections.size());
        if (lp_detections.empty())
        {
            veh_idx++;
            continue;
        }

        int lp_idx = 0;
        for (HailoDetectionPtr &lp_detection : lp_detections)
        {
            std::string lp_label = lp_detection->get_label();
            float lp_conf = lp_detection->get_confidence();
            HailoBBox lp_bbox = lp_detection->get_bbox();
            lpr_dbg("ocr_sink: [veh %d][lp %d] label='%s' conf=%.3f bbox=[%.3f,%.3f,%.3f,%.3f]",
                    veh_idx, lp_idx, lp_label.c_str(), lp_conf,
                    lp_bbox.xmin(), lp_bbox.ymin(), lp_bbox.width(), lp_bbox.height());
            int crop_id = -1;
            int crop_frame = -1;
            if (get_lp_crop_meta(lp_detection, crop_id, crop_frame))
            {
                lpr_dbg("ocr_sink: [veh %d][lp %d] crop_meta crop_id=%d frame=%d",
                        veh_idx, lp_idx, crop_id, crop_frame);
            }

            HailoBBox license_plate_box = hailo_common::create_flattened_bbox(lp_detection->get_bbox(), lp_detection->get_scaling_bbox());

            // For each license plate detection, check the classifications
            classifications = hailo_common::get_hailo_classifications(lp_detection);
            lpr_dbg("ocr_sink: [veh %d][lp %d] classifications count=%zu (expected exactly 1)",
                    veh_idx, lp_idx, classifications.size());

            // List all classifications for debugging
            for (size_t cls_i = 0; cls_i < classifications.size(); cls_i++)
            {
                lpr_dbg("ocr_sink: [veh %d][lp %d]   cls[%zu] type='%s' label='%s' conf=%.3f",
                        veh_idx, lp_idx, cls_i,
                        classifications[cls_i]->get_classification_type().c_str(),
                        classifications[cls_i]->get_label().c_str(),
                        classifications[cls_i]->get_confidence());
            }

            if (classifications.size() != 1)
            {
                lpr_dbg("ocr_sink: [veh %d][lp %d] REMOVE LP - wrong classification count (%zu != 1)",
                        veh_idx, lp_idx, classifications.size());
                vehicle_detection->remove_object(lp_detection); // If no ocr was found then remove this license plate
                lp_idx++;
                continue;
            }

            HailoClassificationPtr classification = classifications[0];
            std::string cls_type = classification->get_classification_type();
            std::string cls_label = classification->get_label();
            float cls_conf = classification->get_confidence();

            lpr_dbg("ocr_sink: [veh %d][lp %d] checking classification type='%s' vs expected='%s'",
                    veh_idx, lp_idx, cls_type.c_str(), OCR_LABEL_TYPE);

            if (cls_type == OCR_LABEL_TYPE)
            {
                confidence = cls_conf;
                license_plate_ocr_label = cls_label;
                if (log_enabled)
                {
                    std::cout << "[LPR_OCSINK] frame=" << frame_id << " OCR Raw: '" << license_plate_ocr_label
                              << "' (Confidence: " << std::fixed << std::setprecision(2) << confidence
                              << ", Track " << track_id << ")" << std::endl;
                }
                lpr_dbg("ocr_sink: [veh %d][lp %d] OCR raw text='%s' conf=%.3f",
                        veh_idx, lp_idx, license_plate_ocr_label.c_str(), confidence);

                std::string normalized_label;
                bool normalized_ok = normalize_ocr_label_for_country(get_lpr_country(), license_plate_ocr_label, normalized_label);
                lpr_dbg("ocr_sink: [veh %d][lp %d] OCR normalized text='%s' (digits=%zu)",
                        veh_idx, lp_idx, normalized_label.c_str(), normalized_label.size());
                if (!normalized_ok)
                {
                    if (log_enabled)
                    {
                        std::cout << "[LPR_OCSINK] frame=" << frame_id
                                  << " OCR rejected (normalize failed) for track " << track_id << std::endl;
                    }
                    lpr_dbg("ocr_sink: [veh %d][lp %d] REJECT OCR - expected 7 or 8 digits", veh_idx, lp_idx);
                    lp_idx++;
                    continue;
                }
                if (log_enabled)
                {
                    std::cout << "[LPR_OCSINK] frame=" << frame_id << " OCR Result: '" << normalized_label
                              << "' (Confidence: " << std::fixed << std::setprecision(2) << confidence
                              << ", Track " << track_id << ")" << std::endl;
                }

                // Prominent debug print for detected license plate - easy to grep
                lpr_dbg(">>>>>> DETECTED LP: \"%s\" (confidence: %.1f%%, track_id: %d) <<<<<<",
                        normalized_label.c_str(), confidence * 100.0f, track_id);

                lpr_dbg("ocr_sink: [veh %d][lp %d] adding track_id=%d to seen list", veh_idx, lp_idx, track_id);
                seen_ocr_track_ids.emplace_back(track_id);

                lpr_dbg("ocr_sink: [veh %d][lp %d] adding OCR result classification type='%s' label='%s'",
                        veh_idx, lp_idx, LPR_RESULT_LABEL_TYPE, normalized_label.c_str());
                HailoClassificationPtr final_classification = std::make_shared<HailoClassification>(
                    LPR_RESULT_LABEL_TYPE, normalized_label, confidence);
                vehicle_detection->add_object(final_classification);

                // Always print what OCR is added to vehicle classification
                if (log_enabled)
                {
                    std::printf("[LPR_OCRSINK] frame=%llu Added classification to vehicle: type='%s' OCR='%s' confidence=%.2f track_id=%d\n",
                                frame_id, LPR_RESULT_LABEL_TYPE, normalized_label.c_str(), confidence, track_id);
                    std::fflush(stdout);
                }

                // Update the tracker with the found ocr
                lpr_dbg("ocr_sink: [veh %d][lp %d] updating tracker '%s' with OCR result", veh_idx, lp_idx, jde_tracker_name.c_str());
                HailoTracker::GetInstance().add_object_to_track(jde_tracker_name,
                                                                track_id,
                                                                final_classification);

                lpr_dbg("ocr_sink: [veh %d][lp %d] cataloging license plate", veh_idx, lp_idx);
                catalog_license_plate(normalized_label, confidence, license_plate_box, hmat, lp_detection);
                break;
            }
            else
            {
                lpr_dbg("ocr_sink: [veh %d][lp %d] SKIP - classification type mismatch (got '%s', expected '%s')",
                        veh_idx, lp_idx, cls_type.c_str(), OCR_LABEL_TYPE);
            }
            lp_idx++;
        }
        veh_idx++;
    }
    lpr_dbg("========== ocr_sink: EXIT ==========");
    return;
}

void filter(HailoROIPtr roi, GstVideoFrame *frame)
{
    lpr_log_settings();
    lpr_dbg("========== lpr_ocrsink filter: ENTER ==========");
    const bool log_enabled = lpr_debug_enabled();
    if (!frame)
    {
        if (log_enabled)
            std::cout << "[LPR_OCSINK] filter: frame is null" << std::endl;
        lpr_dbg("lpr_ocrsink filter: null frame => EXIT");
        return;
    }
    if (!roi)
    {
        if (log_enabled)
            std::cout << "[LPR_OCSINK] filter: ROI is null" << std::endl;
        lpr_dbg("lpr_ocrsink filter: null ROI => EXIT");
        return;
    }
    const unsigned long long frame_id = g_lpr_frame_counter.fetch_add(1);
    GstClockTime pts = GST_BUFFER_PTS(frame->buffer);
    const unsigned long long pts_ns = GST_CLOCK_TIME_IS_VALID(pts) ? static_cast<unsigned long long>(pts) : 0ULL;

    std::shared_ptr<HailoMat> hmat = get_mat_by_format(*(&frame->buffer), &frame->info, 1, 1);
    lpr_dbg("lpr_ocrsink filter: frame_id=%llu frame=%dx%d format=%d mat_valid=%d pts_ns=%llu",
            frame_id, frame->info.width, frame->info.height, frame->info.finfo->format,
            hmat ? 1 : 0, pts_ns);

    // Print ROI structure
    auto all_dets = hailo_common::get_hailo_detections(roi);
    lpr_dbg("lpr_ocrsink filter: frame_id=%llu ROI has %zu top-level detections", frame_id, all_dets.size());

    ocr_sink(roi, hmat, frame_id);

    lpr_dbg("========== lpr_ocrsink filter: EXIT ==========");
}
