/**
 * Person-to-palm cropper for hailocropper element.
 *
 * For each detected person, creates a square crop region centered on the person.
 * This gives the palm detection model a zoomed-in view of each person instead of
 * the entire frame squeezed to 192x192 — dramatically improving detection range.
 *
 * Square crops avoid distortion since the palm model input is 192x192.
 * A minimum crop size of 192px ensures we never upscale tiny regions.
 */
#include <vector>
#include <algorithm>
#include "person_palm_croppers.hpp"

#define MAX_CROPS 4
#define EXPANSION 1.15f
#define MIN_CROP_PX 192.0f

static inline float clamp01(float v)
{
    return std::max(0.0f, std::min(1.0f, v));
}

std::vector<HailoROIPtr> person_palm_crop(std::shared_ptr<HailoMat> image, HailoROIPtr roi)
{
    std::vector<HailoROIPtr> crop_rois;

    float frame_w = (float)image->width();
    float frame_h = (float)image->height();

    auto detections = hailo_common::get_hailo_detections(roi);

    // Collect person detections and sort by area (largest first)
    std::vector<HailoDetectionPtr> persons;
    for (auto &det : detections)
    {
        if (det->get_label() == "person")
            persons.push_back(det);
    }

    std::sort(persons.begin(), persons.end(),
              [](const HailoDetectionPtr &a, const HailoDetectionPtr &b) {
                  float area_a = a->get_bbox().width() * a->get_bbox().height();
                  float area_b = b->get_bbox().width() * b->get_bbox().height();
                  return area_a > area_b;
              });

    int crop_count = 0;
    for (auto &person : persons)
    {
        if (crop_count >= MAX_CROPS)
            break;

        HailoBBox bbox = person->get_bbox();
        float cx_norm = bbox.xmin() + bbox.width() / 2.0f;
        float cy_norm = bbox.ymin() + bbox.height() / 2.0f;

        // Compute square side in pixel space
        float width_px = bbox.width() * frame_w;
        float height_px = bbox.height() * frame_h;
        float side_px = std::max(width_px, height_px) * EXPANSION;

        // Enforce minimum crop size — never upscale a tiny region
        side_px = std::max(side_px, MIN_CROP_PX);

        // Convert back to normalized coords
        float half_norm_x = (side_px / 2.0f) / frame_w;
        float half_norm_y = (side_px / 2.0f) / frame_h;

        float crop_xmin = clamp01(cx_norm - half_norm_x);
        float crop_ymin = clamp01(cy_norm - half_norm_y);
        float crop_xmax = clamp01(cx_norm + half_norm_x);
        float crop_ymax = clamp01(cy_norm + half_norm_y);
        float crop_w = crop_xmax - crop_xmin;
        float crop_h = crop_ymax - crop_ymin;

        if (crop_w < 0.02f || crop_h < 0.02f)
            continue;

        HailoBBox crop_bbox(crop_xmin, crop_ymin, crop_w, crop_h);
        auto crop_det = std::make_shared<HailoDetection>(
            crop_bbox, "person_palm_crop", person->get_confidence());

        roi->add_object(crop_det);
        crop_rois.emplace_back(crop_det);
        crop_count++;
    }

    return crop_rois;
}
