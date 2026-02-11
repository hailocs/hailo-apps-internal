/**
 * Copyright (c) 2021-2022 Hailo Technologies Ltd. All rights reserved.
 * Distributed under the LGPL license (https://www.gnu.org/licenses/old-licenses/lgpl-2.1.txt)
 **/
#pragma once

#include <vector>
#include <string>
#include <memory>
#include <mutex>
#include <unordered_map>
#include <atomic>

// OpenCV forward declaration for blur detection
#include <opencv2/core/mat.hpp>

#include "hailo_objects.hpp"
#include "hailomat.hpp"

/**
 * @brief Generic class for cropping objects from images based on detection metadata.
 *
 * Supports:
 * - Filtering by ROI, size, and area.
 * - Image quality checks (blur detection).
 * - Prioritization of unrecognized objects (by confidence).
 * - Round-robin servicing of recognized objects (by aging) to prevent starvation.
 * - Recursive cropping (finding sub-objects within main detections).
 * - Thread-safe state management.
 */
class GenericCropper
{
public:
    struct Config
    {
        std::string name;             ///< Name identifier for this cropper instance (for logging).
        std::string main_class;       ///< Label of the main object to process (e.g. "vehicle").
        std::string crop_class;       ///< Label of the object to crop. If same as main_class, crops the main object.
        std::string recognition_type; ///< Classification type indicating the object has been recognized (e.g. "license_plate").

        float min_width_px = 0.0f;      ///< Minimum crop width in pixels.
        float min_height_px = 0.0f;     ///< Minimum crop height in pixels.
        float min_relative_area = 0.0f; ///< Minimum crop area relative to frame size (0.0-1.0).

        bool blur_check_enabled = false;
        float blur_threshold = 0.0f; ///< Laplacian variance threshold.

        size_t max_crops_per_frame = 0; ///< Maximum number of crops to return per frame. 0 = unlimited.

        bool roi_check_enabled = false;
        HailoBBox roi_rect = HailoBBox(0.0f, 0.0f, 1.0f, 1.0f); ///< Valid Region of Interest (normalized 0-1).

        // If true, sorts unrecognized objects by confidence (descending).
        bool sort_by_confidence = true;

        // Debugging
        std::string debug_crop_dir;
        bool debug_save_crops = false;
    };

    /**
     * @brief Construct a new Generic Cropper object.
     *
     * @param config Configuration parameters.
     */
    GenericCropper(const Config &config);
    virtual ~GenericCropper() = default;

    /**
     * @brief Process an image and ROI to extract valid crops.
     *
     * @param image Input full frame image.
     * @param roi Input ROI containing detections.
     * @return std::vector<HailoROIPtr> Vector of cropped ROI objects ready for inference.
     */
    std::vector<HailoROIPtr> process(std::shared_ptr<HailoMat> image, HailoROIPtr roi);

private:
    struct Candidate
    {
        HailoDetectionPtr detection;                    ///< The detection to crop (either main or sub-object).
        HailoDetectionPtr main_object;                  ///< The main object (e.g. vehicle) carrying the track ID.
        HailoBBox clamped_bbox{0.0f, 0.0f, 0.0f, 0.0f}; ///< Bounding box clamped to image boundaries.
        int track_id = -1;
        float confidence = 0.0f;
        float score = 0.0f;      ///< Sorting score.
        bool recognized = false; ///< Whether the object has already been recognized.
        float last_seen = 0.0f;  ///< Timestamp of last crop (from aging map).
    };

    Config m_config;

    // State for tracking aging of recognized objects.
    // Map: track_id -> last_cropped_timestamp_ms.
    // Member variable assumes instance persistence or static instantiation in caller.
    struct AgingState
    {
        std::unordered_map<int, long long> last_crop_time;
        std::mutex mutex;
    };
    AgingState m_aging_state;

    // Counters for debug filenames and cleanup.
    std::atomic<int> m_crop_counter{0};
    std::atomic<int> m_frame_counter{0};

    // Helper functions
    bool validate_roi(const HailoBBox &bbox);
    bool check_blur(std::shared_ptr<HailoMat> image, const HailoBBox &bbox);
    bool is_recognized(const HailoDetectionPtr &main_object);
    void save_crop(std::shared_ptr<HailoMat> image, const HailoBBox &bbox, const std::string &prefix, int track_id);

    // Image utilities
    float calculate_blur_score(const cv::Mat &img);
    cv::Mat get_crop_cv(std::shared_ptr<HailoMat> image, const HailoBBox &bbox);

    // Debug logging implementation (called by macro)
    void cropper_dbg_impl(const char *fmt, ...) const;
};
