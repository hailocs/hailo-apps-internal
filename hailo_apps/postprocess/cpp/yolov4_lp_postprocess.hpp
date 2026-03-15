/**
 * @file yolov4_lp_postprocess.hpp
 * @brief Custom Tiny-YOLOv4 license plate detection postprocess.
 *
 * Replaces TAPPAS libyolo_post.so::tiny_yolov4_license_plates which fails on
 * Hailo-8/8L because it reads UINT8 from UINT16 tensor data. This SO handles
 * UINT8, UINT16, and FLOAT32 tensor formats correctly, making it work across
 * all Hailo architectures (H8, H8L, H10H).
 */
#pragma once
#include "hailo_objects.hpp"
#include "hailo_common.hpp"

__BEGIN_DECLS
void tiny_yolov4_license_plates(HailoROIPtr roi);
__END_DECLS
