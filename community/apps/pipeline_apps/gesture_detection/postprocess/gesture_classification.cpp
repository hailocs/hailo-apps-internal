/**
 * Gesture classification from 21 hand landmarks + metadata cleanup.
 *
 * Reads HailoLandmarks ("hand_landmarks") attached to hand detections
 * and adds a HailoClassification ("gesture") with the recognized gesture label.
 *
 * Also cleans up metadata that hailooverlay would otherwise render:
 *  - Removes "palm_angle" classifications (internal rotation metadata)
 *  - Removes "palm" detections (only needed for cropping stage)
 *
 * Ported from gesture_recognition.py — same finger extension logic.
 */
#include <cmath>
#include <string>
#include <vector>
#include <algorithm>
#include <limits>
#include "gesture_classification.hpp"

// Hand landmark indices (MediaPipe)
enum HandLandmark {
    WRIST = 0,
    THUMB_CMC = 1, THUMB_MCP = 2, THUMB_IP = 3, THUMB_TIP = 4,
    INDEX_MCP = 5, INDEX_PIP = 6, INDEX_DIP = 7, INDEX_TIP = 8,
    MIDDLE_MCP = 9, MIDDLE_PIP = 10, MIDDLE_DIP = 11, MIDDLE_TIP = 12,
    RING_MCP = 13, RING_PIP = 14, RING_DIP = 15, RING_TIP = 16,
    PINKY_MCP = 17, PINKY_PIP = 18, PINKY_DIP = 19, PINKY_TIP = 20,
};

static inline float dist(const HailoPoint &a, const HailoPoint &b)
{
    float dx = a.x() - b.x();
    float dy = a.y() - b.y();
    return std::sqrt(dx * dx + dy * dy);
}

static bool is_finger_extended(const std::vector<HailoPoint> &pts, int tip_idx, int pip_idx)
{
    return dist(pts[tip_idx], pts[WRIST]) > dist(pts[pip_idx], pts[WRIST]);
}

static bool is_thumb_extended(const std::vector<HailoPoint> &pts)
{
    return dist(pts[THUMB_TIP], pts[INDEX_MCP]) > dist(pts[THUMB_MCP], pts[INDEX_MCP]);
}

static std::string classify(const std::vector<HailoPoint> &pts)
{
    if (pts.size() < 21)
        return "";

    bool thumb = is_thumb_extended(pts);
    bool index = is_finger_extended(pts, INDEX_TIP, INDEX_PIP);
    bool middle = is_finger_extended(pts, MIDDLE_TIP, MIDDLE_PIP);
    bool ring = is_finger_extended(pts, RING_TIP, RING_PIP);
    bool pinky = is_finger_extended(pts, PINKY_TIP, PINKY_PIP);

    int count = (int)thumb + (int)index + (int)middle + (int)ring + (int)pinky;

    if (count == 0) return "FIST";
    if (count == 5) return "OPEN_HAND";

    // Thumb only
    if (thumb && !index && !middle && !ring && !pinky)
        return (pts[THUMB_TIP].y() < pts[WRIST].y()) ? "THUMBS_UP" : "THUMBS_DOWN";

    // Index only
    if (!thumb && index && !middle && !ring && !pinky)
        return "POINTING";

    // Peace
    if (!thumb && index && middle && !ring && !pinky)
        return "PEACE";

    // Generic
    static const char *count_labels[] = {"", "ONE", "TWO", "THREE", "FOUR"};
    if (count >= 1 && count <= 4)
        return count_labels[count];

    return "";
}

/**
 * @brief Walk all detections on the ROI:
 *  1. Classify gesture from hand_landmarks on hand detections
 *  2. Tighten hand bbox to fit landmarks (matching Python pipeline)
 *  3. Remove palm_angle classifications (internal metadata)
 *  4. Remove palm detections (only needed for the cropping stage)
 *  5. Clear scaling_bbox (palm wrapper's letterbox transform, no longer needed)
 */
void gesture_classification_filter(HailoROIPtr roi)
{
    // Collect objects to remove and add after iteration
    std::vector<HailoObjectPtr> to_remove;
    std::vector<HailoDetectionPtr> to_add;

    for (auto &obj : roi->get_objects_typed(HAILO_DETECTION))
    {
        auto det = std::dynamic_pointer_cast<HailoDetection>(obj);
        if (!det)
            continue;

        // Remove person_palm_crop detections (synthetic crop regions, not real detections).
        // Keep palm detections — their landmarks are useful for debugging and visible in overlay.
        if (det->get_label() == "person_palm_crop")
        {
            to_remove.push_back(obj);
            continue;
        }

        // Process hand detections
        if (det->get_label() == "hand")
        {
            // Find hand_landmarks
            std::shared_ptr<HailoLandmarks> hand_lm = nullptr;
            for (auto &sub_obj : det->get_objects_typed(HAILO_LANDMARKS))
            {
                auto lm = std::dynamic_pointer_cast<HailoLandmarks>(sub_obj);
                if (lm && lm->get_landmarks_type() == "hand_landmarks")
                {
                    hand_lm = lm;
                    break;
                }
            }

            if (!hand_lm)
            {
                // No landmarks — this is a raw crop region from palm_to_hand_crop,
                // not a real hand detection. Remove it so hailooverlay doesn't render it.
                to_remove.push_back(obj);
                continue;
            }

            auto pts = hand_lm->get_points();
            if (pts.size() < 21)
                continue;

            // Classify gesture
            std::string gesture = classify(pts);

            // Convert landmarks to frame-absolute [0,1] coords
            HailoBBox old_bbox = det->get_bbox();
            float old_xmin = old_bbox.xmin();
            float old_ymin = old_bbox.ymin();
            float old_w = old_bbox.width();
            float old_h = old_bbox.height();

            // Compute tight bbox from landmarks (matching Python gesture_detection_gst.py)
            float lm_xmin = std::numeric_limits<float>::max();
            float lm_ymin = std::numeric_limits<float>::max();
            float lm_xmax = std::numeric_limits<float>::lowest();
            float lm_ymax = std::numeric_limits<float>::lowest();

            for (auto &pt : pts)
            {
                // Convert from detection-relative to frame-absolute
                float abs_x = pt.x() * old_w + old_xmin;
                float abs_y = pt.y() * old_h + old_ymin;
                lm_xmin = std::min(lm_xmin, abs_x);
                lm_ymin = std::min(lm_ymin, abs_y);
                lm_xmax = std::max(lm_xmax, abs_x);
                lm_ymax = std::max(lm_ymax, abs_y);
            }

            // Add 10% padding (matching Python)
            float pad_x = (lm_xmax - lm_xmin) * 0.1f;
            float pad_y = (lm_ymax - lm_ymin) * 0.1f;
            lm_xmin = std::max(0.0f, lm_xmin - pad_x);
            lm_ymin = std::max(0.0f, lm_ymin - pad_y);
            lm_xmax = std::min(1.0f, lm_xmax + pad_x);
            lm_ymax = std::min(1.0f, lm_ymax + pad_y);

            float new_w = std::max(lm_xmax - lm_xmin, 0.001f);
            float new_h = std::max(lm_ymax - lm_ymin, 0.001f);

            // Create new detection with tight bbox
            HailoBBox tight_bbox(lm_xmin, lm_ymin, new_w, new_h);
            auto new_det = std::make_shared<HailoDetection>(
                tight_bbox, "hand", det->get_confidence());

            // Re-normalize landmarks relative to the new tight bbox
            std::vector<HailoPoint> new_pts;
            new_pts.reserve(pts.size());
            for (auto &pt : pts)
            {
                float abs_x = pt.x() * old_w + old_xmin;
                float abs_y = pt.y() * old_h + old_ymin;
                float new_x = (abs_x - lm_xmin) / new_w;
                float new_y = (abs_y - lm_ymin) / new_h;
                new_pts.emplace_back(new_x, new_y, pt.confidence());
            }

            auto new_landmarks = std::make_shared<HailoLandmarks>(
                "hand_landmarks", new_pts, hand_lm->get_threshold(),
                hand_lm->get_pairs());
            new_det->add_object(new_landmarks);

            // Add gesture classification
            if (!gesture.empty())
            {
                auto cls = std::make_shared<HailoClassification>(
                    "gesture", gesture, 1.0f);
                new_det->add_object(cls);
            }

            // Replace old detection with new tight one
            to_remove.push_back(obj);
            to_add.push_back(new_det);
        }
    }

    // Apply modifications
    for (auto &obj : to_remove)
        roi->remove_object(obj);
    for (auto &det : to_add)
        roi->add_object(det);

    // Reset scaling_bbox to identity. The INFERENCE_PIPELINE_WRAPPER for palm
    // detection leaves a letterbox scaling_bbox on the ROI. Palm detections
    // (in letterbox space) have been removed above. The new tight hand detections
    // are in frame-absolute normalized coords, so no scaling_bbox is needed.
    // Without this, hailooverlay applies the letterbox scaling to the hand bbox
    // (stretching Y by the aspect ratio), while landmarks bypass it — causing
    // the bbox to appear non-tight around correctly-positioned landmarks.
    roi->clear_scaling_bbox();
}

void filter(HailoROIPtr roi)
{
    gesture_classification_filter(roi);
}
