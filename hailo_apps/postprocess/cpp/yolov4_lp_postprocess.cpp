/**
 * @file yolov4_lp_postprocess.cpp
 * @brief Custom Tiny-YOLOv4 license plate detection postprocess.
 *
 * Decodes raw conv tensors from tiny_yolov4_license_plates HEF into
 * HAILO_DETECTION objects (label "license_plate"). Works with UINT8, UINT16,
 * and FLOAT32 tensor data — enabling GStreamer LP detection on Hailo-8/8L/10H.
 *
 * TAPPAS libyolo_post.so fails on H8 because it reads uint8 from uint16 data.
 * This SO correctly detects the tensor data type and reads accordingly.
 *
 * Model outputs:
 *   conv19: 13×13×18  (3 anchors × 6 attrs: tx,ty,tw,th,obj,cls)
 *   conv21: 26×26×18
 *
 * Anchors (from yolov4_license_plate.json):
 *   13×13: [81,82], [135,169], [344,319]
 *   26×26: [10,14], [23,27], [37,58]
 */
#include <algorithm>
#include <cmath>
#include <string>
#include <vector>
#include "yolov4_lp_postprocess.hpp"

// ---------------------------------------------------------------------------
// Model constants (from yolov4_license_plate.json)
// ---------------------------------------------------------------------------
static constexpr int NUM_ANCHORS = 3;
static constexpr int NUM_CLASSES = 1;      // "license_plate" (label_offset=1)
static constexpr int BOX_ATTRS = 5 + NUM_CLASSES;  // tx,ty,tw,th,obj + 1 class
static constexpr int INPUT_SIZE = 416;
static constexpr float DETECTION_THRESHOLD = 0.3f;
static constexpr float NMS_IOU_THRESHOLD = 0.45f;

// Anchors per grid scale
static const float ANCHORS_13x13[NUM_ANCHORS][2] = {
    {81.0f, 82.0f}, {135.0f, 169.0f}, {344.0f, 319.0f}
};
static const float ANCHORS_26x26[NUM_ANCHORS][2] = {
    {10.0f, 14.0f}, {23.0f, 27.0f}, {37.0f, 58.0f}
};

// ---------------------------------------------------------------------------
// Simple box structure for NMS
// ---------------------------------------------------------------------------
struct LPBox {
    float x1, y1, x2, y2, score;
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
static inline float sigmoid(float x) {
    x = std::max(-50.0f, std::min(50.0f, x));
    return 1.0f / (1.0f + std::exp(-x));
}

static float compute_iou(const LPBox &a, const LPBox &b) {
    float ix1 = std::max(a.x1, b.x1);
    float iy1 = std::max(a.y1, b.y1);
    float ix2 = std::min(a.x2, b.x2);
    float iy2 = std::min(a.y2, b.y2);
    float inter = std::max(0.0f, ix2 - ix1) * std::max(0.0f, iy2 - iy1);
    float area_a = (a.x2 - a.x1) * (a.y2 - a.y1);
    float area_b = (b.x2 - b.x1) * (b.y2 - b.y1);
    float u = area_a + area_b - inter;
    return u > 0.0f ? inter / u : 0.0f;
}

static std::vector<LPBox> nms(std::vector<LPBox> &boxes) {
    std::sort(boxes.begin(), boxes.end(),
              [](const LPBox &a, const LPBox &b) { return a.score > b.score; });
    std::vector<LPBox> keep;
    std::vector<bool> suppressed(boxes.size(), false);
    for (size_t i = 0; i < boxes.size(); ++i) {
        if (suppressed[i]) continue;
        keep.push_back(boxes[i]);
        for (size_t j = i + 1; j < boxes.size(); ++j) {
            if (!suppressed[j] && compute_iou(boxes[i], boxes[j]) >= NMS_IOU_THRESHOLD) {
                suppressed[j] = true;
            }
        }
    }
    return keep;
}

// ---------------------------------------------------------------------------
// Read a dequantized float from a tensor at (row, col, channel).
// Handles UINT8, UINT16, and FLOAT32 data types. Assumes NHWC memory layout
// (which hailonet provides by default via FCR→NHWC transform).
//
// When qp_scale=0 and qp_zp=0, the HEF uses per-channel quantization and the
// single-QP metadata is invalid (sentinel INVALID_QP_VALUE=0). If the hailonet
// element was configured with output-format-type=HAILO_FORMAT_TYPE_FLOAT32,
// data is already dequantized float32 even though metadata may still report
// UINT16. We detect this via the invalid-QP sentinel and read as float32.
// ---------------------------------------------------------------------------
static float read_tensor_value(HailoTensorPtr &tensor, uint row, uint col, uint channel) {
    auto fmt = tensor->format();
    auto qinfo = tensor->quant_info();

    // Float32 format, or invalid QP (per-channel quant, data already dequantized by hailonet)
    bool is_float = (fmt.type == HailoTensorFormatType::HAILO_FORMAT_TYPE_FLOAT32) ||
                    (qinfo.qp_scale == 0.0f && qinfo.qp_zp == 0.0f);

    if (is_float) {
        // Already dequantized float32 — read directly with NHWC indexing
        float *fdata = reinterpret_cast<float *>(tensor->data());
        uint w = tensor->width();
        uint f = tensor->features();
        uint pos = (w * f) * row + f * col + channel;
        return fdata[pos];
    } else if (fmt.type == HailoTensorFormatType::HAILO_FORMAT_TYPE_UINT16) {
        return tensor->get_full_percision(row, col, channel, /*is_uint16=*/true);
    } else {
        // UINT8 or AUTO — treat as uint8
        return tensor->get_full_percision(row, col, channel, /*is_uint16=*/false);
    }
}

// ---------------------------------------------------------------------------
// Decode one tensor grid into bounding boxes
// ---------------------------------------------------------------------------
static void decode_tensor(HailoTensorPtr &tensor, const float anchors[][2],
                          std::vector<LPBox> &boxes) {
    int grid_h = static_cast<int>(tensor->height());
    int grid_w = static_cast<int>(tensor->width());

    for (int row = 0; row < grid_h; ++row) {
        for (int col = 0; col < grid_w; ++col) {
            for (int a = 0; a < NUM_ANCHORS; ++a) {
                int ch = a * BOX_ATTRS;

                float obj = sigmoid(read_tensor_value(tensor, row, col, ch + 4));
                if (obj < DETECTION_THRESHOLD) continue;

                float cls_score = sigmoid(read_tensor_value(tensor, row, col, ch + 5));
                float score = obj * cls_score;
                if (score < DETECTION_THRESHOLD) continue;

                float tx = read_tensor_value(tensor, row, col, ch + 0);
                float ty = read_tensor_value(tensor, row, col, ch + 1);
                float tw = read_tensor_value(tensor, row, col, ch + 2);
                float th = read_tensor_value(tensor, row, col, ch + 3);

                float cx = (sigmoid(tx) + static_cast<float>(col)) / static_cast<float>(grid_w);
                float cy = (sigmoid(ty) + static_cast<float>(row)) / static_cast<float>(grid_h);
                float bw = (std::exp(tw) * anchors[a][0]) / static_cast<float>(INPUT_SIZE);
                float bh = (std::exp(th) * anchors[a][1]) / static_cast<float>(INPUT_SIZE);

                LPBox box;
                box.x1 = cx - bw / 2.0f;
                box.y1 = cy - bh / 2.0f;
                box.x2 = cx + bw / 2.0f;
                box.y2 = cy + bh / 2.0f;
                box.score = score;
                boxes.push_back(box);
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Main postprocess entry point — called by hailofilter
// ---------------------------------------------------------------------------
void tiny_yolov4_license_plates(HailoROIPtr roi) {
    if (!roi->has_tensors()) {
        return;
    }

    auto tensors = roi->get_tensors();

    // Decode all tensor grids
    std::vector<LPBox> all_boxes;
    for (auto &tensor : tensors) {
        int h = static_cast<int>(tensor->height());
        int w = static_cast<int>(tensor->width());
        if (h == 13 && w == 13) {
            decode_tensor(tensor, ANCHORS_13x13, all_boxes);
        } else if (h == 26 && w == 26) {
            decode_tensor(tensor, ANCHORS_26x26, all_boxes);
        }
        // else: skip unknown tensor shapes
    }

    // NMS
    auto kept = nms(all_boxes);

    // Add detections to ROI
    std::vector<HailoDetection> detections;
    detections.reserve(kept.size());
    for (auto &box : kept) {
        // Clamp to [0, 1]
        float x1 = std::max(0.0f, std::min(1.0f, box.x1));
        float y1 = std::max(0.0f, std::min(1.0f, box.y1));
        float x2 = std::max(0.0f, std::min(1.0f, box.x2));
        float y2 = std::max(0.0f, std::min(1.0f, box.y2));
        float w = x2 - x1;
        float h = y2 - y1;
        if (w <= 0.0f || h <= 0.0f) continue;
        HailoBBox bbox(x1, y1, w, h);
        detections.emplace_back(HailoDetection(bbox, 1, "license_plate", box.score));
    }
    hailo_common::add_detections(roi, detections);
}
