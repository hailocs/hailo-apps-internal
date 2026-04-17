/**
 * Palm detection preprocessing, anchor decode, weighted NMS, and denormalization.
 * Ports blaze_base.py + palm_detection_postprocess.cpp to standalone C++ (no xtensor/TAPPAS).
 */
#include "palm_detection.hpp"
#include <algorithm>
#include <cmath>
#include <cstring>
#include <opencv2/imgproc.hpp>

// Anchor generation parameters
static const int STRIDES[] = {8, 16, 16, 16};
static const int NUM_LAYERS = 4;

static std::vector<Anchor> generate_anchors()
{
    std::vector<Anchor> anchors;
    anchors.reserve(PALM_NUM_ANCHORS);

    int layer_id = 0;
    while (layer_id < NUM_LAYERS)
    {
        int last_same = layer_id;
        int num_anchors_per_cell = 0;

        while (last_same < NUM_LAYERS && STRIDES[last_same] == STRIDES[layer_id])
        {
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
                    anchors.push_back({x_center, y_center, 1.0f, 1.0f});
                }
            }
        }

        layer_id = last_same;
    }

    return anchors;
}

const std::vector<Anchor>& get_palm_anchors()
{
    static std::vector<Anchor> anchors = generate_anchors();
    return anchors;
}

PalmPreprocessResult preprocess_palm(const cv::Mat& rgb)
{
    // Aspect-preserving resize + pad to 192x192 (matches blaze_base.resize_pad)
    int h = rgb.rows, w = rgb.cols;
    float th = PALM_INPUT_SIZE, tw = PALM_INPUT_SIZE;

    float scale = std::min(th / h, tw / w);
    int new_h = static_cast<int>(h * scale);
    int new_w = static_cast<int>(w * scale);

    cv::Mat resized;
    cv::resize(rgb, resized, cv::Size(new_w, new_h));

    int pad_h = (static_cast<int>(th) - new_h) / 2;
    int pad_w = (static_cast<int>(tw) - new_w) / 2;

    cv::Mat padded = cv::Mat::zeros(static_cast<int>(th), static_cast<int>(tw), rgb.type());
    resized.copyTo(padded(cv::Rect(pad_w, pad_h, new_w, new_h)));

    float inv_scale = 1.0f / scale;
    float pad_orig_y = pad_h * inv_scale;
    float pad_orig_x = pad_w * inv_scale;

    return {padded, inv_scale, pad_orig_y, pad_orig_x};
}

static float compute_iou(const float* box_a, const float* box_b)
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

std::vector<PalmDetection> decode_palm_outputs(
    const float* scores_large, size_t n_large,
    const float* scores_small, size_t n_small,
    const float* boxes_large,
    const float* boxes_small)
{
    size_t total_anchors = n_large + n_small;
    if (total_anchors != PALM_NUM_ANCHORS)
        return {};

    const auto& anchors = get_palm_anchors();
    std::vector<PalmDetection> detections;

    for (size_t i = 0; i < total_anchors; i++)
    {
        float raw_score;
        if (i < n_large)
            raw_score = scores_large[i];
        else
            raw_score = scores_small[i - n_large];

        raw_score = std::max(-PALM_SCORE_CLIPPING_THRESH,
                             std::min(PALM_SCORE_CLIPPING_THRESH, raw_score));
        float score = 1.0f / (1.0f + std::exp(-raw_score));

        if (score < PALM_MIN_SCORE_THRESH)
            continue;

        const float* raw_box;
        if (i < n_large)
            raw_box = boxes_large + i * PalmDetection::NUM_COORDS;
        else
            raw_box = boxes_small + (i - n_large) * PalmDetection::NUM_COORDS;

        // Decode box relative to anchor (same as blaze_base.decode_boxes)
        float x_center = raw_box[0] / PALM_INPUT_SIZE * anchors[i].w + anchors[i].x_center;
        float y_center = raw_box[1] / PALM_INPUT_SIZE * anchors[i].h + anchors[i].y_center;
        float w = raw_box[2] / PALM_INPUT_SIZE * anchors[i].w;
        float h = raw_box[3] / PALM_INPUT_SIZE * anchors[i].h;

        PalmDetection det;
        det.score = score;
        det.coords[0] = y_center - h / 2.0f; // ymin
        det.coords[1] = x_center - w / 2.0f; // xmin
        det.coords[2] = y_center + h / 2.0f; // ymax
        det.coords[3] = x_center + w / 2.0f; // xmax

        for (int k = 0; k < PALM_NUM_KEYPOINTS; k++)
        {
            int offset = 4 + k * 2;
            float kp_x = raw_box[offset] / PALM_INPUT_SIZE * anchors[i].w + anchors[i].x_center;
            float kp_y = raw_box[offset + 1] / PALM_INPUT_SIZE * anchors[i].h + anchors[i].y_center;
            det.coords[offset] = kp_x;
            det.coords[offset + 1] = kp_y;
        }

        detections.push_back(det);
    }

    return detections;
}

std::vector<PalmDetection> weighted_nms(std::vector<PalmDetection>& dets, float iou_threshold)
{
    if (dets.empty())
        return {};

    std::sort(dets.begin(), dets.end(),
              [](const PalmDetection& a, const PalmDetection& b) { return a.score > b.score; });

    std::vector<PalmDetection> output;
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

        PalmDetection merged;
        merged.score = dets[i].score;
        float weight_sum = 0.0f;
        std::memset(merged.coords, 0, sizeof(merged.coords));

        for (size_t idx : overlapping)
        {
            float w = dets[idx].score;
            weight_sum += w;
            for (int c = 0; c < PalmDetection::NUM_COORDS; c++)
                merged.coords[c] += dets[idx].coords[c] * w;
        }

        for (int c = 0; c < PalmDetection::NUM_COORDS; c++)
            merged.coords[c] /= weight_sum;

        output.push_back(merged);
    }

    return output;
}

void denormalize_detections(std::vector<PalmDetection>& dets,
                            float inv_scale, float pad_y, float pad_x)
{
    // Matches blaze_base.denormalize_detections:
    // coord_pixel = coord_norm * inv_scale * model_size - pad
    float s = inv_scale * PALM_INPUT_SIZE;

    for (auto& det : dets)
    {
        // Box: [ymin, xmin, ymax, xmax]
        det.coords[0] = det.coords[0] * s - pad_y;  // ymin
        det.coords[1] = det.coords[1] * s - pad_x;  // xmin
        det.coords[2] = det.coords[2] * s - pad_y;  // ymax
        det.coords[3] = det.coords[3] * s - pad_x;  // xmax

        // Keypoints: alternating x, y starting at index 4
        for (int k = 0; k < PALM_NUM_KEYPOINTS; k++)
        {
            int offset = 4 + k * 2;
            det.coords[offset] = det.coords[offset] * s - pad_x;         // x
            det.coords[offset + 1] = det.coords[offset + 1] * s - pad_y; // y
        }
    }
}
