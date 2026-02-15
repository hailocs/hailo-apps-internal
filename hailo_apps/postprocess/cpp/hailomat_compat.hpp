/**
 * Copyright (c) 2021-2022 Hailo Technologies Ltd. All rights reserved.
 * Distributed under the LGPL license (https://www.gnu.org/licenses/old-licenses/lgpl-2.1.txt)
 **/
/**
 * @file hailomat_compat.hpp
 * @brief Compatibility shim for HailoMat crop/matrix access across TAPPAS versions.
 *
 * TAPPAS 5.2 (Hailo 10H) uses a PIMPL pattern: crop() returns
 * std::unique_ptr<HailoMatImpl> and cv::Mat access goes through
 * hailomat_internal.hpp helpers (crop_to_cv_matrices, get_cv_matrices).
 *
 * Older TAPPAS (Hailo 8L) exposes cv::Mat directly: crop() returns
 * std::vector<cv::Mat> and get_matrices() is a member of HailoMat.
 *
 * This header detects which API is available at compile time and provides
 * a unified interface so all .cpp files can use the same calls regardless
 * of platform:
 *   - crop_to_cv_matrices(mat, roi)   -> std::vector<cv::Mat>
 *   - get_cv_matrices(mat)            -> std::vector<cv::Mat>&
 */

#pragma once

#include "hailomat.hpp"

#if __has_include("hailomat_internal.hpp")
// ── New TAPPAS (Hailo 10H) ─────────────────────────────────────────────────
// hailomat_internal.hpp already defines crop_to_cv_matrices() and
// get_cv_matrices(); just pull them in.
#include "hailomat_internal.hpp"

#else
// ── Old TAPPAS (Hailo 8L) ──────────────────────────────────────────────────
// Provide the same helper signatures, forwarding to the old direct API.

#include <opencv2/core.hpp>
#include <vector>
#include <memory>

inline std::vector<cv::Mat> crop_to_cv_matrices(HailoMat &mat, HailoROIPtr crop_roi)
{
    return mat.crop(crop_roi);
}

inline std::vector<cv::Mat> &get_cv_matrices(HailoMat &mat)
{
    return mat.get_matrices();
}

inline const std::vector<cv::Mat> &get_cv_matrices(const HailoMat &mat)
{
    return mat.get_matrices();
}

#endif
