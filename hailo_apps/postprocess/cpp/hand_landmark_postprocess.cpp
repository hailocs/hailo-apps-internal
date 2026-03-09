/**
 * Copyright (c) 2021-2022 Hailo Technologies Ltd. All rights reserved.
 * Distributed under the LGPL license (https://www.gnu.org/licenses/old-licenses/lgpl-2.1.txt)
 *
 * Hand landmark postprocess for hand_landmark_lite.hef (224x224).
 * Runs inside hailocropper inner pipeline — ROI is the hand detection.
 *
 * The crop is square in pixel space (palm_croppers computes geometry in
 * pixel coords). videoscale to 224x224 is a uniform scale, so the warp
 * and model operate in proper square pixel space.
 * The inverse rotation in normalized [0,1] coords is a simple rotation
 * around (0.5, 0.5) with no aspect ratio correction.
 *
 * hailooverlay maps landmarks as: screen = (point * bbox_size + bbox_min) * frame_size
 */
#include <vector>
#include <algorithm>
#include <cmath>
#include <string>
#include "common/tensors.hpp"
#include "common/math.hpp"
#include "hand_landmark_postprocess.hpp"
#include "hailo_xtensor.hpp"
#include "xtensor/xadapt.hpp"
#include "xtensor/xarray.hpp"
#include "xtensor/xview.hpp"

#define NUM_HAND_LANDMARKS 21
#define HAND_LANDMARK_INPUT_SIZE 224.0f
#define HAND_FLAG_THRESHOLD 0.5f

static const std::string LANDMARKS_TENSOR_SUFFIX = "fc1";

static const std::vector<std::pair<int, int>> HAND_JOINT_PAIRS = {
    {0, 1}, {1, 2}, {2, 3}, {3, 4},       // Thumb
    {0, 5}, {5, 6}, {6, 7}, {7, 8},       // Index
    {5, 9}, {9, 10}, {10, 11}, {11, 12},   // Middle
    {9, 13}, {13, 14}, {14, 15}, {15, 16}, // Ring
    {13, 17}, {17, 18}, {18, 19}, {19, 20},// Pinky
    {0, 17}                                 // Palm
};

static HailoTensorPtr find_tensor_by_name_suffix(HailoROIPtr roi, const std::string &suffix)
{
    for (auto &tensor : roi->get_tensors())
    {
        const std::string &name = tensor->name();
        if (name.size() >= suffix.size() &&
            name.compare(name.size() - suffix.size(), suffix.size(), suffix) == 0)
        {
            return tensor;
        }
    }
    return nullptr;
}

/**
 * @brief Read palm_angle theta from HailoClassification on the ROI.
 */
static float get_palm_angle(HailoROIPtr roi)
{
    for (auto &cls_obj : roi->get_objects_typed(HAILO_CLASSIFICATION))
    {
        auto cls = std::dynamic_pointer_cast<HailoClassification>(cls_obj);
        if (cls && cls->get_classification_type() == "palm_angle")
        {
            try {
                return std::stof(cls->get_label());
            } catch (...) {
                return 0.0f;
            }
        }
    }
    return 0.0f;
}

void hand_landmark_postprocess(HailoROIPtr roi)
{
    if (!roi->has_tensors())
        return;

    HailoTensorPtr landmarks_tensor = find_tensor_by_name_suffix(roi, LANDMARKS_TENSOR_SUFFIX);

    // Find hand flag tensor (1-element tensor)
    HailoTensorPtr hand_flag_tensor = nullptr;
    for (auto &t : roi->get_tensors())
    {
        size_t total = t->width() * t->height() * t->features();
        if (total == 1)
        {
            hand_flag_tensor = t;
            break;
        }
    }

    if (!landmarks_tensor)
        return;

    if (hand_flag_tensor)
    {
        auto flag_data = common::get_xtensor_float(hand_flag_tensor);
        float raw = flag_data(0);
        float hand_flag = 1.0f / (1.0f + std::exp(-raw));
        if (hand_flag < HAND_FLAG_THRESHOLD)
            return;
    }

    // Dequantize landmarks from [0..224] to [0..1]
    auto landmarks_data = common::get_xtensor_float(landmarks_tensor);
    xt::xarray<float> landmarks = xt::reshape_view(landmarks_data, {NUM_HAND_LANDMARKS, 3});

    // Read palm_angle theta for inverse transform.
    // The affine warp did two things: (1) zoomed in by `expand` to compensate for
    // AABB padding, and (2) rotated by -theta to straighten the hand.
    // To map landmarks back to the AABB crop space, we reverse both:
    // (1) Scale by 1/expand (zoom back out), (2) Rotate by +theta.
    float theta = get_palm_angle(roi);
    float cos_t = std::cos(theta);
    float sin_t = std::sin(theta);
    float expand = std::abs(cos_t) + std::abs(sin_t);
    if (expand < 1.0f) expand = 1.0f;  // safety

    std::vector<HailoPoint> points;
    points.reserve(NUM_HAND_LANDMARKS);
    for (int i = 0; i < NUM_HAND_LANDMARKS; i++)
    {
        float nx = landmarks(i, 0) / HAND_LANDMARK_INPUT_SIZE;
        float ny = landmarks(i, 1) / HAND_LANDMARK_INPUT_SIZE;

        // Inverse of warp: first scale by 1/expand (undo zoom), then rotate by +theta
        float cx = (nx - 0.5f) / expand;
        float cy = (ny - 0.5f) / expand;
        float rx = cos_t * cx - sin_t * cy + 0.5f;
        float ry = sin_t * cx + cos_t * cy + 0.5f;

        rx = std::max(0.0f, std::min(1.0f, rx));
        ry = std::max(0.0f, std::min(1.0f, ry));

        points.emplace_back(rx, ry, 1.0f);
    }

    // Find hand detection — inside the cropper, the ROI IS the hand detection
    HailoDetectionPtr hand_det = nullptr;
    auto det_ptr = std::dynamic_pointer_cast<HailoDetection>(roi);
    if (det_ptr && det_ptr->get_label() == "hand")
        hand_det = det_ptr;

    if (!hand_det)
    {
        for (auto &obj : roi->get_objects_typed(HAILO_DETECTION))
        {
            auto det = std::dynamic_pointer_cast<HailoDetection>(obj);
            if (det && det->get_label() == "hand")
            {
                hand_det = det;
                break;
            }
        }
    }

    // Attach landmarks directly — [0,1] relative to the crop = detection bbox.
    // Do NOT use add_landmarks_to_detection() which re-normalizes incorrectly.
    auto landmarks_obj = std::make_shared<HailoLandmarks>(
        "hand_landmarks", points, 0.0f, HAND_JOINT_PAIRS);

    if (hand_det)
        hand_det->add_object(landmarks_obj);
    else
        roi->add_object(landmarks_obj);
}

void filter(HailoROIPtr roi)
{
    hand_landmark_postprocess(roi);
}
