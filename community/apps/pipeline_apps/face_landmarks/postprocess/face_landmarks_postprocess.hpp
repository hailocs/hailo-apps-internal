/**
 * face_landmarks_lite postprocess — converts raw tensors to HailoLandmarks.
 */
#pragma once
#include "hailo_objects.hpp"
#include "hailo_common.hpp"

__BEGIN_DECLS
void filter(HailoROIPtr roi);
void face_landmarks_postprocess(HailoROIPtr roi);
__END_DECLS
