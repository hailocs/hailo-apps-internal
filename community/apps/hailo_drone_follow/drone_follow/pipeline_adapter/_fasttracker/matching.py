"""Matching utilities for FastTracker.

Vendored from https://github.com/Hamidreza-Hashempoor/FastTracker
Modified: replaced lap/cython_bbox with scipy/numpy equivalents.
"""

import numpy as np
from scipy.optimize import linear_sum_assignment as scipy_lsa
from scipy.spatial.distance import cdist

from . import kalman_filter


# ---------------------------------------------------------------------------
# Pure-numpy bbox IoU (replaces cython_bbox)
# ---------------------------------------------------------------------------

def _bbox_ious_numpy(atlbrs: np.ndarray, btlbrs: np.ndarray) -> np.ndarray:
    """Compute IoU between two sets of tlbr boxes using numpy broadcasting."""
    a = np.asarray(atlbrs, dtype=np.float64)
    b = np.asarray(btlbrs, dtype=np.float64)
    # (N,1,4) vs (1,M,4)
    a_exp = a[:, None, :]
    b_exp = b[None, :, :]
    xx1 = np.maximum(a_exp[..., 0], b_exp[..., 0])
    yy1 = np.maximum(a_exp[..., 1], b_exp[..., 1])
    xx2 = np.minimum(a_exp[..., 2], b_exp[..., 2])
    yy2 = np.minimum(a_exp[..., 3], b_exp[..., 3])
    inter = np.maximum(0, xx2 - xx1) * np.maximum(0, yy2 - yy1)
    area_a = (a_exp[..., 2] - a_exp[..., 0]) * (a_exp[..., 3] - a_exp[..., 1])
    area_b = (b_exp[..., 2] - b_exp[..., 0]) * (b_exp[..., 3] - b_exp[..., 1])
    return inter / np.maximum(area_a + area_b - inter, 1e-6)


# ---------------------------------------------------------------------------
# scipy-based linear assignment (replaces lap.lapjv)
# ---------------------------------------------------------------------------

def linear_assignment(cost_matrix, thresh):
    if cost_matrix.size == 0:
        return (np.empty((0, 2), dtype=int),
                tuple(range(cost_matrix.shape[0])),
                tuple(range(cost_matrix.shape[1])))
    row_ind, col_ind = scipy_lsa(cost_matrix)
    matches = []
    unmatched_a = set(range(cost_matrix.shape[0]))
    unmatched_b = set(range(cost_matrix.shape[1]))
    for r, c in zip(row_ind, col_ind):
        if cost_matrix[r, c] <= thresh:
            matches.append([r, c])
            unmatched_a.discard(r)
            unmatched_b.discard(c)
    matches = np.asarray(matches) if matches else np.empty((0, 2), dtype=int)
    return matches, np.array(sorted(unmatched_a)), np.array(sorted(unmatched_b))


# ---------------------------------------------------------------------------
# IoU-based distances
# ---------------------------------------------------------------------------

def ious(atlbrs, btlbrs):
    ious_mat = np.zeros((len(atlbrs), len(btlbrs)), dtype=np.float64)
    if ious_mat.size == 0:
        return ious_mat
    return _bbox_ious_numpy(
        np.ascontiguousarray(atlbrs, dtype=np.float64),
        np.ascontiguousarray(btlbrs, dtype=np.float64),
    )


def iou_distance(atracks, btracks):
    if ((len(atracks) > 0 and isinstance(atracks[0], np.ndarray)) or
            (len(btracks) > 0 and isinstance(btracks[0], np.ndarray))):
        atlbrs = atracks
        btlbrs = btracks
    else:
        atlbrs = [track.tlbr for track in atracks]
        btlbrs = [track.tlbr for track in btracks]
    _ious = ious(atlbrs, btlbrs)
    return 1 - _ious


def fuse_score(cost_matrix, detections):
    if cost_matrix.size == 0:
        return cost_matrix
    iou_sim = 1 - cost_matrix
    det_scores = np.array([det.score for det in detections])
    det_scores = np.expand_dims(det_scores, axis=0).repeat(cost_matrix.shape[0], axis=0)
    fuse_sim = iou_sim * det_scores
    return 1 - fuse_sim
