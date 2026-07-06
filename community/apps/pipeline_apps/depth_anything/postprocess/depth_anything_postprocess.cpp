/**
 * Depth Anything V1/V2 post-processing for Hailo GStreamer pipeline.
 *
 * Unlike SCDepthV3 (which applies sigmoid + reciprocal), Depth Anything
 * output is raw relative depth — just dequantize and create HailoDepthMask.
 *
 * Output tensor names:
 *   V1: depth_anything_vits/conv79       (224x224x1, uint16)
 *   V2: depth_anything_v2_vits/conv79    (224x224x1, uint16)
 *
 * The filter() entry point iterates all tensors to find the single output,
 * so it works with both V1 and V2 without hardcoding the layer name.
 */
#include "hailo_objects.hpp"
#include "hailo_common.hpp"
#include "common/tensors.hpp"

#include "xtensor/xarray.hpp"

__BEGIN_DECLS
void filter(HailoROIPtr roi);
void filter_depth_anything(HailoROIPtr roi);
__END_DECLS

void filter(HailoROIPtr roi)
{
    filter_depth_anything(roi);
}

void filter_depth_anything(HailoROIPtr roi)
{
    if (!roi->has_tensors())
    {
        return;
    }

    // Get the first (and only) output tensor — works for both V1 and V2
    auto tensors = roi->get_tensors();
    if (tensors.empty())
    {
        return;
    }
    HailoTensorPtr tensor_ptr = tensors[0];

    // Dequantize uint16 → float32
    xt::xarray<uint16_t> tensor_data = common::get_xtensor_uint16(tensor_ptr);
    xt::xarray<float> depth = common::dequantize(
        tensor_data,
        tensor_ptr->quant_info().qp_scale,
        tensor_ptr->quant_info().qp_zp);

    // No mathematical transform needed (unlike SCDepthV3's sigmoid/reciprocal).
    // The dequantized values ARE the relative depth map.

    // Copy to vector for HailoDepthMask
    std::vector<float> depth_vector(depth.begin(), depth.end());

    hailo_common::add_object(
        roi,
        std::make_shared<HailoDepthMask>(
            std::move(depth_vector),
            tensor_ptr->width(),
            tensor_ptr->height(),
            1.0f));
}
