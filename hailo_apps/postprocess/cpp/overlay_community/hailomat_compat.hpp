#pragma once
// Cross-version bridge for the TAPPAS HailoMat drawing API.
//
// TAPPAS 5.3 decoupled the public hailomat.hpp from OpenCV: the drawing methods
// (draw_rectangle / draw_text / draw_line / draw_ellipse / blur) now take the
// OpenCV-free structs hailo_point_t / hailo_rect_t / hailo_size_t / hailo_scalar_t,
// which replaced cv::Point / cv::Rect / cv::Size / cv::Scalar.
//
// Older TAPPAS (< 5.3) does not define those structs and the same methods take the
// cv:: types directly. This header lets overlay_community build across the whole
// supported TAPPAS range: on >= 5.3 it is a thin pass-through to the real header;
// on < 5.3 it defines the new type names as aliases of the cv:: types, so the
// existing call sites (which use hailo_*_t) resolve to the old cv::-based API.
//
// The TAPPAS version is injected by meson as -DHAILO_TAPPAS_VER=<major*100+minor>
// (0 = unknown -> treated as current/new API).

#include "hailomat.hpp"

#if defined(HAILO_TAPPAS_VER) && HAILO_TAPPAS_VER != 0 && HAILO_TAPPAS_VER < 503
#include <opencv2/core.hpp>

// Pre-5.3 headers lack these structs; alias them onto the cv:: types the old
// drawing API expects. Constructors match those used by overlay_community
// (cv::Point(x,y), cv::Size(w,h), cv::Rect(x,y,w,h), cv::Scalar(v0,v1,v2,v3)).
using hailo_point_t  = cv::Point;
using hailo_size_t   = cv::Size;
using hailo_rect_t   = cv::Rect;
using hailo_scalar_t = cv::Scalar;

#endif // pre-5.3 compatibility
