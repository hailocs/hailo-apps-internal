/**
 * Person-to-palm cropper for hailocropper element.
 * Creates square crop regions around detected persons for palm detection.
 * Each person gets a zoomed-in view instead of squeezing the whole frame.
 */
#pragma once
#include <vector>
#include "hailo_objects.hpp"
#include "hailo_common.hpp"
#include "hailomat.hpp"

__BEGIN_DECLS
std::vector<HailoROIPtr> person_palm_crop(std::shared_ptr<HailoMat> image, HailoROIPtr roi);
__END_DECLS
