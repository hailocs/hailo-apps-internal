/**
 * Copyright (c) 2021-2022 Hailo Technologies Ltd. All rights reserved.
 * Distributed under the LGPL license (https://www.gnu.org/licenses/old-licenses/lgpl-2.1.txt)
 **/
#include "lpr_croppers.hpp"
#include "generic_cropper.hpp"
#include "hailo_common.hpp"
#include <memory>
#include <mutex>

#define LICENSE_PLATE_LABEL "license_plate"
#define RECOGNIZED_LABEL "hailo_lpr_recognized"

// Static ROI rectangle - covers the full frame
static constexpr float STATIC_ROI_XMIN = 0.0f;
static constexpr float STATIC_ROI_YMIN = 0.0f;
static constexpr float STATIC_ROI_XMAX = 1.0f;
static constexpr float STATIC_ROI_YMAX = 1.0f;

/**
 * @brief License plate cropper for LPR pipeline.
 *        Uses GenericCropper to select license plates for OCR.
 *        License plates are at the top level of ROI from the plate detection stage.
 */
std::vector<HailoROIPtr> license_plate_cropper(std::shared_ptr<HailoMat> image, HailoROIPtr roi)
{
    static std::unique_ptr<GenericCropper> cropper = nullptr;
    static std::once_flag flag;
    std::call_once(flag, []()
                   {
        GenericCropper::Config config;
        config.name = "license_plate_cropper";
        // License plates are at the top level of ROI, not nested under vehicles
        // So we set main_class == crop_class to search at the top level
        config.main_class = LICENSE_PLATE_LABEL;
        config.crop_class = LICENSE_PLATE_LABEL;
        config.recognition_type = RECOGNIZED_LABEL;
        config.max_crops_per_frame = 4;
        config.min_width_px = 40.0f;
        config.min_height_px = 15.0f;
        config.min_relative_area = 0.001f;
        config.blur_check_enabled = false;
        config.blur_threshold = 50.0f;
        config.roi_check_enabled = true;
        // Use static rectangle in the middle of the frame
        float region_width = STATIC_ROI_XMAX - STATIC_ROI_XMIN;
        float region_height = STATIC_ROI_YMAX - STATIC_ROI_YMIN;
        config.roi_rect = HailoBBox(STATIC_ROI_XMIN, STATIC_ROI_YMIN, region_width, region_height);
        config.sort_by_confidence = true;

        cropper = std::make_unique<GenericCropper>(config); });

    return cropper->process(image, roi);
}
