/**
 * Gesture classification from 21 hand landmarks.
 * Ported from gesture_classification.cpp — same finger extension logic.
 * No TAPPAS/Hailo dependencies.
 */
#include "gesture_classify.hpp"
#include <cmath>

enum HandLandmark {
    WRIST = 0,
    THUMB_CMC = 1, THUMB_MCP = 2, THUMB_IP = 3, THUMB_TIP = 4,
    INDEX_MCP = 5, INDEX_PIP = 6, INDEX_DIP = 7, INDEX_TIP = 8,
    MIDDLE_MCP = 9, MIDDLE_PIP = 10, MIDDLE_DIP = 11, MIDDLE_TIP = 12,
    RING_MCP = 13, RING_PIP = 14, RING_DIP = 15, RING_TIP = 16,
    PINKY_MCP = 17, PINKY_PIP = 18, PINKY_DIP = 19, PINKY_TIP = 20,
};

static inline float dist2d(const float a[3], const float b[3])
{
    float dx = a[0] - b[0];
    float dy = a[1] - b[1];
    return std::sqrt(dx * dx + dy * dy);
}

static bool is_finger_extended(const float lm[21][3], int tip_idx, int pip_idx)
{
    return dist2d(lm[tip_idx], lm[WRIST]) > dist2d(lm[pip_idx], lm[WRIST]);
}

static bool is_thumb_extended(const float lm[21][3])
{
    return dist2d(lm[THUMB_TIP], lm[INDEX_MCP]) > dist2d(lm[THUMB_MCP], lm[INDEX_MCP]);
}

std::string classify_gesture(const float landmarks[21][3])
{
    bool thumb = is_thumb_extended(landmarks);
    bool index = is_finger_extended(landmarks, INDEX_TIP, INDEX_PIP);
    bool middle = is_finger_extended(landmarks, MIDDLE_TIP, MIDDLE_PIP);
    bool ring = is_finger_extended(landmarks, RING_TIP, RING_PIP);
    bool pinky = is_finger_extended(landmarks, PINKY_TIP, PINKY_PIP);

    int count = (int)thumb + (int)index + (int)middle + (int)ring + (int)pinky;

    if (count == 0) return "FIST";
    if (count == 5) return "OPEN_HAND";

    if (thumb && !index && !middle && !ring && !pinky)
        return (landmarks[THUMB_TIP][1] < landmarks[WRIST][1]) ? "THUMBS_UP" : "THUMBS_DOWN";

    if (!thumb && index && !middle && !ring && !pinky)
        return "POINTING";

    if (!thumb && index && middle && !ring && !pinky)
        return "PEACE";

    static const char* count_labels[] = {"", "ONE", "TWO", "THREE", "FOUR"};
    if (count >= 1 && count <= 4)
        return count_labels[count];

    return "";
}
