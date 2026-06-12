/**
 * Copyright (c) 2026 Hailo Technologies Ltd. All rights reserved.
 * Distributed under the LGPL license.
 */
#pragma once

#include <opencv2/core.hpp>
#include "hailo_objects.hpp"
#include <string>

struct VampireDrawParams {
    const cv::Mat *bg;                              // CV_8UC3, same size as frame
    std::string   vampire_classification_type;     // e.g. "vampire"
    int           dilate_radius;                    // e.g. 15
    int           dilate_iterations;                // e.g. 2
};

// Returns the number of detections drawn (zero if none tagged).
int draw_vampires(cv::Mat &frame, HailoROIPtr roi, const VampireDrawParams &p);
