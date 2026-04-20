/**
 * face_landmarks_lite postprocess for hailofilter in a cascade pipeline.
 *
 * Runs inside hailocropper inner pipeline — ROI is the face detection.
 * Reads the raw output tensors from face_landmarks_lite.hef:
 *   conv22: (1, 1, 1404) → 468 landmarks × 3 (x, y, z)
 *   conv25: (1, 1, 1)    → face presence confidence (apply sigmoid)
 *
 * Normalizes x,y to [0,1] relative to the 192×192 input and creates
 * HailoLandmarks("face_landmarks", 468 points) on the detection.
 *
 * hailooverlay maps: screen = (point * bbox_size + bbox_min) * frame_size
 */
#include <vector>
#include <cmath>
#include <string>
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

// Face mesh skeleton connections for hailooverlay drawing.
// A subset of the MediaPipe FACEMESH_TESSELATION — face oval + eyes + lips + brows.
static const std::vector<std::pair<int, int>> FACE_MESH_PAIRS = {
    // Face oval
    {10, 338}, {338, 297}, {297, 332}, {332, 284}, {284, 251}, {251, 389},
    {389, 356}, {356, 454}, {454, 323}, {323, 361}, {361, 288}, {288, 397},
    {397, 365}, {365, 379}, {379, 378}, {378, 400}, {400, 377}, {377, 152},
    {152, 148}, {148, 176}, {176, 149}, {149, 150}, {150, 136}, {136, 172},
    {172, 58}, {58, 132}, {132, 93}, {93, 234}, {234, 127}, {127, 162},
    {162, 21}, {21, 54}, {54, 103}, {103, 67}, {67, 109}, {109, 10},
    // Left eye
    {362, 382}, {382, 381}, {381, 380}, {380, 374}, {374, 373}, {373, 390},
    {390, 249}, {249, 263}, {263, 466}, {466, 388}, {388, 387}, {387, 386},
    {386, 385}, {385, 384}, {384, 398}, {398, 362},
    // Right eye
    {33, 7}, {7, 163}, {163, 144}, {144, 145}, {145, 153}, {153, 154},
    {154, 155}, {155, 133}, {133, 173}, {173, 157}, {157, 158}, {158, 159},
    {159, 160}, {160, 161}, {161, 246}, {246, 33},
    // Lips (outer)
    {61, 146}, {146, 91}, {91, 181}, {181, 84}, {84, 17}, {17, 314},
    {314, 405}, {405, 321}, {321, 375}, {375, 291}, {291, 308}, {308, 324},
    {324, 318}, {318, 402}, {402, 317}, {317, 14}, {14, 87}, {87, 178},
    {178, 88}, {88, 95}, {95, 61},
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

void face_landmarks_postprocess(HailoROIPtr roi)
{
    if (!roi->has_tensors())
        return;

    HailoTensorPtr landmarks_tensor = find_tensor_by_size(roi, LANDMARKS_TENSOR_SIZE);
    HailoTensorPtr confidence_tensor = find_tensor_by_size(roi, 1);

    if (!landmarks_tensor)
        return;

    // Check face presence confidence (sigmoid)
    if (confidence_tensor)
    {
        auto conf_data = common::get_xtensor_float(confidence_tensor);
        float raw = conf_data(0);
        float confidence = 1.0f / (1.0f + std::exp(-raw));
        if (confidence < FACE_PRESENCE_THRESHOLD)
            return;
    }

    // Dequantize and reshape landmarks
    auto landmarks_data = common::get_xtensor_float(landmarks_tensor);
    xt::xarray<float> landmarks = xt::reshape_view(landmarks_data, {NUM_FACE_LANDMARKS, 3});

    // Normalize x,y to [0,1] and flatten to 1D vector for HailoMatrix storage.
    // We store as HailoMatrix because hailoaggregator preserves HAILO_MATRIX
    // objects (proven by face_recognition/arcface) but drops HAILO_LANDMARKS
    // added in the inner pipeline.
    std::vector<float> flat_data(NUM_FACE_LANDMARKS * 3);
    for (int i = 0; i < NUM_FACE_LANDMARKS; i++)
    {
        float nx = landmarks(i, 0) / FACE_LANDMARK_INPUT_SIZE;
        float ny = landmarks(i, 1) / FACE_LANDMARK_INPUT_SIZE;
        float nz = landmarks(i, 2);

        nx = std::max(0.0f, std::min(1.0f, nx));
        ny = std::max(0.0f, std::min(1.0f, ny));

        flat_data[i * 3 + 0] = nx;
        flat_data[i * 3 + 1] = ny;
        flat_data[i * 3 + 2] = nz;
    }

    // Store as HailoMatrix (1, 1, 1404).
    // Use HailoTracker to persist through the aggregator (same pattern as arcface).
    xt::xarray<float> xmatrix = xt::adapt(flat_data, {(size_t)1, (size_t)1, (size_t)(NUM_FACE_LANDMARKS * 3)});
    HailoMatrixPtr landmarks_matrix = hailo_common::create_matrix_ptr(xmatrix);

    std::string jde_tracker_name = tracker_name + "_" + roi->get_stream_id();
    auto unique_ids = hailo_common::get_hailo_track_id(roi);

    if (unique_ids.empty())
    {
        // No track ID — add directly to ROI (fallback)
        roi->remove_objects_typed(HAILO_MATRIX);
        roi->add_object(landmarks_matrix);
    }
    else
    {
        // Persist via tracker — survives the aggregator
        HailoTracker::GetInstance().remove_matrices_from_track(jde_tracker_name, unique_ids[0]->get_id());
        HailoTracker::GetInstance().add_object_to_track(jde_tracker_name, unique_ids[0]->get_id(), landmarks_matrix);
    }
}

void filter(HailoROIPtr roi)
{
    face_landmarks_postprocess(roi);
}
