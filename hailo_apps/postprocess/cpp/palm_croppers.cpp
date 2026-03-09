/**
 * Copyright (c) 2021-2022 Hailo Technologies Ltd. All rights reserved.
 * Distributed under the LGPL license (https://www.gnu.org/licenses/old-licenses/lgpl-2.1.txt)
 *
 * Palm-to-hand cropper for hailocropper element.
 * Creates hand crop regions from palm detections with rotation envelope.
 * Stores rotation angle for the affine warp stage.
 *
 * Ports detection2roi logic from blaze_base.py.
 * All geometry is computed in pixel space (matching the Python pipeline)
 * to avoid aspect-ratio bugs on non-square frames.
 **/
#include <vector>
#include <cmath>
#include <algorithm>
#include <string>
#include "palm_croppers.hpp"

// detection2roi parameters (from blaze_base.py PALM_MODEL_CONFIG)
#define KP1_INDEX 0  // wrist center
#define KP2_INDEX 2  // middle finger base
#define THETA0 (M_PI / 2.0f)
#define DSCALE 2.6f
#define DY (-0.5f)

#define MAX_HANDS 4

static inline float clamp01(float v)
{
    return std::max(0.0f, std::min(1.0f, v));
}

std::vector<HailoROIPtr> palm_to_hand_crop(std::shared_ptr<HailoMat> image, HailoROIPtr roi)
{
    std::vector<HailoROIPtr> crop_rois;

    // Frame dimensions for pixel-space geometry (matches Python blaze_base.detection2roi)
    float frame_w = (float)image->width();
    float frame_h = (float)image->height();

    auto detections = hailo_common::get_hailo_detections(roi);
    int hand_count = 0;

    for (auto &detection : detections)
    {
        if (hand_count >= MAX_HANDS)
            break;

        if (detection->get_label() != "palm")
            continue;

        // Get palm keypoints
        auto landmarks_objs = detection->get_objects_typed(HAILO_LANDMARKS);
        if (landmarks_objs.empty())
            continue;

        auto landmarks = std::dynamic_pointer_cast<HailoLandmarks>(landmarks_objs[0]);
        if (!landmarks)
            continue;

        auto points = landmarks->get_points();
        if (points.size() < 7)
            continue;

        HailoBBox palm_bbox = detection->get_bbox();
        float xmin = palm_bbox.xmin();
        float ymin = palm_bbox.ymin();
        float xmax = xmin + palm_bbox.width();
        float ymax = ymin + palm_bbox.height();

        // Convert keypoints from bbox-relative [0,1] to frame pixel coords.
        // HailoLandmarks store points relative to parent detection bbox.
        // After hailoaggregator, the bbox is in frame-absolute normalized coords.
        float kp1_px = (xmin + points[KP1_INDEX].x() * (xmax - xmin)) * frame_w;
        float kp1_py = (ymin + points[KP1_INDEX].y() * (ymax - ymin)) * frame_h;
        float kp2_px = (xmin + points[KP2_INDEX].x() * (xmax - xmin)) * frame_w;
        float kp2_py = (ymin + points[KP2_INDEX].y() * (ymax - ymin)) * frame_h;

        // Rotation angle in pixel space
        float theta = std::atan2(kp1_py - kp2_py, kp1_px - kp2_px) - THETA0;

        // Box center and scale in pixel space
        float xc_px = (xmin + xmax) / 2.0f * frame_w;
        float yc_px = (ymin + ymax) / 2.0f * frame_h;
        float scale_px = (xmax - xmin) * frame_w;  // palm width in pixels

        // Apply offsets in pixel space
        yc_px += DY * scale_px;
        scale_px *= DSCALE;

        // AABB that encloses the rotated square (square in pixel space)
        float abs_cos = std::abs(std::cos(theta));
        float abs_sin = std::abs(std::sin(theta));
        float expand = abs_cos + abs_sin;
        float half_side_px = scale_px * expand / 2.0f;

        // Convert back to normalized [0,1] coords for HailoBBox
        float crop_xmin = clamp01((xc_px - half_side_px) / frame_w);
        float crop_ymin = clamp01((yc_px - half_side_px) / frame_h);
        float crop_xmax = clamp01((xc_px + half_side_px) / frame_w);
        float crop_ymax = clamp01((yc_px + half_side_px) / frame_h);
        float crop_w = crop_xmax - crop_xmin;
        float crop_h = crop_ymax - crop_ymin;

        if (crop_w < 0.02f || crop_h < 0.02f)
            continue;

        HailoBBox hand_bbox(crop_xmin, crop_ymin, crop_w, crop_h);
        auto hand_detection = std::make_shared<HailoDetection>(
            hand_bbox, "hand", detection->get_confidence());

        // Store rotation angle in the label string (confidence must be [0,1])
        auto angle_cls = std::make_shared<HailoClassification>(
            "palm_angle", std::to_string(theta), 1.0f);
        hand_detection->add_object(angle_cls);

        roi->add_object(hand_detection);
        crop_rois.emplace_back(hand_detection);
        hand_count++;
    }

    return crop_rois;
}
