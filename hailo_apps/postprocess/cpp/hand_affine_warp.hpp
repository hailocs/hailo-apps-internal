/**
 * Copyright (c) 2021-2022 Hailo Technologies Ltd. All rights reserved.
 * Distributed under the LGPL license (https://www.gnu.org/licenses/old-licenses/lgpl-2.1.txt)
 **/
#pragma once
#include <gst/video/video.h>
#include <opencv2/opencv.hpp>
#include "hailo_objects.hpp"

namespace FacePreprocess {
    // Stub to match face_align.hpp pattern - not used here but needed for link compatibility
}

__BEGIN_DECLS
void filter(HailoROIPtr roi, GstVideoFrame *frame, gchar *current_stream_id);
__END_DECLS
