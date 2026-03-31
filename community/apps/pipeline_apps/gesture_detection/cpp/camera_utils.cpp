#include "camera_utils.hpp"

#include <array>
#include <cstdio>
#include <filesystem>
#include <iostream>

namespace fs = std::filesystem;

/// Run a shell command and capture stdout.
static std::string exec_cmd(const std::string& cmd)
{
    std::array<char, 256> buf;
    std::string result;
    FILE* pipe = popen(cmd.c_str(), "r");
    if (!pipe)
        return "";
    while (fgets(buf.data(), buf.size(), pipe))
        result += buf.data();
    pclose(pipe);
    return result;
}

std::string find_usb_camera()
{
    std::vector<std::string> devices;
    for (auto& entry : fs::directory_iterator("/dev"))
    {
        std::string name = entry.path().filename().string();
        if (name.substr(0, 5) == "video")
            devices.push_back(entry.path().string());
    }
    std::sort(devices.begin(), devices.end());

    for (auto& dev : devices)
    {
        std::string cmd = "udevadm info --query=all --name=" + dev + " 2>/dev/null";
        std::string output = exec_cmd(cmd);

        if (output.find("ID_BUS=usb") != std::string::npos &&
            output.find(":capture:") != std::string::npos)
        {
            return dev;
        }
    }
    return "";
}

cv::VideoCapture open_rpi_camera(int width, int height, int fps)
{
    // Use libcamerasrc GStreamer element (requires gstreamer1.0-libcamera package).
    // Don't force resolution on libcamerasrc — let the ISP negotiate the native
    // sensor resolution, then use videoscale to resize to the desired output.
    std::string pipeline =
        "libcamerasrc ! "
        "videoconvert ! videoscale ! "
        "video/x-raw,format=BGR"
        ",width=" + std::to_string(width) +
        ",height=" + std::to_string(height) +
        ",framerate=" + std::to_string(fps) + "/1 ! "
        "appsink drop=true max-buffers=2";

    std::cout << "Opening RPi camera via libcamerasrc" << std::endl;
    return cv::VideoCapture(pipeline, cv::CAP_GSTREAMER);
}

bool resolve_input(const std::string& input, cv::VideoCapture& cap,
                   std::string& source_desc)
{
    if (input == "usb")
    {
        std::string dev = find_usb_camera();
        if (dev.empty())
        {
            std::cerr << "Error: No USB camera found" << std::endl;
            return false;
        }
        std::cout << "USB camera detected: " << dev << std::endl;
        cap.open(dev, cv::CAP_V4L2);
        source_desc = "USB camera (" + dev + ")";
        return cap.isOpened();
    }

    if (input == "rpi")
    {
        cap = open_rpi_camera();
        source_desc = "RPi camera (libcamerasrc)";
        if (!cap.isOpened())
        {
            std::cerr << "Error: Cannot open RPi camera.\n"
                      << "Install the GStreamer libcamera plugin:\n"
                      << "  sudo apt install gstreamer1.0-libcamera\n"
                      << std::endl;
            return false;
        }
        return true;
    }

    // Try as camera index
    try
    {
        int idx = std::stoi(input);
        if (idx >= 0 && input.find_first_not_of("0123456789") == std::string::npos)
        {
            cap.open(idx, cv::CAP_V4L2);
            source_desc = "camera " + std::to_string(idx);
            return cap.isOpened();
        }
    }
    catch (...) {}

    // File path
    cap.open(input);
    source_desc = input;
    return cap.isOpened();
}
