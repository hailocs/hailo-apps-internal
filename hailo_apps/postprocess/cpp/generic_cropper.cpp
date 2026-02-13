/**
 * Copyright (c) 2021-2022 Hailo Technologies Ltd. All rights reserved.
 * Distributed under the LGPL license (https://www.gnu.org/licenses/old-licenses/lgpl-2.1.txt)
 **/

// OpenCV includes must come first
#include <opencv2/imgproc.hpp>
#include <opencv2/imgcodecs.hpp>

#include "generic_cropper.hpp"
#include "hailo_common.hpp"
#include "hailomat.hpp"
#include <algorithm>
#include <chrono>
#include <iostream>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <cstdarg>
#include <cstdio>

// Helper to get current time in ms
static long long get_current_time_ms()
{
    return std::chrono::duration_cast<std::chrono::milliseconds>(
               std::chrono::system_clock::now().time_since_epoch())
        .count();
}

// Debug logging control via environment variable
static bool generic_cropper_debug_enabled()
{
    static bool initialized = false;
    static bool enabled = false;
    if (!initialized)
    {
        const char *val = std::getenv("HAILO_GENERIC_CROPPER_DEBUG");
        enabled = (val != nullptr && val[0] != '\0');
        initialized = true;
    }
    return enabled;
}

GenericCropper::GenericCropper(const Config &config)
    : m_config(config)
{
}

// Debug logging member function implementation
void GenericCropper::cropper_dbg_impl(const char *fmt, ...) const
{
    if (!m_config.name.empty())
    {
        std::cerr << "[generic_cropper:" << m_config.name << "] ";
    }
    else
    {
        std::cerr << "[generic_cropper] ";
    }
    va_list args;
    va_start(args, fmt);
    std::vfprintf(stderr, fmt, args);
    va_end(args);
    std::cerr << std::endl;
}

// Macro to avoid function call overhead when debug is disabled
// Note: This macro must be used within GenericCropper member functions to access 'this'
#define cropper_dbg(...)                         \
    do                                           \
    {                                            \
        if (generic_cropper_debug_enabled())     \
        {                                        \
            this->cropper_dbg_impl(__VA_ARGS__); \
        }                                        \
    } while (0)

/**
 * @brief Validates if the bounding box is within the configured ROI.
 *        Uses "center inside" logic: passes if the center of the bbox is inside the ROI rectangle.
 *
 * @param bbox The bounding box to validate.
 * @return true if the bbox center is within the ROI, false otherwise.
 */
bool GenericCropper::validate_roi(const HailoBBox &bbox)
{
    if (!m_config.roi_check_enabled)
        return true;

    // Center of the bounding box
    float cx = bbox.xmin() + 0.5f * bbox.width();
    float cy = bbox.ymin() + 0.5f * bbox.height();

    // Check if center is strictly inside the ROI rectangle
    return (cx >= m_config.roi_rect.xmin() &&
            cy >= m_config.roi_rect.ymin() &&
            cx <= m_config.roi_rect.xmax() &&
            cy <= m_config.roi_rect.ymax());
}

/**
 * @brief Calculates blur score using Laplacian variance.
 *
 * @param img Input image (grayscale).
 * @return float Variance of Laplacian (higher is sharper).
 */
float GenericCropper::calculate_blur_score(const cv::Mat &img)
{
    if (img.empty())
        return 0.0f;

    cv::Mat laplacian;
    cv::Laplacian(img, laplacian, CV_64F);

    cv::Scalar mean, stddev;
    cv::meanStdDev(laplacian, mean, stddev);

    // Variance = stddev^2
    return static_cast<float>(stddev[0] * stddev[0]);
}

/**
 * @brief Extracts a crop from the image as a grayscale cv::Mat.
 *        Handles different input formats (RGB, YUY2, NV12).
 *
 * @param image Source HailoMat image.
 * @param bbox Region to crop.
 * @return cv::Mat Grayscale crop.
 */
cv::Mat GenericCropper::get_crop_cv(std::shared_ptr<HailoMat> image, const HailoBBox &bbox)
{
    cv::Mat gray;
    if (!image)
        return gray;

    auto crop_roi = std::make_shared<HailoROI>(bbox);
    std::vector<cv::Mat> cropped = image->crop(crop_roi);
    if (cropped.empty() || cropped[0].empty())
        return gray;

    switch (image->get_type())
    {
    case HAILO_MAT_RGB:
        cv::cvtColor(cropped[0], gray, cv::COLOR_RGB2GRAY);
        break;
    case HAILO_MAT_YUY2:
        cv::cvtColor(cropped[0], gray, cv::COLOR_YUV2GRAY_YUY2);
        break;
    case HAILO_MAT_NV12:
        if (cropped.size() >= 2) // NV12 has 2 planes
            cv::cvtColorTwoPlane(cropped[0], cropped[1], gray, cv::COLOR_YUV2GRAY_NV12);
        else
            gray = cropped[0]; // Should not happen for valid NV12
        break;
    default:
        if (cropped[0].channels() == 3)
            cv::cvtColor(cropped[0], gray, cv::COLOR_BGR2GRAY);
        else
            gray = cropped[0];
        break;
    }
    return gray;
}

/**
 * @brief Checks if the crop passes the blur threshold.
 *
 * @param image Source image.
 * @param bbox Region to check.
 * @return true if sharp enough or check disabled, false if blurry.
 */
bool GenericCropper::check_blur(std::shared_ptr<HailoMat> image, const HailoBBox &bbox)
{
    if (!m_config.blur_check_enabled)
        return true;

    cv::Mat gray = get_crop_cv(image, bbox);
    if (gray.empty())
        return false;

    float score = calculate_blur_score(gray);
    return score >= m_config.blur_threshold;
}

/**
 * @brief Checks if the object has already been recognized (has specific classification).
 *
 * @param main_object The detection object to check.
 * @return true if recognized, false otherwise.
 */
bool GenericCropper::is_recognized(const HailoDetectionPtr &main_object)
{
    if (m_config.recognition_type.empty())
        return false;

    auto classifications = main_object->get_objects_typed(HAILO_CLASSIFICATION);
    for (auto &obj : classifications)
    {
        auto cls = std::dynamic_pointer_cast<HailoClassification>(obj);
        if (cls && cls->get_classification_type() == m_config.recognition_type)
            return true;
    }
    return false;
}

/**
 * @brief Saves crop to disk for debugging purposes.
 */
void GenericCropper::save_crop(std::shared_ptr<HailoMat> image, const HailoBBox &bbox, const std::string &prefix, int track_id)
{
    if (!m_config.debug_save_crops || m_config.debug_crop_dir.empty())
        return;

    auto crop_roi = std::make_shared<HailoROI>(bbox);
    std::vector<cv::Mat> cropped = image->crop(crop_roi);
    if (cropped.empty() || cropped[0].empty())
        return;

    cv::Mat bgr;
    switch (image->get_type())
    {
    case HAILO_MAT_RGB:
        cv::cvtColor(cropped[0], bgr, cv::COLOR_RGB2BGR);
        break;
    case HAILO_MAT_YUY2:
        cv::cvtColor(cropped[0], bgr, cv::COLOR_YUV2BGR_YUY2);
        break;
    case HAILO_MAT_NV12:
        if (cropped.size() >= 2)
            cv::cvtColorTwoPlane(cropped[0], cropped[1], bgr, cv::COLOR_YUV2BGR_NV12);
        break;
    default:
        bgr = cropped[0];
        break;
    }

    if (bgr.empty())
        return;

    std::string cmd = "mkdir -p " + m_config.debug_crop_dir;
    if (system(cmd.c_str()) != 0)
    { /* ignore */
    }

    char filename[256];
    int count = m_crop_counter.fetch_add(1);
    snprintf(filename, sizeof(filename), "%s/%s_track%d_%05d.jpg",
             m_config.debug_crop_dir.c_str(), prefix.c_str(), track_id, count);

    cv::imwrite(filename, bgr);
}

/**
 * @brief Main processing function. Selects best crops based on configuration.
 *
 * @param image Full frame image.
 * @param roi Region of Interest containing detections.
 * @return std::vector<HailoROIPtr> Selected crops.
 */
std::vector<HailoROIPtr> GenericCropper::process(std::shared_ptr<HailoMat> image, HailoROIPtr roi)
{
    std::vector<HailoROIPtr> result_rois;
    if (!image || !roi)
    {
        cropper_dbg("process: NULL image or roi, returning empty");
        return result_rois;
    }

    int img_w = image->width();
    int img_h = image->height();
    cropper_dbg("process: starting | image_size=%dx%d | main_class='%s' | crop_class='%s'",
                img_w, img_h, m_config.main_class.c_str(), m_config.crop_class.c_str());

    // 1. Identify candidates
    std::vector<Candidate> candidates;
    auto detections = hailo_common::get_hailo_detections(roi);
    cropper_dbg("process: found %zu detection(s) in ROI", detections.size());

    for (auto &det : detections)
    {
        if (det->get_label() != m_config.main_class)
        {
            cropper_dbg("  detection: label='%s' (skipped, not main_class='%s')",
                        det->get_label().c_str(), m_config.main_class.c_str());
            continue;
        }
        cropper_dbg("  detection: label='%s' conf=%.3f (matches main_class)",
                    det->get_label().c_str(), det->get_confidence());

        // Get track ID of main object
        int track_id = -1;
        for (auto obj : det->get_objects_typed(HAILO_UNIQUE_ID))
        {
            auto uid = std::dynamic_pointer_cast<HailoUniqueID>(obj);
            if (uid && uid->get_mode() == TRACKING_ID)
            {
                track_id = uid->get_id();
                break;
            }
        }

        // Check if we are looking for sub-objects
        bool search_sub = (!m_config.crop_class.empty() && m_config.crop_class != m_config.main_class);

        if (search_sub)
        {
            auto sub_dets = hailo_common::get_hailo_detections(det);
            for (auto &sub : sub_dets)
            {
                if (sub->get_label() == m_config.crop_class)
                {
                    // Candidate found (Sub-object)
                    Candidate cand;
                    cand.detection = sub;
                    cand.main_object = det;
                    cand.track_id = track_id;
                    cand.confidence = sub->get_confidence();
                    cand.recognized = is_recognized(det);

                    // Flatten bbox to full frame
                    cand.clamped_bbox = hailo_common::create_flattened_bbox(sub->get_bbox(), sub->get_scaling_bbox());

                    cropper_dbg("    candidate: sub-object label='%s' conf=%.3f track_id=%d bbox=(%.3f,%.3f,%.3f,%.3f) recognized=%s",
                                sub->get_label().c_str(), cand.confidence, track_id,
                                cand.clamped_bbox.xmin(), cand.clamped_bbox.ymin(),
                                cand.clamped_bbox.width(), cand.clamped_bbox.height(),
                                cand.recognized ? "YES" : "NO");
                    candidates.push_back(cand);
                }
            }
        }
        else
        {
            // Candidate is the main object itself
            Candidate cand;
            cand.detection = det;
            cand.main_object = det;
            cand.track_id = track_id;
            cand.confidence = det->get_confidence();
            cand.recognized = is_recognized(det);
            cand.clamped_bbox = det->get_bbox();

            cropper_dbg("    candidate: main-object label='%s' conf=%.3f track_id=%d bbox=(%.3f,%.3f,%.3f,%.3f) recognized=%s",
                        det->get_label().c_str(), cand.confidence, track_id,
                        cand.clamped_bbox.xmin(), cand.clamped_bbox.ymin(),
                        cand.clamped_bbox.width(), cand.clamped_bbox.height(),
                        cand.recognized ? "YES" : "NO");
            candidates.push_back(cand);
        }
    }

    // 2. Filter & Prepare Candidates
    std::vector<Candidate> valid_candidates;
    cropper_dbg("process: filtering %zu candidate(s)", candidates.size());
    {
        std::lock_guard<std::mutex> lock(m_aging_state.mutex);

        for (size_t i = 0; i < candidates.size(); ++i)
        {
            auto &cand = candidates[i];
            cropper_dbg("  candidate[%zu]: label='%s' conf=%.3f track_id=%d",
                        i, cand.detection->get_label().c_str(), cand.confidence, cand.track_id);

            // Clamp bbox to [0,1]
            float xmin = std::max(0.0f, std::min(1.0f, cand.clamped_bbox.xmin()));
            float ymin = std::max(0.0f, std::min(1.0f, cand.clamped_bbox.ymin()));
            float xmax = std::max(xmin, std::min(1.0f, cand.clamped_bbox.xmax()));
            float ymax = std::max(ymin, std::min(1.0f, cand.clamped_bbox.ymax()));
            cand.clamped_bbox = HailoBBox(xmin, ymin, xmax - xmin, ymax - ymin);

            // ROI Check
            if (!validate_roi(cand.clamped_bbox))
            {
                cropper_dbg("    REJECTED: ROI check failed | bbox_center=(%.3f,%.3f) roi_rect=(%.3f,%.3f,%.3f,%.3f)",
                            cand.clamped_bbox.xmin() + 0.5f * cand.clamped_bbox.width(),
                            cand.clamped_bbox.ymin() + 0.5f * cand.clamped_bbox.height(),
                            m_config.roi_rect.xmin(), m_config.roi_rect.ymin(),
                            m_config.roi_rect.xmax(), m_config.roi_rect.ymax());
                continue;
            }

            // Size Check
            float w_px = cand.clamped_bbox.width() * img_w;
            float h_px = cand.clamped_bbox.height() * img_h;
            if (w_px < m_config.min_width_px || h_px < m_config.min_height_px)
            {
                cropper_dbg("    REJECTED: size check failed | size_px=%.1fx%.1f | min_required=%.1fx%.1f",
                            w_px, h_px, m_config.min_width_px, m_config.min_height_px);
                continue;
            }

            // Area Check (relative to frame)
            float area = cand.clamped_bbox.width() * cand.clamped_bbox.height();
            if (area < m_config.min_relative_area)
            {
                cropper_dbg("    REJECTED: area check failed | area=%.6f | min_required=%.6f",
                            area, m_config.min_relative_area);
                continue;
            }

            // Aging lookup
            if (m_aging_state.last_crop_time.count(cand.track_id))
            {
                cand.last_seen = static_cast<float>(m_aging_state.last_crop_time[cand.track_id]);
            }
            else
            {
                cand.last_seen = 0.0f; // Never seen
            }

            cropper_dbg("    PASSED: all filters passed | size_px=%.1fx%.1f area=%.6f",
                        w_px, h_px, area);
            valid_candidates.push_back(cand);
        }
    }
    cropper_dbg("process: %zu candidate(s) passed filters", valid_candidates.size());

    // 3. Split & Sort
    std::vector<Candidate> unrecog;
    std::vector<Candidate> recog;

    for (const auto &cand : valid_candidates)
    {
        if (cand.recognized)
            recog.push_back(cand);
        else
            unrecog.push_back(cand);
    }

    // Sort Unrecognized by Confidence Descending
    std::sort(unrecog.begin(), unrecog.end(), [](const Candidate &a, const Candidate &b)
              { return a.confidence > b.confidence; });

    // Sort Recognized by Aging (Last Seen) Ascending (Oldest first)
    // We prioritize recognized objects that haven't been seen for the longest time to prevent starvation.
    std::sort(recog.begin(), recog.end(), [](const Candidate &a, const Candidate &b)
              { return a.last_seen < b.last_seen; });

    // 4. Select Final Crops
    std::vector<Candidate *> selected;
    size_t limit = (m_config.max_crops_per_frame > 0) ? m_config.max_crops_per_frame : candidates.size();

    // Fill with Unrecognized first
    cropper_dbg("process: selecting from %zu unrecognized + %zu recognized (limit=%zu)",
                unrecog.size(), recog.size(), limit);
    for (auto &cand : unrecog)
    {
        if (selected.size() >= limit)
            break;
        // Blur check is expensive, do it here
        if (check_blur(image, cand.clamped_bbox))
        {
            cropper_dbg("  SELECTED: unrecognized label='%s' conf=%.3f track_id=%d",
                        cand.detection->get_label().c_str(), cand.confidence, cand.track_id);
            selected.push_back(&cand);
        }
        else
        {
            cropper_dbg("  REJECTED: unrecognized label='%s' conf=%.3f track_id=%d (blur check failed)",
                        cand.detection->get_label().c_str(), cand.confidence, cand.track_id);
        }
    }

    // If space remains, fill with Recognized
    if (selected.size() < limit)
    {
        for (auto &cand : recog)
        {
            if (selected.size() >= limit)
                break;
            if (check_blur(image, cand.clamped_bbox))
            {
                cropper_dbg("  SELECTED: recognized label='%s' conf=%.3f track_id=%d last_seen=%.0fms",
                            cand.detection->get_label().c_str(), cand.confidence, cand.track_id, cand.last_seen);
                selected.push_back(&cand);
            }
            else
            {
                cropper_dbg("  REJECTED: recognized label='%s' conf=%.3f track_id=%d (blur check failed)",
                            cand.detection->get_label().c_str(), cand.confidence, cand.track_id);
            }
        }
    }

    // 5. Commit & Return
    cropper_dbg("process: final selection: %zu crop(s) selected", selected.size());
    long long now_ts = get_current_time_ms();
    {
        std::lock_guard<std::mutex> lock(m_aging_state.mutex);
        for (size_t i = 0; i < selected.size(); ++i)
        {
            auto *cand = selected[i];
            cropper_dbg("  crop[%zu]: label='%s' conf=%.3f track_id=%d bbox=(%.3f,%.3f,%.3f,%.3f)",
                        i, cand->detection->get_label().c_str(), cand->confidence, cand->track_id,
                        cand->clamped_bbox.xmin(), cand->clamped_bbox.ymin(),
                        cand->clamped_bbox.width(), cand->clamped_bbox.height());
            {
                // Update bbox
                cand->detection->set_bbox(cand->clamped_bbox);
                cand->detection->set_scaling_bbox(HailoBBox(0.0f, 0.0f, 1.0f, 1.0f));

                // Ensure track ID on the crop object
                if (cand->track_id >= 0)
                {
                    bool has_track = false;
                    for (auto obj : cand->detection->get_objects_typed(HAILO_UNIQUE_ID))
                    {
                        if (auto uid = std::dynamic_pointer_cast<HailoUniqueID>(obj))
                        {
                            if (uid->get_mode() == TRACKING_ID && uid->get_id() == cand->track_id)
                                has_track = true;
                        }
                    }
                    if (!has_track)
                    {
                        cand->detection->add_object(std::make_shared<HailoUniqueID>(cand->track_id, TRACKING_ID));
                    }
                }

                // Update aging
                if (cand->track_id >= 0)
                {
                    m_aging_state.last_crop_time[cand->track_id] = now_ts;
                }

                result_rois.push_back(cand->detection);

                // Debug save
                if (m_config.debug_save_crops)
                {
                    save_crop(image, cand->clamped_bbox, "generic_crop", cand->track_id);
                }
            }
        }
        cropper_dbg("process: completed | returning %zu crop(s)", result_rois.size());

        // Periodic cleanup of aging map to prevent memory leaks
        // Runs every 100 frames, removes entries older than 10 seconds
        int fc = m_frame_counter.fetch_add(1);
        if (fc % 100 == 0)
        {
            for (auto it = m_aging_state.last_crop_time.begin(); it != m_aging_state.last_crop_time.end();)
            {
                if ((now_ts - it->second) > 10000)
                {
                    it = m_aging_state.last_crop_time.erase(it);
                }
                else
                {
                    ++it;
                }
            }
        }
    }

    return result_rois;
}
