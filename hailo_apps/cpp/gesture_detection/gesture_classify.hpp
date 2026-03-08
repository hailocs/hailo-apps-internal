#ifndef GESTURE_CLASSIFY_HPP
#define GESTURE_CLASSIFY_HPP

#include <string>

/// Classify gesture from 21 hand landmarks in image pixel coordinates.
/// landmarks[i][0] = x, landmarks[i][1] = y.
std::string classify_gesture(const float landmarks[21][3]);

#endif // GESTURE_CLASSIFY_HPP
