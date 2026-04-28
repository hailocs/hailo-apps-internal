"""FastTracker — occlusion-aware multi-object tracker.

Vendored from https://github.com/Hamidreza-Hashempoor/FastTracker
Modified: removed torch dependency, fixed imports for vendored package.
"""

import copy
import json
import math
import os
import os.path as osp

import numpy as np

from .kalman_filter import KalmanFilter
from . import matching
from .basetrack import BaseTrack, TrackState


class STrack(BaseTrack):
    shared_kalman = KalmanFilter()

    def __init__(self, tlwh, score):
        self._tlwh = np.asarray(tlwh, dtype=np.float64)
        self.kalman_filter = None
        self.mean, self.covariance = None, None
        self.is_activated = False
        self.score = score
        self.tracklet_len = 0
        self.not_matched = 0
        self.is_occluded = False
        self.occluded_len = 0
        self.last_occluded_frame = -1
        self.was_recently_occluded = False
        self.mean_history = []

    def predict(self):
        mean_state = self.mean.copy()
        if self.state != TrackState.Tracked:
            mean_state[7] = 0
        self.mean, self.covariance = self.kalman_filter.predict(mean_state, self.covariance)

    @staticmethod
    def multi_predict(stracks):
        if len(stracks) > 0:
            multi_mean = np.asarray([st.mean.copy() for st in stracks])
            multi_covariance = np.asarray([st.covariance for st in stracks])
            for i, st in enumerate(stracks):
                if st.state != TrackState.Tracked:
                    multi_mean[i][7] = 0
            multi_mean, multi_covariance = STrack.shared_kalman.multi_predict(multi_mean, multi_covariance)
            for i, (mean, cov) in enumerate(zip(multi_mean, multi_covariance)):
                stracks[i].mean = mean
                stracks[i].covariance = cov

    def activate(self, kalman_filter, frame_id):
        self.kalman_filter = kalman_filter
        self.track_id = self.next_id()
        self.mean, self.covariance = self.kalman_filter.initiate(self.tlwh_to_xyah(self._tlwh))
        self.mean_history.append(self.mean.copy())
        if len(self.mean_history) > 100:
            self.mean_history.pop(0)
        self.tracklet_len = 0
        self.state = TrackState.Tracked
        if frame_id == 1:
            self.is_activated = True
        self.frame_id = frame_id
        self.start_frame = frame_id

    def re_activate(self, new_track, frame_id, new_id=False):
        self.mean, self.covariance = self.kalman_filter.update(
            self.mean, self.covariance, self.tlwh_to_xyah(new_track.tlwh))
        self.mean_history.append(self.mean.copy())
        if len(self.mean_history) > 100:
            self.mean_history.pop(0)
        self.tracklet_len = 0
        self.state = TrackState.Tracked
        self.is_activated = True
        self.frame_id = frame_id
        if new_id:
            self.track_id = self.next_id()
        self.score = new_track.score

    def update(self, new_track, frame_id):
        self.frame_id = frame_id
        self.tracklet_len += 1
        new_tlwh = new_track.tlwh
        self.mean, self.covariance = self.kalman_filter.update(
            self.mean, self.covariance, self.tlwh_to_xyah(new_tlwh))
        self.mean_history.append(self.mean.copy())
        if len(self.mean_history) > 100:
            self.mean_history.pop(0)
        self.state = TrackState.Tracked
        self.is_activated = True
        self.score = new_track.score

    @property
    def tlwh(self):
        if self.mean is None:
            return self._tlwh.copy()
        ret = self.mean[:4].copy()
        ret[2] *= ret[3]
        ret[:2] -= ret[2:] / 2
        return ret

    @property
    def tlbr(self):
        ret = self.tlwh.copy()
        ret[2:] += ret[:2]
        return ret

    @staticmethod
    def tlwh_to_xyah(tlwh):
        ret = np.asarray(tlwh).copy()
        ret[:2] += ret[2:] / 2
        ret[2] /= ret[3]
        return ret

    def to_xyah(self):
        return self.tlwh_to_xyah(self.tlwh)

    @staticmethod
    def tlbr_to_tlwh(tlbr):
        ret = np.asarray(tlbr).copy()
        ret[2:] -= ret[:2]
        return ret

    @staticmethod
    def tlwh_to_tlbr(tlwh):
        ret = np.asarray(tlwh).copy()
        ret[2:] += ret[:2]
        return ret

    def __repr__(self):
        return 'OT_{}_({}-{})'.format(self.track_id, self.start_frame, self.end_frame)


def is_occluded_by(box_a, box_b, iou_thresh=0.7):
    inter = (
        max(0, min(box_a[2], box_b[2]) - max(box_a[0], box_b[0])) *
        max(0, min(box_a[3], box_b[3]) - max(box_a[1], box_b[1]))
    )
    area_a = (box_a[2] - box_a[0]) * (box_a[3] - box_a[1])
    if area_a == 0:
        return False
    return (inter / area_a) > iou_thresh


def _iou(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    iw = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    ih = max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = iw * ih
    if inter == 0:
        return 0.0
    area_a = (ax2 - ax1) * (ay2 - ay1)
    area_b = (bx2 - bx1) * (by2 - by1)
    return inter / (area_a + area_b - inter + 1e-9)


class Fasttracker(object):
    def __init__(self, args, config, frame_rate=30):
        self.tracked_stracks = []
        self.lost_stracks = []
        self.removed_stracks = []

        self.frame_id = 0
        self.args = args

        self.det_thresh = config["track_thresh"]
        self.match_thresh = config["match_thresh"]
        self.buffer_size = int(frame_rate / 30.0 * config["track_buffer"])
        self.max_time_lost = self.buffer_size

        self.reset_velocity_offset_occ = config.get("reset_velocity_offset_occ", 3)
        self.reset_pos_offset_occ = config.get("reset_pos_offset_occ", 3)
        self.enlarge_bbox_occ = config.get("enlarge_bbox_occ", 1.2)
        self.dampen_motion_occ = config.get("dampen_motion_occ", 0.5)
        self.active_occ_to_lost_thresh = config.get("active_occ_to_lost_thresh", 10)
        self.init_iou_suppress = config.get("init_iou_suppress", 0.8)

        # ROI constraints (optional, empty by default)
        self.roi_points = []
        self.theta_values = []
        rois = config.get("ROIs", {})
        for name, pts in rois.items():
            try:
                roi_np = np.array(pts)
                self.roi_points.append(roi_np)
                theta = self.compute_theta(roi_np)
                self.theta_values.append(theta)
            except Exception:
                pass

        self.roi_repair_max_gap = config.get("roi_repair_max_gap", 15)
        self.dir_window_N = config.get("dir_window_N", 10)
        self.dir_margin_deg = config.get("dir_margin_deg", 2.0)

        self.kalman_filter = KalmanFilter()

    def update(self, output_results, img_info, img_size):
        self.frame_id += 1
        activated_starcks = []
        refind_stracks = []
        lost_stracks = []
        removed_stracks = []

        if len(output_results) == 0:
            scores = np.array([])
            bboxes = np.array([])
        elif output_results.shape[1] == 5:
            scores = output_results[:, 4]
            bboxes = output_results[:, :4]
        else:
            scores = output_results[:, 4] * output_results[:, 5]
            bboxes = output_results[:, :4]

        img_h, img_w = img_info[0], img_info[1]
        scale = min(img_size[0] / float(img_h), img_size[1] / float(img_w))
        bboxes = bboxes / scale if scale != 1.0 else bboxes

        remain_inds = scores > self.det_thresh
        inds_low = scores > 0.25
        inds_high = scores < self.det_thresh
        inds_second = np.logical_and(inds_low, inds_high)

        dets_second = bboxes[inds_second]
        dets = bboxes[remain_inds]
        scores_keep = scores[remain_inds]
        scores_second = scores[inds_second]

        if len(dets) > 0:
            detections = [STrack(STrack.tlbr_to_tlwh(tlbr), s)
                          for (tlbr, s) in zip(dets, scores_keep)]
        else:
            detections = []

        unconfirmed = []
        tracked_stracks = []
        for track in self.tracked_stracks:
            if not track.is_activated:
                unconfirmed.append(track)
            else:
                tracked_stracks.append(track)

        # First association with high-score detections
        strack_pool = joint_stracks(tracked_stracks, self.lost_stracks)
        STrack.multi_predict(strack_pool)
        dists = matching.iou_distance(strack_pool, detections)
        if not getattr(self.args, 'mot20', False):
            dists = matching.fuse_score(dists, detections)
        matches, u_track, u_detection = matching.linear_assignment(dists, thresh=self.match_thresh)

        for itracked, idet in matches:
            track = strack_pool[itracked]
            det = detections[idet]
            if track.state == TrackState.Tracked:
                track.update(det, self.frame_id)
                activated_starcks.append(track)
            else:
                track.re_activate(det, self.frame_id, new_id=False)
                refind_stracks.append(track)
            track.is_occluded = False
            track.not_matched = 0
            track.occluded_len = 0

        # Second association with low-score detections
        if len(dets_second) > 0:
            detections_second = [STrack(STrack.tlbr_to_tlwh(tlbr), s)
                                 for (tlbr, s) in zip(dets_second, scores_second)]
        else:
            detections_second = []

        r_tracked_stracks = [strack_pool[i] for i in u_track
                             if strack_pool[i].state == TrackState.Tracked]
        dists = matching.iou_distance(r_tracked_stracks, detections_second)
        matches, u_track, u_detection_second = matching.linear_assignment(dists, thresh=0.5)

        for itracked, idet in matches:
            track = r_tracked_stracks[itracked]
            det = detections_second[idet]
            if track.state == TrackState.Tracked:
                track.update(det, self.frame_id)
                activated_starcks.append(track)
            else:
                track.re_activate(det, self.frame_id, new_id=False)
                refind_stracks.append(track)
            track.is_occluded = False
            track.not_matched = 0
            track.occluded_len = 0

        # Occlusion handling
        for it in u_track:
            track = r_tracked_stracks[it]
            track.not_matched += 1

            if not track.is_occluded and track.state == TrackState.Tracked:
                for other in activated_starcks:
                    if track.track_id == other.track_id:
                        continue
                    if not other.is_activated or other.is_occluded:
                        continue
                    if is_occluded_by(track.tlbr, other.tlbr):
                        track.is_occluded = True
                        track.occluded_len += 1
                        track.last_occluded_frame = self.frame_id
                        track.was_recently_occluded = True

                        if len(track.mean_history) >= self.reset_velocity_offset_occ:
                            old_mean = track.mean_history[-self.reset_velocity_offset_occ]
                            track.mean[4:8] = old_mean[4:8]
                        if len(track.mean_history) >= self.reset_pos_offset_occ:
                            old_mean = track.mean_history[-self.reset_pos_offset_occ]
                            track.mean[0:4] = old_mean[0:4]
                        if track.occluded_len == 1:
                            track.mean[3] *= self.enlarge_bbox_occ
                        track.mean[4:8] *= self.dampen_motion_occ
                        break

            if not track.is_occluded:
                track.occluded_len = 0
            else:
                track.occluded_len += 1

            if track.was_recently_occluded and (self.frame_id - track.last_occluded_frame > 40):
                track.was_recently_occluded = False

            if track.state != TrackState.Lost:
                if track.not_matched > 2 and (
                    not track.is_occluded or track.occluded_len > self.active_occ_to_lost_thresh
                ):
                    track.mark_lost()
                    lost_stracks.append(track)

        # Unconfirmed tracks
        detections = [detections[i] for i in u_detection]
        dists = matching.iou_distance(unconfirmed, detections)
        if not getattr(self.args, 'mot20', False):
            dists = matching.fuse_score(dists, detections)
        matches, u_unconfirmed, u_detection = matching.linear_assignment(dists, thresh=0.7)

        for itracked, idet in matches:
            unconfirmed[itracked].update(detections[idet], self.frame_id)
            activated_starcks.append(unconfirmed[itracked])
        for it in u_unconfirmed:
            track = unconfirmed[it]
            track.mark_lost()
            lost_stracks.append(track)

        # Environment constraints
        for t in activated_starcks:
            self.enforce_environment_constraints(t)
        for t in refind_stracks:
            self.enforce_environment_constraints(t)
        for t in self.tracked_stracks:
            if (t.state == TrackState.Tracked and
                    t not in activated_starcks and t not in refind_stracks):
                self.enforce_environment_constraints(t)

        # Init new tracks with IoU suppression
        active_now = {t.track_id: t for t in self.tracked_stracks
                      if t.state == TrackState.Tracked}
        for t in activated_starcks:
            active_now[t.track_id] = t
        active_now = list(active_now.values())

        init_iou_thr = self.init_iou_suppress

        for inew in u_detection:
            track = detections[inew]
            if track.score < self.det_thresh:
                continue
            det_box = STrack.tlwh_to_tlbr(track.tlwh)
            max_iou = 0.0
            for at in active_now:
                max_iou = max(max_iou, _iou(det_box, at.tlbr))
                if max_iou >= init_iou_thr:
                    break
            if max_iou < init_iou_thr:
                track.activate(self.kalman_filter, self.frame_id)
                activated_starcks.append(track)

        # Update state
        for track in self.lost_stracks:
            recently_occluded = (
                track.was_recently_occluded and
                (self.frame_id - track.last_occluded_frame <= 40)
            )
            if not recently_occluded and (self.frame_id - track.end_frame > self.max_time_lost):
                track.mark_removed()
                removed_stracks.append(track)

        self.tracked_stracks = [t for t in self.tracked_stracks if t.state == TrackState.Tracked]
        self.tracked_stracks = joint_stracks(self.tracked_stracks, activated_starcks)
        self.tracked_stracks = joint_stracks(self.tracked_stracks, refind_stracks)
        self.lost_stracks = sub_stracks(self.lost_stracks, self.tracked_stracks)
        self.lost_stracks.extend(lost_stracks)
        self.lost_stracks = sub_stracks(self.lost_stracks, self.removed_stracks)
        self.removed_stracks.extend(removed_stracks)
        self.tracked_stracks, self.lost_stracks = remove_duplicate_stracks(
            self.tracked_stracks, self.lost_stracks)

        return [track for track in self.tracked_stracks if track.is_activated]

    def enforce_environment_constraints(self, t):
        if not self.roi_points:
            return

        if not hasattr(t, "center_history"):
            t.center_history = []
        curr_center = self._get_center_from_tlwh(t.tlwh)
        t.center_history.append(curr_center.copy())

        roi_idx = -1
        for i, roi in enumerate(self.roi_points):
            if len(roi) >= 3 and self._point_in_polygon(curr_center, roi):
                roi_idx = i
                break
        if roi_idx < 0:
            return

        roi = self.roi_points[roi_idx]

        if self._point_in_polygon(curr_center, roi) and len(t.center_history) > 2:
            last_inside_idx = None
            last_outside_idx = None
            for i in range(len(t.center_history) - 2, -1, -1):
                pt = t.center_history[i]
                inside = self._point_in_polygon(pt, roi)
                if inside and last_outside_idx is not None:
                    last_inside_idx = i
                    break
                if not inside and last_outside_idx is None:
                    last_outside_idx = i

            if last_outside_idx is not None and last_inside_idx is not None:
                gap = last_outside_idx - last_inside_idx
                if 0 < gap <= self.roi_repair_max_gap:
                    for j in range(last_inside_idx + 1, last_outside_idx + 1):
                        pt_out = t.center_history[j]
                        clamped_point = self._clamp_point_to_polygon(pt_out, roi)
                        t.center_history[j] = clamped_point
                        if hasattr(t, "mean_history") and j < len(t.mean_history):
                            t.mean_history[j][:2] = clamped_point

        if len(roi) == 4:
            axis_u, theta_deg = self._cone_axis_and_theta(roi)
        else:
            return

        N = self.dir_window_N
        if len(t.center_history) >= (N + 1):
            pk = t.center_history[-1]
            pk_N = t.center_history[-1 - N]
            delta = pk - pk_N
            if np.linalg.norm(delta) > 1e-6:
                adjusted = self._clamp_to_cone(pk_N, pk, axis_u, theta_deg)
                if not np.allclose(adjusted, pk, atol=1e-3):
                    t.center_history[-1] = adjusted
                    if hasattr(t, "mean_history") and len(t.mean_history) > 0:
                        t.mean_history[-1][:2] = adjusted
                    x, y, w, h = t.tlwh
                    new_x = adjusted[0] - 0.5 * w
                    new_y = adjusted[1] - 0.5 * h
                    t.mean[0:2] = np.array([new_x, new_y], dtype=float)

    @staticmethod
    def compute_theta(roi):
        E1, E2, O2, O1 = roi
        v1 = np.array(O2) - np.array(E1)
        v2 = np.array(O1) - np.array(E2)
        dot = np.dot(v1, v2)
        denom = np.linalg.norm(v1) * np.linalg.norm(v2)
        return np.degrees(np.arccos(np.clip(dot / denom, -1.0, 1.0)))

    @staticmethod
    def _get_center_from_tlwh(tlwh):
        x, y, w, h = tlwh
        return np.array([x + 0.5 * w, y + 0.5 * h], dtype=float)

    @staticmethod
    def _point_in_polygon(pt, poly):
        x, y = pt
        inside = False
        n = len(poly)
        for i in range(n):
            x1, y1 = poly[i]
            x2, y2 = poly[(i + 1) % n]
            if ((y1 > y) != (y2 > y)) and (x < (x2 - x1) * (y - y1) / ((y2 - y1) + 1e-9) + x1):
                inside = not inside
        return inside

    @staticmethod
    def _closest_point_on_segment(p, a, b):
        ap = p - a
        ab = b - a
        t = np.dot(ap, ab) / (np.dot(ab, ab) + 1e-9)
        t = max(0.0, min(1.0, t))
        return a + t * ab

    @classmethod
    def _clamp_point_to_polygon(cls, pt, poly):
        best = None
        best_d2 = 1e18
        n = len(poly)
        for i in range(n):
            a = poly[i].astype(float)
            b = poly[(i + 1) % n].astype(float)
            q = cls._closest_point_on_segment(pt, a, b)
            d2 = np.sum((q - pt) ** 2)
            if d2 < best_d2:
                best_d2 = d2
                best = q
        return best if best is not None else pt

    @staticmethod
    def _normalize(v):
        n = np.linalg.norm(v)
        return v / (n + 1e-9)

    @staticmethod
    def _cone_axis_and_theta(roi):
        E1, E2, O2, O1 = roi
        v1 = Fasttracker._normalize(np.array(O2) - np.array(E1))
        v2 = Fasttracker._normalize(np.array(O1) - np.array(E2))
        axis = Fasttracker._normalize(v1 + v2)
        dot = float(np.clip(np.dot(v1, v2), -1.0, 1.0))
        theta = math.degrees(math.acos(dot))
        return axis, theta

    def _clamp_to_cone(self, anchor_pt, curr_pt, axis_u, theta_deg):
        delta = np.asarray(curr_pt, dtype=float) - np.asarray(anchor_pt, dtype=float)
        mag = np.linalg.norm(delta)
        if mag < 3.0:
            return curr_pt
        delta_u = delta / mag
        axis_u = self._normalize(np.asarray(axis_u, dtype=float))
        cosang = float(np.clip(np.dot(delta_u, axis_u), -1.0, 1.0))
        ang = math.acos(cosang)
        half = math.radians(theta_deg) * 0.5
        if ang <= half:
            return curr_pt
        cross_z = axis_u[0] * delta_u[1] - axis_u[1] * delta_u[0]
        sign = 1.0 if cross_z > 0 else -1.0
        c, s = math.cos(sign * half), math.sin(sign * half)
        boundary_dir = np.array([axis_u[0] * c - axis_u[1] * s,
                                 axis_u[0] * s + axis_u[1] * c], dtype=float)
        return np.asarray(anchor_pt, dtype=float) + boundary_dir * mag


def joint_stracks(tlista, tlistb):
    exists = {}
    res = []
    for t in tlista:
        exists[t.track_id] = 1
        res.append(t)
    for t in tlistb:
        if not exists.get(t.track_id, 0):
            exists[t.track_id] = 1
            res.append(t)
    return res


def sub_stracks(tlista, tlistb):
    stracks = {t.track_id: t for t in tlista}
    for t in tlistb:
        stracks.pop(t.track_id, None)
    return list(stracks.values())


def remove_duplicate_stracks(stracksa, stracksb):
    pdist = matching.iou_distance(stracksa, stracksb)
    pairs = np.where(pdist < 0.15)
    dupa, dupb = [], []
    for p, q in zip(*pairs):
        timep = stracksa[p].frame_id - stracksa[p].start_frame
        timeq = stracksb[q].frame_id - stracksb[q].start_frame
        if timep > timeq:
            dupb.append(q)
        else:
            dupa.append(p)
    resa = [t for i, t in enumerate(stracksa) if i not in dupa]
    resb = [t for i, t in enumerate(stracksb) if i not in dupb]
    return resa, resb
