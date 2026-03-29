#pragma once
#include <string>
#include <opencv2/opencv.hpp>

/// Auto-detect the first USB video capture device via udevadm.
/// Returns "" if none found.
std::string find_usb_camera();

/// Open an RPi CSI camera via libcamerasrc GStreamer pipeline.
/// Returns an opened VideoCapture (check .isOpened()).
cv::VideoCapture open_rpi_camera(int width = 640, int height = 480, int fps = 30);

/// Resolve the --input argument:
///   "usb"  → auto-detect USB camera device path
///   "rpi"  → open RPi camera via GStreamer
///   "0"-"9"→ camera index
///   other  → file path (returned as-is)
/// On success, cap is opened and source_desc is set for display.
/// Returns false on failure.
bool resolve_input(const std::string& input, cv::VideoCapture& cap,
                   std::string& source_desc);
