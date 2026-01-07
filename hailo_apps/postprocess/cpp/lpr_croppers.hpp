/**
* Copyright (c) 2021-2022 Hailo Technologies Ltd. All rights reserved.
* Distributed under the LGPL license (https://www.gnu.org/licenses/old-licenses/lgpl-2.1.txt)
**/
#pragma once
#include <vector>
#include <opencv2/opencv.hpp>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>
#include <opencv2/core.hpp>
#include "hailo_objects.hpp"
#include "hailo_common.hpp"
#include "hailomat.hpp"

__BEGIN_DECLS
std::vector<HailoROIPtr> vehicles_roi_cropper(std::shared_ptr<HailoMat> image, HailoROIPtr roi);
std::vector<HailoROIPtr> license_plate_with_quality(std::shared_ptr<HailoMat> image, HailoROIPtr roi);
std::vector<HailoROIPtr> license_plate_quality_estimation(std::shared_ptr<HailoMat> image, HailoROIPtr roi);
std::vector<HailoROIPtr> license_plate_no_quality(std::shared_ptr<HailoMat> image, HailoROIPtr roi);
std::vector<HailoROIPtr> license_plate_no_quality_simple(std::shared_ptr<HailoMat> image, HailoROIPtr roi);
std::vector<HailoROIPtr> lp_simple_cropper(std::shared_ptr<HailoMat> image, HailoROIPtr roi);
std::vector<HailoROIPtr> license_plate_no_quality_two_best(std::shared_ptr<HailoMat> image, HailoROIPtr roi);
std::vector<HailoROIPtr> license_plate_no_quality_four_best(std::shared_ptr<HailoMat> image, HailoROIPtr roi);
std::vector<HailoROIPtr> license_plate_minimal(std::shared_ptr<HailoMat> image, HailoROIPtr roi);
std::vector<HailoROIPtr> license_plate_vehicle_crop(std::shared_ptr<HailoMat> image, HailoROIPtr roi);
__END_DECLS
