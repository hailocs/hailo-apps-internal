/**
 * Copyright (c) 2021-2022 Hailo Technologies Ltd. All rights reserved.
 * Distributed under the LGPL license (https://www.gnu.org/licenses/old-licenses/lgpl-2.1.txt)
 *
 * Palm detection postprocess for palm_detection_lite.hef (192x192).
 * Ports SSD anchor decode + weighted NMS from blaze_base.py.
 **/
#include <vector>
#include <algorithm>
#include <cmath>
#include <cstring>
#include "common/tensors.hpp"
#include "common/math.hpp"
#include "palm_detection_postprocess.hpp"
#include "hailo_xtensor.hpp"
#include "xtensor/xadapt.hpp"
#include "xtensor/xarray.hpp"

// Palm detection model constants (from blaze_base.py PALM_ANCHOR_OPTIONS / PALM_MODEL_CONFIG)
#define INPUT_SIZE 192.0f
#define NUM_ANCHORS 2016
#define NUM_COORDS 18       // 4 box coords + 7 keypoints * 2
#define NUM_KEYPOINTS 7
#define SCORE_CLIPPING_THRESH 100.0f
#define MIN_SCORE_THRESH 0.5f
#define MIN_SUPPRESSION_THRESHOLD 0.3f

// Anchor generation parameters
static const int STRIDES[] = {8, 16, 16, 16};
static const int NUM_LAYERS = 4;

struct Anchor {
    float x_center;
    float y_center;
    float w;
    float h;
};

/**
 * @brief Pre-compute 2016 SSD anchors (same as blaze_base.generate_anchors).
 * Called once, result cached in static vector.
 */
static std::vector<Anchor> generate_anchors()
{
    std::vector<Anchor> anchors;
    anchors.reserve(NUM_ANCHORS);

    int layer_id = 0;
    while (layer_id < NUM_LAYERS)
    {
        int last_same = layer_id;
        int num_anchors_per_cell = 0;

        while (last_same < NUM_LAYERS && STRIDES[last_same] == STRIDES[layer_id])
        {
            // Each layer contributes 2 anchors per cell:
            // 1 for aspect_ratio=1.0 at the layer's scale
            // 1 for interpolated_scale_aspect_ratio=1.0
            num_anchors_per_cell += 2;
            last_same++;
        }

        int stride = STRIDES[layer_id];
        int feature_map_h = static_cast<int>(std::ceil(192.0f / stride));
        int feature_map_w = static_cast<int>(std::ceil(192.0f / stride));

        for (int y = 0; y < feature_map_h; y++)
        {
            for (int x = 0; x < feature_map_w; x++)
            {
                float x_center = (x + 0.5f) / feature_map_w;
                float y_center = (y + 0.5f) / feature_map_h;
                for (int a = 0; a < num_anchors_per_cell; a++)
                {
                    // fixed_anchor_size = True → w=1.0, h=1.0
                    anchors.push_back({x_center, y_center, 1.0f, 1.0f});
                }
            }
        }

        layer_id = last_same;
    }

    return anchors;
}

static const std::vector<Anchor> &get_anchors()
{
    static std::vector<Anchor> anchors = generate_anchors();
    return anchors;
}

static float compute_iou(const float *box_a, const float *box_b)
{
    float y1 = std::max(box_a[0], box_b[0]);
    float x1 = std::max(box_a[1], box_b[1]);
    float y2 = std::min(box_a[2], box_b[2]);
    float x2 = std::min(box_a[3], box_b[3]);

    float intersection = std::max(0.0f, y2 - y1) * std::max(0.0f, x2 - x1);
    float area_a = (box_a[2] - box_a[0]) * (box_a[3] - box_a[1]);
    float area_b = (box_b[2] - box_b[0]) * (box_b[3] - box_b[1]);
    float union_area = area_a + area_b - intersection;

    return (union_area > 1e-6f) ? intersection / union_area : 0.0f;
}

struct Detection {
    float coords[NUM_COORDS]; // [ymin, xmin, ymax, xmax, kp0_x, kp0_y, ..., kp6_x, kp6_y]
    float score;
};

/**
 * @brief Weighted NMS (BlazeFace-style).
 * Instead of discarding overlapping detections, takes weighted average.
 */
static std::vector<Detection> weighted_nms(std::vector<Detection> &dets, float iou_threshold)
{
    if (dets.empty())
        return {};

    std::sort(dets.begin(), dets.end(),
              [](const Detection &a, const Detection &b) { return a.score > b.score; });

    std::vector<Detection> output;
    std::vector<bool> used(dets.size(), false);

    for (size_t i = 0; i < dets.size(); i++)
    {
        if (used[i])
            continue;

        std::vector<size_t> overlapping;
        overlapping.push_back(i);

        for (size_t j = i + 1; j < dets.size(); j++)
        {
            if (used[j])
                continue;
            float iou = compute_iou(dets[i].coords, dets[j].coords);
            if (iou > iou_threshold)
            {
                overlapping.push_back(j);
                used[j] = true;
            }
        }
        used[i] = true;

        Detection merged;
        merged.score = dets[i].score;
        float weight_sum = 0.0f;
        std::memset(merged.coords, 0, sizeof(merged.coords));

        for (size_t idx : overlapping)
        {
            float w = dets[idx].score;
            weight_sum += w;
            for (int c = 0; c < NUM_COORDS; c++)
                merged.coords[c] += dets[idx].coords[c] * w;
        }

        for (int c = 0; c < NUM_COORDS; c++)
            merged.coords[c] /= weight_sum;

        output.push_back(merged);
    }

    return output;
}

/**
 * @brief Main postprocess: decode palm detections from model output tensors.
 */
void palm_detection_postprocess(HailoROIPtr roi)
{
    if (!roi->has_tensors())
        return;

    auto tensors = roi->get_tensors();

    // Separate score tensors (total < 2016) from box tensors (total >= 2016)
    // Expected:
    //   scores: conv29 (24,24,2)=1152, conv24 (12,12,6)=864 → total 2016
    //   boxes:  conv30 (24,24,36)=20736, conv25 (12,12,108)=15552
    std::vector<HailoTensorPtr> score_tensors;
    std::vector<HailoTensorPtr> box_tensors;

    for (auto &t : tensors)
    {
        size_t total = t->width() * t->height() * t->features();
        if (total < NUM_ANCHORS)
            score_tensors.push_back(t);
        else
            box_tensors.push_back(t);
    }

    if (score_tensors.size() < 2 || box_tensors.size() < 2)
        return;

    // Sort by total size descending (large layer first)
    auto sort_by_size = [](const HailoTensorPtr &a, const HailoTensorPtr &b) {
        return (a->width() * a->height() * a->features()) > (b->width() * b->height() * b->features());
    };
    std::sort(score_tensors.begin(), score_tensors.end(), sort_by_size);
    std::sort(box_tensors.begin(), box_tensors.end(), sort_by_size);

    // Dequantize tensors to flat float arrays
    auto scores_large_xt = common::get_xtensor_float(score_tensors[0]); // 1152 scores
    auto scores_small_xt = common::get_xtensor_float(score_tensors[1]); // 864 scores
    auto boxes_large_xt = common::get_xtensor_float(box_tensors[0]);    // 1152 * 18
    auto boxes_small_xt = common::get_xtensor_float(box_tensors[1]);    // 864 * 18

    size_t n_large = scores_large_xt.size();
    size_t n_small = scores_small_xt.size();
    size_t total_anchors = n_large + n_small;

    if (total_anchors != NUM_ANCHORS)
        return;

    // Access flat data pointers for direct indexing
    const float *scores_large = scores_large_xt.data();
    const float *scores_small = scores_small_xt.data();
    const float *boxes_large = boxes_large_xt.data();
    const float *boxes_small = boxes_small_xt.data();

    const auto &anchors = get_anchors();

    // Decode boxes and filter by score in one pass
    std::vector<Detection> detections;

    for (size_t i = 0; i < total_anchors; i++)
    {
        // Get raw score
        float raw_score;
        if (i < n_large)
            raw_score = scores_large[i];
        else
            raw_score = scores_small[i - n_large];

        // Clip and sigmoid
        raw_score = std::max(-SCORE_CLIPPING_THRESH, std::min(SCORE_CLIPPING_THRESH, raw_score));
        float score = 1.0f / (1.0f + std::exp(-raw_score));

        if (score < MIN_SCORE_THRESH)
            continue;

        // Get raw box coords (NUM_COORDS values per anchor)
        const float *raw_box;
        if (i < n_large)
            raw_box = boxes_large + i * NUM_COORDS;
        else
            raw_box = boxes_small + (i - n_large) * NUM_COORDS;

        // Decode box relative to anchor (same as blaze_base.decode_boxes)
        float x_center = raw_box[0] / INPUT_SIZE * anchors[i].w + anchors[i].x_center;
        float y_center = raw_box[1] / INPUT_SIZE * anchors[i].h + anchors[i].y_center;
        float w = raw_box[2] / INPUT_SIZE * anchors[i].w;
        float h = raw_box[3] / INPUT_SIZE * anchors[i].h;

        Detection det;
        det.score = score;
        det.coords[0] = y_center - h / 2.0f; // ymin
        det.coords[1] = x_center - w / 2.0f; // xmin
        det.coords[2] = y_center + h / 2.0f; // ymax
        det.coords[3] = x_center + w / 2.0f; // xmax

        // Decode keypoints
        for (int k = 0; k < NUM_KEYPOINTS; k++)
        {
            int offset = 4 + k * 2;
            float kp_x = raw_box[offset] / INPUT_SIZE * anchors[i].w + anchors[i].x_center;
            float kp_y = raw_box[offset + 1] / INPUT_SIZE * anchors[i].h + anchors[i].y_center;
            det.coords[offset] = kp_x;
            det.coords[offset + 1] = kp_y;
        }

        detections.push_back(det);
    }

    // Weighted NMS
    auto nms_dets = weighted_nms(detections, MIN_SUPPRESSION_THRESHOLD);

    // Create HailoDetection objects
    auto clamp01 = [](float v) { return std::max(0.0f, std::min(1.0f, v)); };

    for (auto &det : nms_dets)
    {
        float ymin = clamp01(det.coords[0]);
        float xmin = clamp01(det.coords[1]);
        float ymax = clamp01(det.coords[2]);
        float xmax = clamp01(det.coords[3]);

        float w = xmax - xmin;
        float h = ymax - ymin;
        if (w < 0.01f || h < 0.01f)
            continue;

        HailoBBox bbox(xmin, ymin, w, h);
        auto detection = std::make_shared<HailoDetection>(bbox, "palm", det.score);

        // Add 7 keypoints as landmarks (bbox-relative [0,1])
        // HailoLandmarks convention: points are relative to parent detection bbox.
        // This is critical for correct coordinate handling through hailoaggregator,
        // which transforms detection bboxes but not landmarks within them.
        std::vector<HailoPoint> keypoints;
        keypoints.reserve(NUM_KEYPOINTS);
        for (int k = 0; k < NUM_KEYPOINTS; k++)
        {
            int offset = 4 + k * 2;
            float kp_x_abs = clamp01(det.coords[offset]);
            float kp_y_abs = clamp01(det.coords[offset + 1]);
            // Convert from absolute model-normalized to bbox-relative
            float kp_x_rel = (w > 1e-6f) ? (kp_x_abs - xmin) / w : 0.5f;
            float kp_y_rel = (h > 1e-6f) ? (kp_y_abs - ymin) / h : 0.5f;
            keypoints.emplace_back(kp_x_rel, kp_y_rel, 1.0f);
        }

        std::vector<std::pair<int, int>> no_pairs;
        auto landmarks = std::make_shared<HailoLandmarks>("palm_kps", keypoints, 0.0f, no_pairs);
        detection->add_object(landmarks);

        roi->add_object(detection);
    }
}

void filter(HailoROIPtr roi)
{
    palm_detection_postprocess(roi);
}
