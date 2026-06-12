/**
 * Standalone gesture detection using HailoRT + OpenCV.
 * Follows the proven Python pipeline (gesture_detection_h8.py / blaze_base.py) exactly.
 *
 * Data flow:
 *   OpenCV capture (BGR) → BGR→RGB → resize_pad(192x192)
 *   → palm_detection_lite.hef → decode anchors + weighted NMS → denormalize
 *   → for each palm: detection2roi → warpAffine(224x224)
 *     → hand_landmark_lite.hef → decode landmarks → denormalize via inv_affine
 *     → classify_gesture → draw on frame → imshow
 *
 * Usage:
 *   ./gesture_detection --palm-model palm_detection_lite.hef --hand-model hand_landmark_lite.hef
 *   ./gesture_detection --input video.mp4
 *   ./gesture_detection --input photo.jpg
 */
#include <iostream>
#include <string>
#include <vector>
#include <chrono>
#include <algorithm>
#include <cstring>

#include <opencv2/opencv.hpp>

#include "hailo_infer.hpp"
#include "common_types.hpp"
#include "palm_detection.hpp"
#include "hand_landmark.hpp"
#include "gesture_classify.hpp"
#include "camera_utils.hpp"

// Drawing constants
static const cv::Scalar COLOR_PALM_BOX(0, 255, 0);
static const cv::Scalar COLOR_LANDMARK(255, 0, 0);
static const cv::Scalar COLOR_SKELETON(0, 200, 200);
static const cv::Scalar COLOR_GESTURE(255, 255, 255);
static const cv::Scalar COLOR_FPS(0, 255, 0);

// Hand skeleton connections (MediaPipe topology)
static const std::vector<std::pair<int,int>> HAND_CONNECTIONS = {
    {0,1},{1,2},{2,3},{3,4},         // thumb
    {0,5},{5,6},{6,7},{7,8},         // index
    {0,9},{9,10},{10,11},{11,12},    // middle
    {0,13},{13,14},{14,15},{15,16},  // ring
    {0,17},{17,18},{18,19},{19,20},  // pinky
    {5,9},{9,13},{13,17},            // palm
};

static constexpr int MAX_HANDS = 4;

// Default model paths (relative to models/ subdirectory)
static const std::string DEFAULT_PALM_MODEL = "models/palm_detection_lite.hef";
static const std::string DEFAULT_HAND_MODEL = "models/hand_landmark_lite.hef";

struct Args {
    std::string palm_model;
    std::string hand_model;
    std::string input;
    bool headless = false;
};

static Args parse_args(int argc, char** argv)
{
    Args args;
    args.palm_model = DEFAULT_PALM_MODEL;
    args.hand_model = DEFAULT_HAND_MODEL;
    args.input = "0";

    for (int i = 1; i < argc; i++)
    {
        std::string arg = argv[i];
        if ((arg == "--palm-model") && i + 1 < argc)
            args.palm_model = argv[++i];
        else if ((arg == "--hand-model") && i + 1 < argc)
            args.hand_model = argv[++i];
        else if ((arg == "--input" || arg == "-i") && i + 1 < argc)
            args.input = argv[++i];
        else if (arg == "--headless")
            args.headless = true;
        else if (arg == "--help" || arg == "-h")
        {
            std::cout << "Usage: gesture_detection [options]\n"
                      << "  --palm-model PATH   Palm detection HEF (default: " << DEFAULT_PALM_MODEL << ")\n"
                      << "  --hand-model PATH   Hand landmark HEF (default: " << DEFAULT_HAND_MODEL << ")\n"
                      << "  --input SOURCE      Input source (default: 0)\n"
                      << "                        usb  - auto-detect USB camera\n"
                      << "                        rpi  - RPi CSI camera (libcamerasrc)\n"
                      << "                        0-9  - camera index\n"
                      << "                        path - video file or image\n"
                      << "  --headless          No display window\n";
            std::exit(0);
        }
    }
    return args;
}

static void draw_hand(cv::Mat& frame, const HandResult& result)
{
    // Draw skeleton
    for (auto& [i, j] : HAND_CONNECTIONS)
    {
        cv::Point pi(static_cast<int>(result.landmarks[i][0]),
                     static_cast<int>(result.landmarks[i][1]));
        cv::Point pj(static_cast<int>(result.landmarks[j][0]),
                     static_cast<int>(result.landmarks[j][1]));
        cv::line(frame, pi, pj, COLOR_SKELETON, 2);
    }

    // Draw landmark points
    for (int i = 0; i < 21; i++)
    {
        cv::Point pt(static_cast<int>(result.landmarks[i][0]),
                     static_cast<int>(result.landmarks[i][1]));
        cv::circle(frame, pt, 4, COLOR_LANDMARK, -1);
    }

    // Draw gesture label
    if (!result.gesture.empty())
    {
        std::string hand_str = (result.handedness > 0.5f) ? "L" : "R";
        std::string label = hand_str + " " + result.gesture;
        cv::Point wrist(static_cast<int>(result.landmarks[0][0]) - 30,
                        static_cast<int>(result.landmarks[0][1]) - 20);
        cv::putText(frame, label, wrist, cv::FONT_HERSHEY_SIMPLEX,
                    0.8, COLOR_GESTURE, 2, cv::LINE_AA);
    }
}

static void draw_palm_box(cv::Mat& frame, const PalmDetection& det)
{
    cv::Point tl(static_cast<int>(det.coords[1]), static_cast<int>(det.coords[0]));
    cv::Point br(static_cast<int>(det.coords[3]), static_cast<int>(det.coords[2]));
    cv::rectangle(frame, tl, br, COLOR_PALM_BOX, 2);
}

/// Identify palm model output tensors by size.
/// Score tensors: total < 2016, box tensors: total >= 2016.
/// Sort each by size descending (large layer first).
struct PalmOutputMapping {
    // Indices into the output_data_and_infos vector
    int score_large = -1, score_small = -1;
    int box_large = -1, box_small = -1;
    size_t n_score_large = 0, n_score_small = 0;
};

static PalmOutputMapping map_palm_outputs(
    const std::vector<std::pair<uint8_t*, hailo_vstream_info_t>>& outputs)
{
    PalmOutputMapping m;

    struct TensorInfo { int idx; size_t total; };
    std::vector<TensorInfo> score_tensors, box_tensors;

    for (int i = 0; i < static_cast<int>(outputs.size()); i++)
    {
        auto& info = outputs[i].second;
        size_t total = info.shape.height * info.shape.width * info.shape.features;
        if (total < PALM_NUM_ANCHORS)
            score_tensors.push_back({i, total});
        else
            box_tensors.push_back({i, total});
    }

    // Sort descending by size
    std::sort(score_tensors.begin(), score_tensors.end(),
              [](const TensorInfo& a, const TensorInfo& b) { return a.total > b.total; });
    std::sort(box_tensors.begin(), box_tensors.end(),
              [](const TensorInfo& a, const TensorInfo& b) { return a.total > b.total; });

    if (score_tensors.size() >= 2 && box_tensors.size() >= 2)
    {
        m.score_large = score_tensors[0].idx;
        m.score_small = score_tensors[1].idx;
        m.n_score_large = score_tensors[0].total;
        m.n_score_small = score_tensors[1].total;
        m.box_large = box_tensors[0].idx;
        m.box_small = box_tensors[1].idx;
    }

    return m;
}

/// Identify hand landmark output tensors by size / name suffix.
struct HandOutputMapping {
    int landmarks_idx = -1;   // fc1: 63 floats (21*3)
    int flag_idx = -1;        // fc4: 1 float
    int handedness_idx = -1;  // fc3: 1 float
};

static HandOutputMapping map_hand_outputs(
    const std::vector<std::pair<uint8_t*, hailo_vstream_info_t>>& outputs)
{
    HandOutputMapping m;

    // First pass: match by name suffix (fc1=landmarks, fc2=world(skip), fc3=handedness, fc4=flag)
    for (int i = 0; i < static_cast<int>(outputs.size()); i++)
    {
        std::string name(outputs[i].second.name);

        // Check suffix: name might be "model/fc1" or "hand_landmark_lite/fc1" etc.
        if (name.size() >= 3)
        {
            std::string suffix3 = name.substr(name.size() - 3);
            if (suffix3 == "fc1")
                m.landmarks_idx = i;
            else if (suffix3 == "fc4")
                m.flag_idx = i;
            else if (suffix3 == "fc3")
                m.handedness_idx = i;
            // fc2 = world landmarks, intentionally skipped
        }
    }

    // Fallback by size if name matching didn't work
    if (m.landmarks_idx == -1 || m.flag_idx == -1)
    {
        for (int i = 0; i < static_cast<int>(outputs.size()); i++)
        {
            auto& info = outputs[i].second;
            size_t total = info.shape.height * info.shape.width * info.shape.features;
            if (total == 63 && m.landmarks_idx == -1)
                m.landmarks_idx = i;
            else if (total == 1)
            {
                if (m.flag_idx == -1)
                    m.flag_idx = i;
                else if (m.handedness_idx == -1)
                    m.handedness_idx = i;
            }
        }
    }

    return m;
}

static bool is_image_file(const std::string& path)
{
    std::string lower = path;
    std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);
    return lower.find(".jpg") != std::string::npos ||
           lower.find(".jpeg") != std::string::npos ||
           lower.find(".png") != std::string::npos ||
           lower.find(".bmp") != std::string::npos;
}

int main(int argc, char** argv)
{
    Args args = parse_args(argc, argv);

    std::cout << "Loading palm detection: " << args.palm_model << std::endl;
    std::cout << "Loading hand landmark:  " << args.hand_model << std::endl;

    // Create two HailoInfer instances sharing a VDevice via group_id
    const std::string group_id = "gesture";
    HailoInfer palm_model(args.palm_model, group_id, 1,
                          HAILO_FORMAT_TYPE_AUTO, HAILO_FORMAT_TYPE_FLOAT32);
    HailoInfer hand_model(args.hand_model, group_id, 1,
                          HAILO_FORMAT_TYPE_AUTO, HAILO_FORMAT_TYPE_FLOAT32);

    auto palm_shape = palm_model.get_model_shape();
    auto hand_shape = hand_model.get_model_shape();
    std::cout << "Palm model input: " << palm_shape.width << "x" << palm_shape.height << std::endl;
    std::cout << "Hand model input: " << hand_shape.width << "x" << hand_shape.height << std::endl;

    // Open input source
    bool single_image = false;
    cv::Mat static_frame;
    cv::VideoCapture cap;

    if (is_image_file(args.input))
    {
        static_frame = cv::imread(args.input);
        if (static_frame.empty())
        {
            std::cerr << "Error: Cannot read image: " << args.input << std::endl;
            return 1;
        }
        single_image = true;
        std::cout << "Processing image: " << args.input
                  << " (" << static_frame.cols << "x" << static_frame.rows << ")" << std::endl;
    }
    else
    {
        std::string source_desc;
        if (!resolve_input(args.input, cap, source_desc))
        {
            std::cerr << "Error: Cannot open video source: " << args.input << std::endl;
            return 1;
        }

        int w = static_cast<int>(cap.get(cv::CAP_PROP_FRAME_WIDTH));
        int h = static_cast<int>(cap.get(cv::CAP_PROP_FRAME_HEIGHT));
        double fps = cap.get(cv::CAP_PROP_FPS);
        std::cout << "Source: " << source_desc << " (" << w << "x" << h
                  << " @ " << fps << "fps)" << std::endl;
    }

    // Output tensor mappings (computed once after first inference)
    PalmOutputMapping palm_map;
    HandOutputMapping hand_map;
    bool palm_mapped = false, hand_mapped = false;

    // FPS tracking
    double fps_smoothed = 0.0;
    auto prev_time = std::chrono::high_resolution_clock::now();

    // Benchmark stats
    int total_frames = 0;
    int frames_with_hands = 0;
    std::vector<double> frame_times_ms;
    std::vector<double> preprocess_times_ms;
    std::vector<double> palm_infer_times_ms;
    std::vector<double> postprocess_times_ms;
    std::vector<double> hand_infer_times_ms;
    auto wall_start = std::chrono::high_resolution_clock::now();

    std::cout << "Starting gesture detection (press 'q' to quit)..." << std::endl;

    while (true)
    {
        cv::Mat frame;
        if (single_image)
        {
            frame = static_frame.clone();
        }
        else
        {
            if (!cap.read(frame) || frame.empty())
            {
                // For video files, end of stream
                if (!cap.get(cv::CAP_PROP_POS_FRAMES))
                    continue;
                break;
            }
        }

        auto t_start = std::chrono::high_resolution_clock::now();

        // 1. BGR → RGB
        cv::Mat rgb;
        cv::cvtColor(frame, rgb, cv::COLOR_BGR2RGB);

        // 2. Preprocess for palm detection
        auto palm_pre = preprocess_palm(rgb);

        auto t_preprocess = std::chrono::high_resolution_clock::now();

        // 3. Run palm detection inference
        // Prepare input: model expects uint8 RGB
        std::string palm_input_name = palm_model.get_infer_model()->get_input_names()[0];
        InputMap palm_inputs;
        palm_inputs[palm_input_name] = {palm_pre.padded};

        // Storage for palm results (populated in callback)
        std::vector<PalmDetection> palm_detections;
        std::vector<std::pair<uint8_t*, hailo_vstream_info_t>> palm_outputs_copy;

        palm_model.infer(palm_inputs,
            [&](const hailort::AsyncInferCompletionInfo& info,
                const std::vector<std::pair<uint8_t*, hailo_vstream_info_t>>& output_data,
                const std::vector<std::shared_ptr<uint8_t>>&) {
                if (info.status != HAILO_SUCCESS)
                {
                    std::cerr << "Palm inference failed: " << info.status << std::endl;
                    return;
                }

                if (!palm_mapped)
                {
                    palm_map = map_palm_outputs(output_data);
                    palm_mapped = true;
                }

                if (palm_map.score_large < 0)
                    return;

                const float* scores_large = reinterpret_cast<const float*>(
                    output_data[palm_map.score_large].first);
                const float* scores_small = reinterpret_cast<const float*>(
                    output_data[palm_map.score_small].first);
                const float* boxes_large = reinterpret_cast<const float*>(
                    output_data[palm_map.box_large].first);
                const float* boxes_small = reinterpret_cast<const float*>(
                    output_data[palm_map.box_small].first);

                auto dets = decode_palm_outputs(
                    scores_large, palm_map.n_score_large,
                    scores_small, palm_map.n_score_small,
                    boxes_large, boxes_small);

                palm_detections = weighted_nms(dets, PALM_MIN_SUPPRESSION_THRESHOLD);
            });
        palm_model.wait_for_last_job();

        auto t_palm_infer = std::chrono::high_resolution_clock::now();

        if (palm_detections.empty())
        {
            total_frames++;
            double pre_ms = std::chrono::duration<double, std::milli>(t_preprocess - t_start).count();
            double palm_ms = std::chrono::duration<double, std::milli>(t_palm_infer - t_preprocess).count();
            auto t_end_frame = std::chrono::high_resolution_clock::now();
            double total_ms = std::chrono::duration<double, std::milli>(t_end_frame - t_start).count();
            frame_times_ms.push_back(total_ms);
            preprocess_times_ms.push_back(pre_ms);
            palm_infer_times_ms.push_back(palm_ms);
            postprocess_times_ms.push_back(0);
            hand_infer_times_ms.push_back(0);

            if (!args.headless)
            {
                auto now = std::chrono::high_resolution_clock::now();
                double dt = std::chrono::duration<double>(now - prev_time).count();
                double fps_inst = 1.0 / std::max(dt, 1e-6);
                fps_smoothed = fps_smoothed > 0 ? 0.1 * fps_inst + 0.9 * fps_smoothed : fps_inst;
                prev_time = now;

                cv::putText(frame, "FPS: " + std::to_string(static_cast<int>(fps_smoothed)),
                            cv::Point(10, 30), cv::FONT_HERSHEY_SIMPLEX, 1.0, COLOR_FPS, 2);
                cv::imshow("Gesture Detection (C++)", frame);
                int key = cv::waitKey(single_image ? 0 : 1) & 0xFF;
                if (key == 'q')
                    break;
            }
            if (single_image)
                break;
            continue;
        }

        // 4. Denormalize detections to image pixel space
        denormalize_detections(palm_detections, palm_pre.inv_scale,
                               palm_pre.pad_y, palm_pre.pad_x);

        // Limit to MAX_HANDS
        if (palm_detections.size() > MAX_HANDS)
            palm_detections.resize(MAX_HANDS);

        auto t_postprocess_start = std::chrono::high_resolution_clock::now();

        // 5. For each palm: extract ROI, run hand landmark, classify gesture
        cv::Mat display = frame.clone();
        std::string hand_input_name = hand_model.get_infer_model()->get_input_names()[0];
        bool any_valid_hand = false;
        double hand_infer_accum_ms = 0.0;

        for (size_t p = 0; p < palm_detections.size(); p++)
        {
            // Draw palm detection box
            draw_palm_box(display, palm_detections[p]);

            // Convert palm detection to oriented ROI
            HandROI roi = detection2roi(palm_detections[p]);

            // Extract oriented crop via affine warp
            cv::Mat crop = extract_roi(rgb, roi);

            // The model expects uint8 input — convert back from float [0,1]
            cv::Mat crop_uint8;
            crop.convertTo(crop_uint8, CV_8UC3, 255.0);

            if (!crop_uint8.isContinuous())
                crop_uint8 = crop_uint8.clone();

            // Run hand landmark inference
            auto t_hand_start = std::chrono::high_resolution_clock::now();
            InputMap hand_inputs;
            hand_inputs[hand_input_name] = {crop_uint8};

            HandResult hand_result;
            bool hand_valid = false;

            hand_model.infer(hand_inputs,
                [&](const hailort::AsyncInferCompletionInfo& info,
                    const std::vector<std::pair<uint8_t*, hailo_vstream_info_t>>& output_data,
                    const std::vector<std::shared_ptr<uint8_t>>&) {
                    if (info.status != HAILO_SUCCESS)
                    {
                        std::cerr << "Hand inference failed: " << info.status << std::endl;
                        return;
                    }

                    if (!hand_mapped)
                    {
                        hand_map = map_hand_outputs(output_data);
                        hand_mapped = true;

                        // Debug: print tensor mapping
                        std::cout << "Hand model output tensors:" << std::endl;
                        for (int i = 0; i < static_cast<int>(output_data.size()); i++)
                        {
                            auto& oi = output_data[i].second;
                            size_t total = oi.shape.height * oi.shape.width * oi.shape.features;
                            std::cout << "  [" << i << "] " << oi.name
                                      << " (" << oi.shape.height << "x" << oi.shape.width
                                      << "x" << oi.shape.features << " = " << total << ")"
                                      << std::endl;
                        }
                        std::cout << "  landmarks_idx=" << hand_map.landmarks_idx
                                  << " flag_idx=" << hand_map.flag_idx
                                  << " handedness_idx=" << hand_map.handedness_idx << std::endl;
                    }

                    if (hand_map.landmarks_idx < 0)
                        return;

                    const float* lm_data = reinterpret_cast<const float*>(
                        output_data[hand_map.landmarks_idx].first);
                    size_t lm_total = output_data[hand_map.landmarks_idx].second.shape.height *
                                     output_data[hand_map.landmarks_idx].second.shape.width *
                                     output_data[hand_map.landmarks_idx].second.shape.features;

                    const float* flag_data = (hand_map.flag_idx >= 0)
                        ? reinterpret_cast<const float*>(output_data[hand_map.flag_idx].first)
                        : nullptr;

                    const float* hand_data = (hand_map.handedness_idx >= 0)
                        ? reinterpret_cast<const float*>(output_data[hand_map.handedness_idx].first)
                        : nullptr;

                    hand_result = decode_hand_outputs(lm_data, lm_total, flag_data, hand_data);
                    hand_valid = true;
                });
            hand_model.wait_for_last_job();
            auto t_hand_end = std::chrono::high_resolution_clock::now();
            hand_infer_accum_ms += std::chrono::duration<double, std::milli>(t_hand_end - t_hand_start).count();

            if (!hand_valid || hand_result.flag < HAND_FLAG_THRESHOLD)
                continue;

            any_valid_hand = true;

            // Denormalize landmarks to image pixel coords
            denormalize_landmarks(hand_result, roi.inv_affine);

            // Classify gesture
            hand_result.gesture = classify_gesture(hand_result.landmarks);

            // Draw hand
            draw_hand(display, hand_result);
        }

        // Accumulate benchmark stats
        auto t_end_frame = std::chrono::high_resolution_clock::now();
        total_frames++;
        if (any_valid_hand) frames_with_hands++;
        double pre_ms = std::chrono::duration<double, std::milli>(t_preprocess - t_start).count();
        double palm_ms = std::chrono::duration<double, std::milli>(t_palm_infer - t_preprocess).count();
        double post_ms = std::chrono::duration<double, std::milli>(t_postprocess_start - t_palm_infer).count()
                       + std::chrono::duration<double, std::milli>(t_end_frame - t_postprocess_start).count()
                       - hand_infer_accum_ms;
        double total_ms = std::chrono::duration<double, std::milli>(t_end_frame - t_start).count();
        frame_times_ms.push_back(total_ms);
        preprocess_times_ms.push_back(pre_ms);
        palm_infer_times_ms.push_back(palm_ms);
        postprocess_times_ms.push_back(post_ms);
        hand_infer_times_ms.push_back(hand_infer_accum_ms);

        if (args.headless && total_frames % 100 == 0)
            std::cout << "  Processed " << total_frames << " frames... FPS: "
                      << static_cast<int>(fps_smoothed) << std::endl;

        // FPS calculation
        auto now = std::chrono::high_resolution_clock::now();
        double dt = std::chrono::duration<double>(now - prev_time).count();
        double fps_inst = 1.0 / std::max(dt, 1e-6);
        fps_smoothed = fps_smoothed > 0 ? 0.1 * fps_inst + 0.9 * fps_smoothed : fps_inst;
        prev_time = now;

        if (!args.headless)
        {
            double frame_ms = std::chrono::duration<double, std::milli>(now - t_start).count();
            cv::putText(display, "FPS: " + std::to_string(static_cast<int>(fps_smoothed)),
                        cv::Point(10, 30), cv::FONT_HERSHEY_SIMPLEX, 1.0, COLOR_FPS, 2);
            cv::putText(display, "Frame: " + std::to_string(static_cast<int>(frame_ms)) + "ms",
                        cv::Point(10, 65), cv::FONT_HERSHEY_SIMPLEX, 0.7, COLOR_FPS, 2);
            cv::putText(display, "Palms: " + std::to_string(palm_detections.size()),
                        cv::Point(10, 95), cv::FONT_HERSHEY_SIMPLEX, 0.7, COLOR_FPS, 2);

            cv::imshow("Gesture Detection (C++)", display);
            int key = cv::waitKey(single_image ? 0 : 1) & 0xFF;
            if (key == 'q')
                break;
        }

        if (single_image)
            break;
    }

    if (!single_image)
        cap.release();
    if (!args.headless)
        cv::destroyAllWindows();

    // Print benchmark report
    auto wall_end = std::chrono::high_resolution_clock::now();
    double wall_time = std::chrono::duration<double>(wall_end - wall_start).count();

    if (!frame_times_ms.empty())
    {
        auto mean = [](const std::vector<double>& v) {
            double sum = 0; for (auto x : v) sum += x; return sum / v.size();
        };
        auto median = [](std::vector<double> v) {
            std::sort(v.begin(), v.end());
            size_t n = v.size();
            return (n % 2 == 0) ? (v[n/2-1] + v[n/2]) / 2.0 : v[n/2];
        };

        std::cout << "\n";
        std::cout << "=======================================================\n";
        std::cout << "  BENCHMARK REPORT - C++ Standalone (HailoRT + OpenCV)\n";
        std::cout << "=======================================================\n\n";

        std::cout << "--- Performance ---\n";
        std::cout << "  Frames:        " << total_frames << "\n";
        printf("  Wall time:     %.1f s\n", wall_time);
        printf("  Avg FPS:       %.1f\n", total_frames / wall_time);
        printf("  Avg frame:     %.1f ms\n", mean(frame_times_ms));
        printf("  Median frame:  %.1f ms\n", median(frame_times_ms));

        if (frame_times_ms.size() > 10)
        {
            auto sorted = frame_times_ms;
            std::sort(sorted.begin(), sorted.end());
            double p5 = sorted[static_cast<size_t>(sorted.size() * 0.05)];
            double p95 = sorted[static_cast<size_t>(sorted.size() * 0.95)];
            printf("  P5 frame:      %.1f ms (best)\n", p5);
            printf("  P95 frame:     %.1f ms (worst)\n", p95);
        }

        std::cout << "\n--- Timing Breakdown ---\n";
        printf("  Pre-process (C++)           avg %5.1f ms  med %5.1f ms\n",
               mean(preprocess_times_ms), median(preprocess_times_ms));
        printf("  Palm detect (Hailo)         avg %5.1f ms  med %5.1f ms\n",
               mean(palm_infer_times_ms), median(palm_infer_times_ms));
        printf("  Post-process (C++)          avg %5.1f ms  med %5.1f ms\n",
               mean(postprocess_times_ms), median(postprocess_times_ms));
        printf("  Hand landmark (Hailo)       avg %5.1f ms  med %5.1f ms\n",
               mean(hand_infer_times_ms), median(hand_infer_times_ms));

        double total_infer = mean(palm_infer_times_ms) + mean(hand_infer_times_ms);
        double total_cpp = mean(preprocess_times_ms) + mean(postprocess_times_ms);
        printf("  Hailo inference total       avg %5.1f ms\n", total_infer);
        printf("  C++ pre/post total          avg %5.1f ms\n", total_cpp);

        std::cout << "\n--- Detection ---\n";
        double det_pct = total_frames > 0 ? 100.0 * frames_with_hands / total_frames : 0;
        printf("  Frames w/hand: %d/%d (%.0f%%)\n", frames_with_hands, total_frames, det_pct);
        std::cout << "\n";
    }

    std::cout << "Done." << std::endl;
    return 0;
}
