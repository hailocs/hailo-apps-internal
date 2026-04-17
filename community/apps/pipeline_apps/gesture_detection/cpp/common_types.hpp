#ifndef GESTURE_COMMON_TYPES_HPP
#define GESTURE_COMMON_TYPES_HPP

#include <array>
#include <string>
#include <vector>
#include <opencv2/core.hpp>

struct Anchor {
    float x_center;
    float y_center;
    float w;
    float h;
};

struct PalmDetection {
    // coords[0..3] = ymin, xmin, ymax, xmax (in normalized [0,1] or pixel space)
    // coords[4..17] = 7 keypoints, alternating x, y
    static constexpr int NUM_COORDS = 18;
    float coords[NUM_COORDS];
    float score;
};

struct HandROI {
    float xc;       // center x in image pixels
    float yc;       // center y in image pixels
    float scale;    // ROI size in pixels
    float theta;    // rotation angle
    cv::Mat inv_affine;  // 2x3 inverse affine matrix (crop → image)
};

struct HandResult {
    float flag;                    // hand presence confidence (after sigmoid)
    float landmarks[21][3];        // 21 landmarks, each (x, y, z) in image pixels
    float handedness;              // >0.5 = left hand
    std::string gesture;           // classified gesture label
};

#endif // GESTURE_COMMON_TYPES_HPP
