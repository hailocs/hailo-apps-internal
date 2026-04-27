/**
 * face_mesh_align — rotation-aware face alignment for face_landmarks_lite.
 *
 * Runs as a hailofilter inside the cropper's inner pipeline, BEFORE the
 * face_landmarks_lite hailonet. Reads SCRFD's 5-point landmarks from the ROI,
 * computes an affine warp that makes the eyes horizontal (MediaPipe-style),
 * and warps the crop image in place so the model sees an upright face.
 *
 * Stores the 2x3 warp matrix as a 6-element HailoMatrix on the ROI so the
 * downstream face_landmarks_postprocess can apply the inverse transform
 * when projecting the 468 landmarks back to image coordinates.
 *
 * Math (matches face_landmarks_standalone.py):
 *   angle  = atan2(ly - ry, lx - rx)              // image-space eye angle
 *   rotation = -angle                             // rotate by -angle to straighten
 *   center = 0.5 * bbox_center + 0.5 * eye_center
 *   size   = max(bbox_w, bbox_h) * scale          // scale = 1.5 by default
 *   s      = 192 / size
 *   M      = [ s*cos -s*sin   -s*cos*cx + s*sin*cy + 96 ]
 *            [ s*sin  s*cos   -s*sin*cx - s*cos*cy + 96 ]
 */

#include <cmath>
#include <vector>
#include <gst/video/video.h>
#include <opencv2/opencv.hpp>
#include <opencv2/imgproc.hpp>
#include <opencv2/core.hpp>

#include "face_mesh_align.hpp"
#include "hailo_common.hpp"
#include "hailo_xtensor.hpp"
#include "image.hpp"
#include "xtensor/xadapt.hpp"
#include "xtensor/xarray.hpp"

#define FACE_MESH_INPUT_SIZE 192.0f
#define CROP_SCALE           1.5f
#define KP_RIGHT_EYE         0
#define KP_LEFT_EYE          1


struct WarpMatrices
{
    cv::Mat M_pixel; // For cv::warpAffine — maps input pixels → output pixels
    cv::Mat M_norm;  // For postprocess inverse — maps [0,1] input → [0,1] output
};


static WarpMatrices compute_warp_matrices(
    const std::vector<HailoPoint> &landmarks,
    guint img_w, guint img_h,
    HailoBBox bbox)
{
    // SCRFD landmarks are normalized [0,1] relative to the bbox.
    // First get EVERYTHING in normalized (bbox) coordinates, then in image pixels.
    const HailoPoint &right_eye = landmarks[KP_RIGHT_EYE];
    const HailoPoint &left_eye  = landmarks[KP_LEFT_EYE];

    // Eye pixel positions in image space
    float bw_px = bbox.width()  * img_w;
    float bh_px = bbox.height() * img_h;
    float bx_px = bbox.xmin()   * img_w;
    float by_px = bbox.ymin()   * img_h;
    float rex = right_eye.x() * bw_px + bx_px;
    float rey = right_eye.y() * bh_px + by_px;
    float lex = left_eye.x()  * bw_px + bx_px;
    float ley = left_eye.y()  * bh_px + by_px;

    // Rotation from eye vector (image-space, y-down).
    float angle_image = std::atan2(ley - rey, lex - rex);
    float rotation    = -angle_image;

    // Center for the warp: bbox center in image pixels.  The cropper already
    // centered the expanded bbox on the face (with a height offset upward for
    // more forehead in the crop), so the bbox center is a good rotation pivot.
    float cx = bx_px + 0.5f * bw_px;
    float cy = by_px + 0.5f * bh_px;

    // The vms_croppers cropper already expanded the original face bbox 1.58x and
    // produced this sub-frame. So the face region already fills most of the crop.
    // We do NOT apply any extra scaling — just rotation around the face center,
    // translating that center to the image center. videoscale then uniformly
    // resizes the whole frame to 192x192, preserving the proportion.
    float cos_r = std::cos(rotation);
    float sin_r = std::sin(rotation);

    // ---- M_pixel: pure rotation around (cx, cy), translating to image center ----
    cv::Mat M_pixel(2, 3, CV_32F);
    M_pixel.at<float>(0, 0) = cos_r;
    M_pixel.at<float>(0, 1) = -sin_r;
    M_pixel.at<float>(0, 2) = -cos_r * cx + sin_r * cy + img_w / 2.0f;
    M_pixel.at<float>(1, 0) = sin_r;
    M_pixel.at<float>(1, 1) = cos_r;
    M_pixel.at<float>(1, 2) = -sin_r * cx - cos_r * cy + img_h / 2.0f;

    // ---- M_norm: the same rotation expressed in [0,1] × [0,1] image space ----
    // The face center in normalized bbox coords; target is (0.5, 0.5).
    float cx_n = cx / img_w;
    float cy_n = cy / img_h;
    cv::Mat M_norm(2, 3, CV_32F);
    M_norm.at<float>(0, 0) = cos_r;
    M_norm.at<float>(0, 1) = -sin_r;
    M_norm.at<float>(0, 2) = -cos_r * cx_n + sin_r * cy_n + 0.5f;
    M_norm.at<float>(1, 0) = sin_r;
    M_norm.at<float>(1, 1) = cos_r;
    M_norm.at<float>(1, 2) = -sin_r * cx_n - cos_r * cy_n + 0.5f;

    return {M_pixel, M_norm};
}


static void store_warp_matrix_in_roi(HailoROIPtr roi, const cv::Mat &M)
{
    // Flatten 2x3 float matrix into 6 floats.
    std::vector<float> flat(6);
    for (int r = 0; r < 2; r++)
        for (int c = 0; c < 3; c++)
            flat[r * 3 + c] = M.at<float>(r, c);

    // Store as (1, 1, 6) HailoMatrix — downstream postprocess identifies it by size 6.
    xt::xarray<float> xmatrix = xt::adapt(flat, {(size_t)1, (size_t)1, (size_t)6});
    HailoMatrixPtr warp_mat_obj = hailo_common::create_matrix_ptr(xmatrix);
    roi->add_object(warp_mat_obj);
}


void face_mesh_align(HailoROIPtr roi, GstVideoFrame *frame, gchar *stream_id)
{
    (void)stream_id;

    // Read SCRFD 5-point landmarks from the ROI (bbox-normalized).
    auto landmark_objects = roi->get_objects_typed(HAILO_LANDMARKS);
    if (landmark_objects.empty())
        return;
    auto lm_obj = std::dynamic_pointer_cast<HailoLandmarks>(landmark_objects[0]);
    if (!lm_obj)
        return;
    std::vector<HailoPoint> pts = lm_obj->get_points();
    if (pts.size() < 2)
        return;

    cv::Mat image = get_mat_from_gst_frame(frame);
    guint width  = image.cols;
    guint height = image.rows;

    // Build both matrices — M_pixel for warping the image now, M_norm for the
    // postprocess to invert normalized landmarks back to original bbox coords.
    WarpMatrices mats = compute_warp_matrices(pts, width, height, roi->get_bbox());

    GstVideoInfo *info = &frame->info;
    switch (info->finfo->format)
    {
    case GST_VIDEO_FORMAT_RGBA:
    case GST_VIDEO_FORMAT_RGB:
    {
        cv::warpAffine(image, image, mats.M_pixel, image.size(),
                       cv::INTER_LINEAR, cv::BORDER_CONSTANT, cv::Scalar(0, 0, 0));
        break;
    }
    case GST_VIDEO_FORMAT_NV12:
    {
        cv::Mat y_mat  = cv::Mat(height * 2 / 3, width, CV_8UC1,
                                  (char *)image.data, width);
        cv::Mat uv_mat = cv::Mat(height / 3, width / 2, CV_8UC2,
                                  (char *)image.data + ((height * 2 / 3) * width), width);

        cv::warpAffine(y_mat, y_mat, mats.M_pixel, y_mat.size(), cv::INTER_LINEAR);

        cv::Mat M_uv = mats.M_pixel.clone();
        M_uv.at<float>(0, 2) /= 2.0f;
        M_uv.at<float>(1, 2) /= 2.0f;
        cv::warpAffine(uv_mat, uv_mat, M_uv, uv_mat.size(), cv::INTER_LINEAR);
        break;
    }
    default:
        return;
    }

    // Store the NORMALIZED warp matrix so postprocess can invert it directly
    // to get [0,1] bbox coordinates without knowing the crop image dimensions.
    store_warp_matrix_in_roi(roi, mats.M_norm);
}


void filter(HailoROIPtr roi, GstVideoFrame *frame, gchar *stream_id)
{
    face_mesh_align(roi, frame, stream_id);
}
