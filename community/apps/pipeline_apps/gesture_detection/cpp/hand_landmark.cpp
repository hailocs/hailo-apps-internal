/**
 * Hand landmark ROI extraction, inference decode, and denormalization.
 * Ports blaze_base.py detection2roi + extract_roi + decode + denormalize.
 * Uses single cv::warpAffine — no GStreamer, no hailocropper.
 */
#include "hand_landmark.hpp"
#include <cmath>
#include <algorithm>
#include <opencv2/imgproc.hpp>

HandROI detection2roi(const PalmDetection& det)
{
    // Box center in image pixels (detection coords are already denormalized)
    float xc = (det.coords[1] + det.coords[3]) / 2.0f;  // (xmin + xmax) / 2
    float yc = (det.coords[0] + det.coords[2]) / 2.0f;  // (ymin + ymax) / 2

    // Scale from box width
    float scale = det.coords[3] - det.coords[1];  // xmax - xmin

    // Rotation from keypoints (kp1=0, kp2=2)
    float kp1_x = det.coords[4 + ROI_KP1 * 2];
    float kp1_y = det.coords[4 + ROI_KP1 * 2 + 1];
    float kp2_x = det.coords[4 + ROI_KP2 * 2];
    float kp2_y = det.coords[4 + ROI_KP2 * 2 + 1];

    float theta = std::atan2(kp1_y - kp2_y, kp1_x - kp2_x) - ROI_THETA0;

    // Apply offsets along the hand axis (rotated coordinate frame)
    xc += -ROI_DY * scale * std::sin(theta);
    yc += ROI_DY * scale * std::cos(theta);
    scale *= ROI_DSCALE;

    HandROI roi;
    roi.xc = xc;
    roi.yc = yc;
    roi.scale = scale;
    roi.theta = theta;
    return roi;
}

cv::Mat extract_roi(const cv::Mat& rgb, HandROI& roi)
{
    // Matches blaze_base.extract_roi exactly:
    // Source points: center, center+right, center+down (in image space)
    float cos_t = std::cos(roi.theta);
    float sin_t = std::sin(roi.theta);
    float half = roi.scale / 2.0f;
    float res = HAND_LANDMARK_INPUT_SIZE;

    cv::Point2f src[3];
    src[0] = cv::Point2f(roi.xc, roi.yc);                                          // center
    src[1] = cv::Point2f(roi.xc + half * cos_t, roi.yc + half * sin_t);           // center + right
    src[2] = cv::Point2f(roi.xc - half * sin_t, roi.yc + half * cos_t);           // center + down

    cv::Point2f dst[3];
    dst[0] = cv::Point2f(res / 2.0f, res / 2.0f);    // center
    dst[1] = cv::Point2f(res, res / 2.0f);             // right
    dst[2] = cv::Point2f(res / 2.0f, res);             // bottom

    // Forward affine: image → crop
    cv::Mat M = cv::getAffineTransform(src, dst);
    cv::Mat crop;
    cv::warpAffine(rgb, crop, M, cv::Size(static_cast<int>(res), static_cast<int>(res)));

    // Convert to float32 [0,1]
    crop.convertTo(crop, CV_32FC3, 1.0 / 255.0);

    // Inverse affine: crop → image (for denormalizing landmarks)
    roi.inv_affine = cv::getAffineTransform(dst, src);

    return crop;
}

HandResult decode_hand_outputs(
    const float* landmarks_data, size_t landmarks_size,
    const float* flag_data,
    const float* handedness_data)
{
    HandResult result;

    // Flag: sigmoid
    float raw_flag = flag_data ? flag_data[0] : 0.0f;
    result.flag = 1.0f / (1.0f + std::exp(-raw_flag));

    // Handedness
    result.handedness = handedness_data ? handedness_data[0] : 0.0f;

    // Landmarks: reshape (63,) → (21, 3), values in [0, 224]
    if (landmarks_size >= 63)
    {
        for (int i = 0; i < 21; i++)
        {
            result.landmarks[i][0] = landmarks_data[i * 3 + 0];  // x
            result.landmarks[i][1] = landmarks_data[i * 3 + 1];  // y
            result.landmarks[i][2] = landmarks_data[i * 3 + 2];  // z
        }
    }
    else
    {
        std::memset(result.landmarks, 0, sizeof(result.landmarks));
    }

    result.gesture = "";
    return result;
}

void denormalize_landmarks(HandResult& result, const cv::Mat& inv_affine)
{
    // Matches blaze_base.denormalize_landmarks:
    // landmarks are in [0, 224] pixel coords in crop space.
    // Apply inv_affine (2x3) to map to original image pixels.
    // No need to multiply by resolution since landmarks_data is already in [0,224].

    if (inv_affine.empty())
        return;

    // inv_affine is 2x3, double precision from getAffineTransform
    double m00 = inv_affine.at<double>(0, 0);
    double m01 = inv_affine.at<double>(0, 1);
    double m02 = inv_affine.at<double>(0, 2);
    double m10 = inv_affine.at<double>(1, 0);
    double m11 = inv_affine.at<double>(1, 1);
    double m12 = inv_affine.at<double>(1, 2);

    for (int i = 0; i < 21; i++)
    {
        float x = result.landmarks[i][0];
        float y = result.landmarks[i][1];

        // [x', y'] = M[:,:2] @ [x, y]^T + M[:,2]
        result.landmarks[i][0] = static_cast<float>(m00 * x + m01 * y + m02);
        result.landmarks[i][1] = static_cast<float>(m10 * x + m11 * y + m12);
        // z stays unchanged
    }
}
