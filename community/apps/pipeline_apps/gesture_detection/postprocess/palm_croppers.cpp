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

#define MAX_HANDS 2
#define PALM_CLASS_ID 100  // Must match palm_detection_postprocess.cpp

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

    // Collect palm detections from two possible locations:
    // 1. Direct children of ROI (whole-buffer mode)
    // 2. Nested inside person_palm_crop sub-detections (person-crop mode)
    //    In case 2, palm coords are parent-bbox-relative and must be promoted
    //    to frame-absolute so the hand crop geometry works correctly.
    //
    // Promoted palms are collected first, then NMS'd to remove duplicates from
    // overlapping person crops before adding survivors to the ROI.
    std::vector<HailoDetectionPtr> palms;
    std::vector<HailoDetectionPtr> promoted_palms;  // from person_palm_crop, not yet on ROI
    auto detections = hailo_common::get_hailo_detections(roi);

    for (auto &det : detections)
    {
        if (det->get_label() == "palm")
        {
            palms.push_back(det);
        }
        else if (det->get_label() == "person_palm_crop")
        {
            HailoBBox pb = det->get_bbox();
            for (auto &child_obj : det->get_objects_typed(HAILO_DETECTION))
            {
                auto child = std::dynamic_pointer_cast<HailoDetection>(child_obj);
                if (!child || child->get_label() != "palm")
                    continue;

                // Convert bbox from parent-relative to frame-absolute
                HailoBBox cb = child->get_bbox();
                HailoBBox abs_bbox(
                    pb.xmin() + cb.xmin() * pb.width(),
                    pb.ymin() + cb.ymin() * pb.height(),
                    cb.width() * pb.width(),
                    cb.height() * pb.height());

                auto promoted = std::make_shared<HailoDetection>(
                    abs_bbox, PALM_CLASS_ID, "palm", child->get_confidence());

                // Copy landmarks — keypoints are bbox-relative [0,1] so they
                // stay valid with the new (remapped) parent bbox
                for (auto &lm_obj : child->get_objects_typed(HAILO_LANDMARKS))
                    promoted->add_object(lm_obj);

                promoted_palms.push_back(promoted);
            }
        }
    }

    // Frame-level NMS on promoted palms: deduplicate detections from overlapping
    // person crops before adding to the ROI. Without this, the same physical palm
    // detected in two overlapping person crops produces two tracked IDs.
    std::sort(promoted_palms.begin(), promoted_palms.end(),
              [](const HailoDetectionPtr &a, const HailoDetectionPtr &b) {
                  return a->get_confidence() > b->get_confidence();
              });
    {
        std::vector<bool> suppressed(promoted_palms.size(), false);
        for (size_t i = 0; i < promoted_palms.size(); i++)
        {
            if (suppressed[i]) continue;
            HailoBBox bi = promoted_palms[i]->get_bbox();
            float ci_x = bi.xmin() + bi.width() / 2.0f;
            float ci_y = bi.ymin() + bi.height() / 2.0f;
            for (size_t j = i + 1; j < promoted_palms.size(); j++)
            {
                if (suppressed[j]) continue;
                HailoBBox bj = promoted_palms[j]->get_bbox();
                float cj_x = bj.xmin() + bj.width() / 2.0f;
                float cj_y = bj.ymin() + bj.height() / 2.0f;
                // Suppress if centers are close (within 1.5x palm width)
                float dx = ci_x - cj_x, dy = ci_y - cj_y;
                float dist = std::sqrt(dx * dx + dy * dy);
                float radius = std::max(bi.width(), bi.height()) * 1.5f;
                if (dist < radius)
                    suppressed[j] = true;
            }
        }
        int added = 0;
        for (size_t i = 0; i < promoted_palms.size() && added < MAX_HANDS; i++)
        {
            if (!suppressed[i])
            {
                roi->add_object(promoted_palms[i]);
                palms.push_back(promoted_palms[i]);
                added++;
            }
        }
    }

    int hand_count = 0;

    for (auto &detection : palms)
    {
        if (hand_count >= MAX_HANDS)
            break;

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
        // Use max of width/height in pixels to handle non-square palm bboxes
        // (can happen due to frame aspect ratio or model stretching)
        float width_px = (xmax - xmin) * frame_w;
        float height_px = (ymax - ymin) * frame_h;
        float scale_px = std::max(width_px, height_px);

        // Apply offsets along the hand axis (rotated coordinate frame)
        xc_px += -DY * scale_px * std::sin(theta);
        yc_px += DY * scale_px * std::cos(theta);
        scale_px *= DSCALE;

        // Use fixed maximum expansion (sqrt2) so the crop size doesn't
        // depend on rotation. hand_affine_warp handles the actual rotation
        // inside the crop buffer. This ensures a stable, always-square crop.
        static const float FIXED_EXPAND = 1.41421356f; // sqrt(2)
        float half_side_px = scale_px * FIXED_EXPAND / 2.0f;

        // Compute normalized crop ensuring it's square in pixel space.
        // Use separate half-widths in normalized coords to guarantee the
        // hailocropper extracts a square crop.
        float half_norm_x = half_side_px / frame_w;
        float half_norm_y = half_side_px / frame_h;
        float cx_norm = xc_px / frame_w;
        float cy_norm = yc_px / frame_h;

        float crop_xmin = clamp01(cx_norm - half_norm_x);
        float crop_ymin = clamp01(cy_norm - half_norm_y);
        float crop_xmax = clamp01(cx_norm + half_norm_x);
        float crop_ymax = clamp01(cy_norm + half_norm_y);
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
