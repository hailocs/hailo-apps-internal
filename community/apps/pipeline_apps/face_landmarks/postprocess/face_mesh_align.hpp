/**
 * face_mesh_align — rotation-aware face alignment hailofilter.
 */
#pragma once
#include <gst/video/video.h>
#include "hailo_objects.hpp"
#include "hailo_common.hpp"

__BEGIN_DECLS
void filter(HailoROIPtr roi, GstVideoFrame *frame, gchar *stream_id);
void face_mesh_align(HailoROIPtr roi, GstVideoFrame *frame, gchar *stream_id);
__END_DECLS
