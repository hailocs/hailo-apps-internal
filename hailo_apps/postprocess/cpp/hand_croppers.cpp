/**
 * Copyright (c) 2021-2022 Hailo Technologies Ltd. All rights reserved.
 * Distributed under the LGPL license (https://www.gnu.org/licenses/old-licenses/lgpl-2.1.txt)
 **/
#include <vector>
#include <cmath>
#include <algorithm>
#include <unordered_map>
#include "hand_croppers.hpp"

// YOLOv8 pose keypoint indices
#define LEFT_ELBOW_INDEX 7
#define RIGHT_ELBOW_INDEX 8
#define LEFT_WRIST_INDEX 9
#define RIGHT_WRIST_INDEX 10

// Cropping parameters
#define WRIST_CONFIDENCE_THRESHOLD 0.3f
#define HAND_SIZE_SCALE 2.5f
#define FALLBACK_HAND_SIZE_RATIO 0.15f  // 15% of person bbox height
#define MAX_HANDS_PER_FRAME 2

#define PERSON_LABEL "person"

static HailoUniqueIDPtr get_tracking_id(HailoDetectionPtr detection)
{
    for (auto obj : detection->get_objects_typed(HAILO_UNIQUE_ID))
    {
        HailoUniqueIDPtr id = std::dynamic_pointer_cast<HailoUniqueID>(obj);
        if (id->get_mode() == TRACKING_ID)
            return id;
    }
    return nullptr;
}

static inline float clamp(float val, float min_val, float max_val)
{
    return std::max(min_val, std::min(val, max_val));
}

static inline float distance_2d(float x1, float y1, float x2, float y2)
{
    float dx = x2 - x1;
    float dy = y2 - y1;
    return std::sqrt(dx * dx + dy * dy);
}

std::vector<HailoROIPtr> hand_crop(std::shared_ptr<HailoMat> image, HailoROIPtr roi)
{
    static std::unordered_map<int, int> track_ages;
    std::vector<HailoROIPtr> crop_rois;

    std::vector<HailoDetectionPtr> detections_ptrs = hailo_common::get_hailo_detections(roi);

    // Increment the age of all tracks
    for (auto &entry : track_ages)
        entry.second++;

    // Sort detections by track age (oldest first) for fairness
    std::sort(detections_ptrs.begin(), detections_ptrs.end(),
              [&](const HailoDetectionPtr &a, const HailoDetectionPtr &b)
              {
                  auto tracking_obj_a = get_tracking_id(a);
                  auto tracking_obj_b = get_tracking_id(b);
                  if (tracking_obj_a && tracking_obj_b)
                  {
                      int track_id_a = tracking_obj_a->get_id();
                      int track_id_b = tracking_obj_b->get_id();
                      return track_ages[track_id_a] > track_ages[track_id_b];
                  }
                  return false;
              });

    int hand_count = 0;

    for (HailoDetectionPtr &detection : detections_ptrs)
    {
        if (hand_count >= MAX_HANDS_PER_FRAME)
            break;

        if (std::string(PERSON_LABEL) != detection->get_label())
            continue;

        auto landmarks_objs = detection->get_objects_typed(HAILO_LANDMARKS);
        if (landmarks_objs.empty())
            continue;

        auto landmarks = std::dynamic_pointer_cast<HailoLandmarks>(landmarks_objs[0]);
        if (!landmarks)
            continue;

        auto points = landmarks->get_points();
        if (points.size() < 17)
            continue;

        HailoBBox person_bbox = detection->get_bbox();

        struct WristInfo
        {
            int wrist_idx;
            int elbow_idx;
            const char *side;
        };
        std::vector<WristInfo> wrists = {
            {LEFT_WRIST_INDEX, LEFT_ELBOW_INDEX, "left"},
            {RIGHT_WRIST_INDEX, RIGHT_ELBOW_INDEX, "right"}};

        for (const auto &wrist_info : wrists)
        {
            if (hand_count >= MAX_HANDS_PER_FRAME)
                break;

            auto &wrist_pt = points[wrist_info.wrist_idx];
            if (wrist_pt.confidence() < WRIST_CONFIDENCE_THRESHOLD)
                continue;

            // Wrist coordinates are detection-relative, convert to frame-relative
            float wrist_x = wrist_pt.x() * person_bbox.width() + person_bbox.xmin();
            float wrist_y = wrist_pt.y() * person_bbox.height() + person_bbox.ymin();

            // Estimate hand size from wrist-to-elbow distance
            float hand_size;
            auto &elbow_pt = points[wrist_info.elbow_idx];
            if (elbow_pt.confidence() >= WRIST_CONFIDENCE_THRESHOLD)
            {
                float elbow_x = elbow_pt.x() * person_bbox.width() + person_bbox.xmin();
                float elbow_y = elbow_pt.y() * person_bbox.height() + person_bbox.ymin();
                float wrist_elbow_dist = distance_2d(wrist_x, wrist_y, elbow_x, elbow_y);
                hand_size = wrist_elbow_dist * HAND_SIZE_SCALE;
            }
            else
            {
                hand_size = person_bbox.height() * FALLBACK_HAND_SIZE_RATIO;
            }

            hand_size = std::max(hand_size, 0.03f);

            float half_size = hand_size / 2.0f;
            float crop_xmin = clamp(wrist_x - half_size, 0.0f, 1.0f);
            float crop_ymin = clamp(wrist_y - half_size, 0.0f, 1.0f);
            float crop_width = clamp(hand_size, 0.0f, 1.0f - crop_xmin);
            float crop_height = clamp(hand_size, 0.0f, 1.0f - crop_ymin);

            if (crop_width < 0.02f || crop_height < 0.02f)
                continue;

            HailoBBox hand_bbox(crop_xmin, crop_ymin, crop_width, crop_height);
            HailoDetectionPtr hand_detection = std::make_shared<HailoDetection>(
                hand_bbox, "hand", wrist_pt.confidence());

            auto hand_side = std::make_shared<HailoClassification>(
                "hand_side", wrist_info.side, 1.0f);
            hand_detection->add_object(hand_side);

            detection->add_object(hand_detection);
            crop_rois.emplace_back(hand_detection);
            hand_count++;
        }

        // Reset the age of the processed track
        auto tracking_obj = get_tracking_id(detection);
        if (tracking_obj)
            track_ages[tracking_obj->get_id()] = 0;
    }

    // Remove old tracks that are no longer detected
    for (auto it = track_ages.begin(); it != track_ages.end();)
    {
        if (std::none_of(detections_ptrs.begin(), detections_ptrs.end(),
                         [&](const HailoDetectionPtr &detection)
                         {
                             auto tracking_obj = get_tracking_id(detection);
                             return tracking_obj && tracking_obj->get_id() == it->first;
                         }))
        {
            it = track_ages.erase(it);
        }
        else
        {
            ++it;
        }
    }

    return crop_rois;
}
