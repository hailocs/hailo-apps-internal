#pragma once
#include <opencv2/core.hpp>
#include "hailo_objects.hpp"
#include <string>

struct VampireDrawParams {
    const cv::Mat *bg;
    std::string   vampire_classification_type;
    int           dilate_radius;
    int           dilate_iterations;
};

int draw_vampires(cv::Mat &frame, HailoROIPtr roi, const VampireDrawParams &p);
