#ifndef GESTURE_HAND_LANDMARK_HPP
#define GESTURE_HAND_LANDMARK_HPP

#include <vector>
#include <opencv2/core.hpp>
#include "common_types.hpp"

constexpr float HAND_LANDMARK_INPUT_SIZE = 224.0f;
constexpr float HAND_FLAG_THRESHOLD = 0.5f;

// detection2roi parameters (from blaze_base.py PALM_MODEL_CONFIG)
constexpr int ROI_KP1 = 0;    // wrist center
constexpr int ROI_KP2 = 2;    // middle finger base
constexpr float ROI_THETA0 = static_cast<float>(M_PI / 2.0);
constexpr float ROI_DSCALE = 2.6f;
constexpr float ROI_DY = -0.5f;

/// Convert palm detection to oriented hand ROI.
/// Detection coords must be in image pixel space (after denormalize_detections).
HandROI detection2roi(const PalmDetection& det);

/// Extract oriented ROI crop from frame using affine warp.
/// Returns 224x224 float32 [0,1] normalized RGB crop.
/// Also stores inv_affine in roi.
cv::Mat extract_roi(const cv::Mat& rgb, HandROI& roi);

/// Decode hand landmark model outputs.
/// Returns HandResult with landmarks in crop [0,224] space, flag (sigmoid), handedness.
HandResult decode_hand_outputs(
    const float* landmarks_data, size_t landmarks_size,
    const float* flag_data,
    const float* handedness_data);

/// Map landmarks from crop space to original image pixels using inv_affine.
void denormalize_landmarks(HandResult& result, const cv::Mat& inv_affine);

#endif // GESTURE_HAND_LANDMARK_HPP
