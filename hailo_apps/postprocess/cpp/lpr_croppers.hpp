/**
 * Copyright (c) 2021-2022 Hailo Technologies Ltd. All rights reserved.
 * Distributed under the LGPL license (https://www.gnu.org/licenses/old-licenses/lgpl-2.1.txt)
 **/
#pragma once
#include <vector>
#include <memory>
#include "hailo_objects.hpp"
#include "hailo_common.hpp"
#include "hailomat.hpp"

__BEGIN_DECLS

/**
 * @brief License plate cropper for LPR pipeline.
 *        Uses GenericCropper to select license plates for OCR.
 */
std::vector<HailoROIPtr> license_plate_cropper(std::shared_ptr<HailoMat> image, HailoROIPtr roi);

__END_DECLS
