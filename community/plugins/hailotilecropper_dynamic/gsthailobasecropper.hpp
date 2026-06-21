/**
* Copyright (c) 2021-2022 Hailo Technologies Ltd. All rights reserved.
* Distributed under the LGPL license (https://www.gnu.org/licenses/old-licenses/lgpl-2.1.txt)
**/
#pragma once
#include <map>
#include <gst/gst.h>
#include <gst/video/video-format.h>
#include <opencv2/opencv.hpp>
#include "hailo_objects.hpp"

G_BEGIN_DECLS

#define GST_TYPE_HAILO_BASE_CROPPER_DYN (gst_hailo_basecropper_dyn_get_type())
#define GST_HAILO_BASE_CROPPER_DYN(obj) (G_TYPE_CHECK_INSTANCE_CAST((obj), GST_TYPE_HAILO_BASE_CROPPER_DYN, GstHailoBaseCropperDyn))
#define GST_HAILO_BASE_CROPPER_DYN_CLASS(klass) (G_TYPE_CHECK_CLASS_CAST((klass), GST_TYPE_HAILO_BASE_CROPPER_DYN, GstHailoBaseCropperDynClass))
#define GST_IS_HAILO_BASE_CROPPER_DYN(obj) (G_TYPE_CHECK_INSTANCE_TYPE((obj), GST_TYPE_HAILO_BASE_CROPPER_DYN))
#define GST_IS_HAILO_BASE_CROPPER_DYN_CLASS(klass) (G_TYPE_CHECK_CLASS_TYPE((klass), GST_TYPE_HAILO_BASE_CROPPER_DYN))
#define GST_HAILO_BASE_CROPPER_DYN_CAST(obj) ((GstHailoBaseCropperDyn *)obj)
#define GST_HAILO_BASE_CROPPER_DYN_GET_CLASS(obj) \
        (G_TYPE_INSTANCE_GET_CLASS ((obj),GST_TYPE_HAILO_BASE_CROPPER_DYN,GstHailoBaseCropperDynClass))

#define GST_HAILO_CROPPER_MAX_FILTER_STREAMS 40
#define HAILO_BASE_CROPPER_SUPPORTED_FORMATS_DYN "{ RGB, RGBA, YUY2, NV12 }"
#define HAILO_BASE_CROPPER_VIDEO_CAPS_DYN \
    GST_VIDEO_CAPS_MAKE(HAILO_BASE_CROPPER_SUPPORTED_FORMATS_DYN)

typedef struct _GstHailoBaseCropperDyn GstHailoBaseCropperDyn;
typedef struct _GstHailoBaseCropperDynClass GstHailoBaseCropperDynClass;

struct _GstHailoBaseCropperDyn
{
    GstElement element;
    gboolean use_internal_offset;
    gboolean drop_uncropped_buffers;
    uint internal_offset;
    uint cropping_period;
    #ifdef HAILO15_TARGET
    bool use_dsp;
    guint bufferpool_max_size;
    guint bufferpool_min_size;
    #endif
    GstBufferPool *buffer_pool;
    uint num_streams_to_filter = 0;
    GstPad *sinkpad, *srcpad_crop, *srcpad_main;
    std::map<std::string, int> stream_ids_buff_offset;
    const gchar *filter_streams[GST_HAILO_CROPPER_MAX_FILTER_STREAMS];
};

struct _GstHailoBaseCropperDynClass
{
    GstElementClass parent_class;

    std::vector<HailoROIPtr> (*prepare_crops) (GstHailoBaseCropperDyn *hailocropper,  GstBuffer *buf);
    void (*resize) (GstHailoBaseCropperDyn *basecropper, std::vector<cv::Mat> &cropped_image, std::vector<cv::Mat> &resized_image, HailoROIPtr roi, GstVideoFormat image_format);
};

G_GNUC_INTERNAL GType gst_hailo_basecropper_dyn_get_type(void);
void resize_normal(cv::InterpolationFlags method, std::vector<cv::Mat> &cropped_image_vec, std::vector<cv::Mat> &resized_image_vec, GstVideoFormat image_format);
void resize_letterbox(cv::InterpolationFlags method, std::vector<cv::Mat> &cropped_image_vec, std::vector<cv::Mat> &resized_image_vec, HailoROIPtr roi, GstVideoFormat image_format, bool no_scaling_bbox);

G_END_DECLS
