#ifndef GESTURE_PALM_DETECTION_HPP
#define GESTURE_PALM_DETECTION_HPP

#include <vector>
#include <opencv2/core.hpp>
#include "common_types.hpp"

// Palm detection model constants
constexpr float PALM_INPUT_SIZE = 192.0f;
constexpr int PALM_NUM_ANCHORS = 2016;
constexpr int PALM_NUM_KEYPOINTS = 7;
constexpr float PALM_SCORE_CLIPPING_THRESH = 100.0f;
constexpr float PALM_MIN_SCORE_THRESH = 0.5f;
constexpr float PALM_MIN_SUPPRESSION_THRESHOLD = 0.3f;

struct PalmPreprocessResult {
    cv::Mat padded;        // 192x192 RGB, uint8
    float inv_scale;       // inverse scale factor
    float pad_y;           // pad offset in original image coords
    float pad_x;
};

/// Pre-compute 2016 SSD anchors (cached on first call).
const std::vector<Anchor>& get_palm_anchors();

/// BGR→RGB, aspect-preserving resize, pad to 192x192.
PalmPreprocessResult preprocess_palm(const cv::Mat& rgb);

/// Decode raw float outputs from palm_detection_lite.hef.
/// score_data/box_data arrays are indexed by anchor, with sizes n_large + n_small = 2016.
std::vector<PalmDetection> decode_palm_outputs(
    const float* scores_large, size_t n_large,
    const float* scores_small, size_t n_small,
    const float* boxes_large,
    const float* boxes_small);

/// Weighted NMS (BlazeFace-style).
std::vector<PalmDetection> weighted_nms(std::vector<PalmDetection>& dets, float iou_threshold);

/// Map normalized [0,1] detection coords to original image pixel space.
void denormalize_detections(std::vector<PalmDetection>& dets,
                            float inv_scale, float pad_y, float pad_x);

#endif // GESTURE_PALM_DETECTION_HPP
