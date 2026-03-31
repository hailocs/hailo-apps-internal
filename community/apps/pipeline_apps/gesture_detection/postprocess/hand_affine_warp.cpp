/**
 * Copyright (c) 2021-2022 Hailo Technologies Ltd. All rights reserved.
 * Distributed under the LGPL license (https://www.gnu.org/licenses/old-licenses/lgpl-2.1.txt)
 *
 * Hand affine warp filter for hailofilter with use-gst-buffer=true.
 * Applies rotation + zoom correction to the hand crop buffer in-place.
 *
 * The crop buffer is an axis-aligned bounding box (AABB) that encloses a
 * rotated square region. The AABB is `expand = |cos θ| + |sin θ|` times
 * larger than the actual content. This filter:
 * 1. Zooms in on the rotated square content (compensating for AABB padding)
 * 2. Rotates to straighten the hand
 * Both are combined in a single affine transform, matching blaze_base.extract_roi.
 **/
#include <gst/video/video.h>
#include <cmath>
#include <string>

#include "hand_affine_warp.hpp"
#include "hailo_common.hpp"
#include "image.hpp"

#include <opencv2/opencv.hpp>
#include <opencv2/imgproc.hpp>
#include <opencv2/core.hpp>

static float get_palm_angle(HailoROIPtr roi)
{
    auto classifications = roi->get_objects_typed(HAILO_CLASSIFICATION);
    for (auto &cls_obj : classifications)
    {
        auto cls = std::dynamic_pointer_cast<HailoClassification>(cls_obj);
        if (cls && cls->get_classification_type() == "palm_angle")
        {
            try {
                return std::stof(cls->get_label());
            } catch (...) {
                return 0.0f;
            }
        }
    }
    return 0.0f;
}

/**
 * @brief Compute the affine warp matrix that rotates + zooms the crop.
 *
 * The crop is an AABB with expand = |cos θ| + |sin θ| padding factor.
 * The actual rotated square content occupies 1/expand of the buffer.
 * The source points span the rotated square (not the full buffer),
 * so the warp zooms in and straightens simultaneously.
 *
 * This matches blaze_base.extract_roi's single-step affine warp.
 */
static cv::Mat compute_warp_matrix(int width, int height, float theta)
{
    float cx = width / 2.0f;
    float cy = height / 2.0f;

    // Fixed expand = sqrt(2), matching palm_croppers.cpp which uses a fixed
    // maximum expansion so the crop size doesn't depend on rotation.
    static const float expand = 1.41421356f; // sqrt(2)

    // Source points: the rotated square content inscribed in the AABB.
    // half_content_* is the half-size of the actual content in pixel coords.
    float half_content_w = (width / 2.0f) / expand;
    float half_content_h = (height / 2.0f) / expand;

    float cos_t = std::cos(theta);
    float sin_t = std::sin(theta);

    // Source: center and two axis endpoints of the rotated content
    cv::Point2f src[3];
    src[0] = cv::Point2f(cx, cy);
    src[1] = cv::Point2f(cx + half_content_w * cos_t, cy + half_content_w * sin_t);
    src[2] = cv::Point2f(cx - half_content_h * sin_t, cy + half_content_h * cos_t);

    // Destination: fill the full output buffer
    cv::Point2f dst[3];
    dst[0] = cv::Point2f(cx, cy);
    dst[1] = cv::Point2f((float)width, cy);
    dst[2] = cv::Point2f(cx, (float)height);

    return cv::getAffineTransform(src, dst);
}

void filter(HailoROIPtr roi, GstVideoFrame *frame, gchar *current_stream_id)
{
    float theta = get_palm_angle(roi);

    // Skip warp if angle is negligible
    if (std::abs(theta) < 0.01f)
        return;

    cv::Mat image = get_mat_from_gst_frame(frame);
    int width = image.cols;
    int height = image.rows;

    GstVideoInfo *info = &frame->info;
    switch (info->finfo->format)
    {
    case GST_VIDEO_FORMAT_RGBA:
    case GST_VIDEO_FORMAT_RGB:
    {
        cv::Mat warp_mat = compute_warp_matrix(width, height, theta);
        cv::warpAffine(image, image, warp_mat, image.size());
        break;
    }
    case GST_VIDEO_FORMAT_NV12:
    {
        cv::Mat y_mat = cv::Mat(height * 2 / 3, width, CV_8UC1, (char *)image.data, width);
        cv::Mat uv_mat = cv::Mat(height / 3, width / 2, CV_8UC2,
                                 (char *)image.data + ((height * 2 / 3) * width), width);

        cv::Mat warp_mat = compute_warp_matrix(y_mat.cols, y_mat.rows, theta);
        cv::warpAffine(y_mat, y_mat, warp_mat, y_mat.size());

        warp_mat.at<double>(0, 2) = warp_mat.at<double>(0, 2) / 2;
        warp_mat.at<double>(1, 2) = warp_mat.at<double>(1, 2) / 2;
        cv::warpAffine(uv_mat, uv_mat, warp_mat, uv_mat.size(), cv::INTER_LINEAR);
        break;
    }
    default:
        break;
    }
}
