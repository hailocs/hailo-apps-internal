/**
 * face_landmarks_lite postprocess for hailofilter in a cascade pipeline.
 *
 * Runs inside the hailocropper inner pipeline — ROI is the face detection.
 * Reads the raw output tensors from face_landmarks_lite.hef:
 *   conv22: (1, 1, 1404) → 468 landmarks × 3 (x, y, z)
 *   conv25: (1, 1, 1)    → face presence confidence (apply sigmoid)
 *
 * If face_mesh_align ran upstream it will have stored a 6-element HailoMatrix
 * on the ROI containing the 2x3 affine warp matrix that was applied to the
 * image. We apply the inverse to project landmarks from the aligned 192x192
 * space back to crop-image pixel space, then normalize to bbox coords.
 *
 * Landmarks are stored as a 1404-element HailoMatrix (via HailoTracker so the
 * aggregator preserves them).
 */
#include <vector>
#include <cmath>
#include <string>
#include <opencv2/opencv.hpp>

#include "common/tensors.hpp"
#include "common/math.hpp"
#include "face_landmarks_postprocess.hpp"
#include "hailo_tracker.hpp"
#include "hailo_xtensor.hpp"
#include "xtensor/xadapt.hpp"
#include "xtensor/xarray.hpp"
#include "xtensor/xview.hpp"

static std::string tracker_name = "hailo_face_tracker";

#define NUM_FACE_LANDMARKS 468
#define FACE_LANDMARK_INPUT_SIZE 192.0f
#define FACE_PRESENCE_THRESHOLD 0.3f

// Landmark tensor has 1404 elements (468 * 3)
static const size_t LANDMARKS_TENSOR_SIZE = 1404;
// Warp matrix stored by face_mesh_align has 6 elements (2x3 affine)
static const size_t WARP_MATRIX_SIZE = 6;

// Face mesh skeleton connections (subset) for hailooverlay drawing.
static const std::vector<std::pair<int, int>> FACE_MESH_PAIRS = {
    {10, 338}, {338, 297}, {297, 332}, {332, 284}, {284, 251}, {251, 389},
    {389, 356}, {356, 454}, {454, 323}, {323, 361}, {361, 288}, {288, 397},
    {397, 365}, {365, 379}, {379, 378}, {378, 400}, {400, 377}, {377, 152},
    {152, 148}, {148, 176}, {176, 149}, {149, 150}, {150, 136}, {136, 172},
    {172, 58}, {58, 132}, {132, 93}, {93, 234}, {234, 127}, {127, 162},
    {162, 21}, {21, 54}, {54, 103}, {103, 67}, {67, 109}, {109, 10},
};

static HailoTensorPtr find_tensor_by_size(HailoROIPtr roi, size_t expected_size)
{
    for (auto &tensor : roi->get_tensors())
    {
        size_t total = tensor->width() * tensor->height() * tensor->features();
        if (total == expected_size)
            return tensor;
    }
    return nullptr;
}

// Look for a HailoMatrix of a specific flat size (e.g. 6 for warp matrix).
static HailoMatrixPtr find_matrix_by_size(HailoROIPtr roi, size_t expected_size)
{
    for (auto &obj : roi->get_objects_typed(HAILO_MATRIX))
    {
        auto mat = std::dynamic_pointer_cast<HailoMatrix>(obj);
        if (!mat) continue;
        auto data = mat->get_data();
        if (data.size() == expected_size)
            return mat;
    }
    return nullptr;
}

void face_landmarks_postprocess(HailoROIPtr roi)
{
    if (!roi->has_tensors())
        return;

    HailoTensorPtr landmarks_tensor = find_tensor_by_size(roi, LANDMARKS_TENSOR_SIZE);
    HailoTensorPtr confidence_tensor = find_tensor_by_size(roi, 1);

    if (!landmarks_tensor)
        return;

    // Face presence check (sigmoid of raw confidence)
    if (confidence_tensor)
    {
        auto conf_data = common::get_xtensor_float(confidence_tensor);
        float raw = conf_data(0);
        float confidence = 1.0f / (1.0f + std::exp(-raw));
        if (confidence < FACE_PRESENCE_THRESHOLD)
            return;
    }

    // Dequantize landmark tensor to (468, 3) in 192x192 ALIGNED pixel space.
    auto landmarks_data = common::get_xtensor_float(landmarks_tensor);
    xt::xarray<float> landmarks = xt::reshape_view(landmarks_data, {NUM_FACE_LANDMARKS, 3});

    // If the upstream face_mesh_align filter ran, it stored the 2x3 warp matrix
    // as a 6-element HailoMatrix on the ROI. Apply its inverse to project
    // landmarks from 192x192 aligned space back to crop-image pixel space.
    HailoMatrixPtr warp_mat_obj = find_matrix_by_size(roi, WARP_MATRIX_SIZE);
    bool have_warp = (warp_mat_obj != nullptr);

    cv::Mat M_inv;
    if (have_warp)
    {
        auto warp_data = warp_mat_obj->get_data();
        cv::Mat M(2, 3, CV_32F);
        for (int r = 0; r < 2; r++)
            for (int c = 0; c < 3; c++)
                M.at<float>(r, c) = warp_data[r * 3 + c];
        cv::invertAffineTransform(M, M_inv);

        // Remove the warp matrix so it doesn't pollute downstream.
        roi->remove_object(warp_mat_obj);
    }

    // Build output vector — landmarks in [0,1] of the bbox (= of the cropped image).
    // The stored warp matrix M_norm maps [0,1] bbox → [0,1] aligned.
    // So M_inv maps [0,1] aligned (normalized model space) → [0,1] bbox.
    std::vector<float> flat_data(NUM_FACE_LANDMARKS * 3);
    for (int i = 0; i < NUM_FACE_LANDMARKS; i++)
    {
        // Normalize model output from 192x192 pixel space → [0,1]
        float x_aligned = landmarks(i, 0) / FACE_LANDMARK_INPUT_SIZE;
        float y_aligned = landmarks(i, 1) / FACE_LANDMARK_INPUT_SIZE;
        float z = landmarks(i, 2);

        float x_bbox, y_bbox;
        if (have_warp)
        {
            x_bbox = M_inv.at<float>(0, 0) * x_aligned +
                     M_inv.at<float>(0, 1) * y_aligned +
                     M_inv.at<float>(0, 2);
            y_bbox = M_inv.at<float>(1, 0) * x_aligned +
                     M_inv.at<float>(1, 1) * y_aligned +
                     M_inv.at<float>(1, 2);
        }
        else
        {
            x_bbox = x_aligned;
            y_bbox = y_aligned;
        }

        flat_data[i * 3 + 0] = std::max(0.0f, std::min(x_bbox, 1.0f));
        flat_data[i * 3 + 1] = std::max(0.0f, std::min(y_bbox, 1.0f));
        flat_data[i * 3 + 2] = z;
    }

    // Store as HailoMatrix (1, 1, 1404), persisted via the tracker.
    xt::xarray<float> xmatrix = xt::adapt(flat_data,
        {(size_t)1, (size_t)1, (size_t)(NUM_FACE_LANDMARKS * 3)});
    HailoMatrixPtr landmarks_matrix = hailo_common::create_matrix_ptr(xmatrix);

    std::string jde_tracker_name = tracker_name + "_" + roi->get_stream_id();
    auto unique_ids = hailo_common::get_hailo_track_id(roi);

    if (unique_ids.empty())
    {
        roi->remove_objects_typed(HAILO_MATRIX);
        roi->add_object(landmarks_matrix);
    }
    else
    {
        HailoTracker::GetInstance().remove_matrices_from_track(jde_tracker_name, unique_ids[0]->get_id());
        HailoTracker::GetInstance().add_object_to_track(jde_tracker_name, unique_ids[0]->get_id(), landmarks_matrix);
    }
}

void filter(HailoROIPtr roi)
{
    face_landmarks_postprocess(roi);
}
