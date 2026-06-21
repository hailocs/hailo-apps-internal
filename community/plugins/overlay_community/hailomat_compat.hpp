#pragma once
// Cross-version bridge for the TAPPAS HailoMat drawing API.
//
// TAPPAS 5.2 decoupled the public hailomat.hpp from OpenCV: the drawing methods
// (draw_rectangle / draw_text / draw_line / draw_ellipse / blur) now take the
// OpenCV-free structs hailo_point_t / hailo_rect_t / hailo_size_t / hailo_scalar_t,
// which replaced cv::Point / cv::Rect / cv::Size / cv::Scalar. (Verified on real
// TAPPAS 5.2.0 + 5.3.x headers; 5.1.0 still ships the old cv::-based API.)
//
// Older TAPPAS (< 5.2) does not define those structs and the same methods take the
// cv:: types directly. This header lets overlay_community build across the whole
// supported TAPPAS range: on >= 5.2 it is a thin pass-through to the real header;
// on < 5.2 it defines the new type names as aliases of the cv:: types, so the
// existing call sites (which use hailo_*_t) resolve to the old cv::-based API.
//
// The TAPPAS version is injected by meson as -DHAILO_TAPPAS_VER=<major*100+minor>
// (0 = unknown -> treated as current/new API).

#include "hailomat.hpp"
#include <opencv2/core.hpp>
#include <vector>

#if defined(HAILO_TAPPAS_VER) && HAILO_TAPPAS_VER != 0 && HAILO_TAPPAS_VER < 502
// ---------------------------- TAPPAS < 5.2 ----------------------------------
// Pre-5.2 headers lack the OpenCV-free drawing structs; alias them onto the
// cv:: types the old drawing API expects (cv::Point(x,y), cv::Size(w,h),
// cv::Rect(x,y,w,h), cv::Scalar(v0,v1,v2,v3)).
using hailo_point_t  = cv::Point;
using hailo_size_t   = cv::Size;
using hailo_rect_t   = cv::Rect;
using hailo_scalar_t = cv::Scalar;

// Pre-5.2 has no hailomat_internal.hpp / get_impl(); cv::Mat is reachable via
// HailoMat::get_matrices() directly. Provide the 5.2+ accessor names so call
// sites work uniformly across versions.
inline std::vector<cv::Mat> &get_cv_matrices(HailoMat &mat) { return mat.get_matrices(); }
inline cv::Mat &get_cv_matrix(HailoMat &mat, int idx = 0) { return mat.get_matrices()[idx]; }

#else
// ---------------------------- TAPPAS >= 5.2 ---------------------------------
// The real internal header provides get_impl()/get_cv_matrices(); the
// OpenCV-free drawing structs live in the public hailomat.hpp.
#include "hailomat_internal.hpp"
inline cv::Mat &get_cv_matrix(HailoMat &mat, int idx = 0) { return mat.get_impl()->get(idx); }
#endif
