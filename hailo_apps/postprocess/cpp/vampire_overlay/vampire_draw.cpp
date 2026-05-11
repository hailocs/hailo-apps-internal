/**
 * Copyright (c) 2026 Hailo Technologies Ltd. All rights reserved.
 * Distributed under the LGPL license.
 *
 * draw_vampires - C++ port of the Python vampire compositing logic.
 * For each detection tagged with a HailoClassification of the configured
 * type ("vampire" by default), the segmentation mask is resized to the
 * detection bbox, dilated, and the corresponding region of the shared
 * background buffer is copied into the frame.
 */
#include "vampire_draw.hpp"

#include <algorithm>
#include <opencv2/imgproc.hpp>

namespace {

bool detection_is_vampire(const HailoDetectionPtr &det, const std::string &type)
{
    for (const auto &obj : det->get_objects_typed(HAILO_CLASSIFICATION)) {
        auto cls = std::dynamic_pointer_cast<HailoClassification>(obj);
        if (cls && cls->get_classification_type() == type) return true;
    }
    return false;
}

}  // namespace

int draw_vampires(cv::Mat &frame, HailoROIPtr roi, const VampireDrawParams &p)
{
    if (!p.bg || p.bg->empty()) return 0;
    const cv::Mat &bg = *p.bg;
    if (bg.size() != frame.size() || bg.type() != frame.type()) return 0;

    // Precompute the dilation kernel once per call.
    const cv::Mat kernel = cv::getStructuringElement(
        cv::MORPH_ELLIPSE,
        cv::Size(std::max(1, p.dilate_radius), std::max(1, p.dilate_radius)));

    int drawn = 0;

    for (const auto &obj : roi->get_objects_typed(HAILO_DETECTION)) {
        auto det = std::dynamic_pointer_cast<HailoDetection>(obj);
        if (!det) continue;
        if (det->get_label() != "person") continue;
        if (!detection_is_vampire(det, p.vampire_classification_type)) continue;

        auto bbox = det->get_bbox();
        int px1 = std::max((int)(bbox.xmin() * frame.cols), 0);
        int py1 = std::max((int)(bbox.ymin() * frame.rows), 0);
        int px2 = std::min((int)((bbox.xmin() + bbox.width())  * frame.cols), frame.cols);
        int py2 = std::min((int)((bbox.ymin() + bbox.height()) * frame.rows), frame.rows);
        if (px2 <= px1 || py2 <= py1) continue;

        const cv::Rect rect(px1, py1, px2 - px1, py2 - py1);

        auto masks = det->get_objects_typed(HAILO_CONF_CLASS_MASK);
        if (masks.empty()) {
            // No mask available — fall back to filling the bbox with bg pixels.
            bg(rect).copyTo(frame(rect));
            ++drawn;
            continue;
        }
        auto mask = std::dynamic_pointer_cast<HailoConfClassMask>(masks[0]);
        if (!mask) continue;

        // The mask data is float in [0,1] at the model's native mask resolution
        // (e.g. 160x160 for yolov5m_seg).
        const std::vector<float> &mdata = mask->get_data();
        const int mh = (int)mask->get_height();
        const int mw = (int)mask->get_width();
        if (mh <= 0 || mw <= 0 || (int)mdata.size() < mh * mw) continue;

        // Wrap the raw mask data without copying. const_cast is safe because
        // cv::resize only reads its input.
        cv::Mat mask_src(mh, mw, CV_32F, const_cast<float*>(mdata.data()));
        cv::Mat resized;
        cv::resize(mask_src, resized, rect.size(), 0, 0, cv::INTER_LINEAR);

        // Threshold + dilate to a binary uint8 mask.
        cv::Mat binary = (resized > 0.5f);  // CV_8U, 0 or 255
        cv::dilate(binary, binary, kernel, cv::Point(-1, -1),
                   std::max(0, p.dilate_iterations));

        // Copy bg pixels into the frame where the mask is non-zero.
        bg(rect).copyTo(frame(rect), binary);
        ++drawn;
    }
    return drawn;
}
