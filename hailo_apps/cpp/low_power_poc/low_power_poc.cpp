/**
 * Hailo Low-Power Mode Proof of Concept (C++)
 *
 * Benchmarks a Hailo-8 M.2 module across three states:
 *   1. Active inference (baseline)
 *   2. Sleep mode (low power)
 *   3. Active inference (post-wake validation)
 *
 * Measures: power consumption, sleep/wake transition times, FPS.
 * Validates the device recovers to the same performance after waking.
 *
 * Build:
 *   cd hailo_apps/cpp/low_power_poc && bash build.sh
 *
 * Usage:
 *   ./build/low_power_poc
 *   ./build/low_power_poc --inference-duration 20 --sleep-duration 30
 */

#include "hailo/hailort.hpp"
#include "hailo/device.hpp"

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <numeric>
#include <regex>
#include <sstream>
#include <string>
#include <sys/types.h>
#include <sys/wait.h>
#include <thread>
#include <unistd.h>
#include <vector>

using Clock = std::chrono::steady_clock;
using namespace hailort;
namespace fs = std::filesystem;

// ---------------------------------------------------------------------------
// Data structures
// ---------------------------------------------------------------------------

struct PowerStats {
    double avg      = 0.0;
    double min_val  = 0.0;
    double max_val  = 0.0;
    int    samples  = 0;

    std::string as_str() const {
        if (samples == 0) return "N/A";
        std::ostringstream os;
        os << std::fixed << std::setprecision(3)
           << avg << " / " << min_val << " / " << max_val << " W";
        return os.str();
    }
};

struct PhaseResult {
    double     fps   = 0.0;
    PowerStats power;
};

struct Report {
    std::string device_id;
    std::string device_arch;
    std::string fw_version;
    std::string model    = "yolov6n (640x640)";
    std::string video    = "example_640.mp4";
    int inference_duration_s = 0;
    int sleep_duration_s     = 0;
    double idle_power_w      = 0.0;
    PhaseResult baseline;
    double sleep_entry_ms    = 0.0;
    PowerStats  sleep_power;
    double wake_exit_ms      = 0.0;
    PhaseResult postwake;
    double fps_delta_pct     = -1.0;
    bool   fps_pass          = false;
    double power_reduction_pct = 0.0;
    bool   device_alive_after  = false;
};

// ---------------------------------------------------------------------------
// CLI args
// ---------------------------------------------------------------------------

struct Args {
    int    inference_duration = 15;
    int    sleep_duration     = 40;
    double fps_threshold      = 5.0;
    std::string output_json   = "low_power_report.json";
    std::string inference_cmd; // path to detection_simple or equivalent
};

static Args parse_args(int argc, char** argv) {
    Args a;

    // Find the repo root: walk up from executable to find setup_env.sh
    fs::path exe_dir = fs::canonical("/proc/self/exe").parent_path();
    fs::path repo_root;
    for (auto p = exe_dir; p != p.root_path(); p = p.parent_path()) {
        if (fs::exists(p / "setup_env.sh")) {
            repo_root = p;
            break;
        }
    }

    if (!repo_root.empty()) {
        // Default inference command: use the Python detection_simple via the venv
        a.inference_cmd = "source " + (repo_root / "setup_env.sh").string()
            + " && python3 -m hailo_apps.python.pipeline_apps.detection_simple.detection_simple"
              " --disable-sync --show-fps";
    }

    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--inference-duration" && i + 1 < argc) a.inference_duration = std::atoi(argv[++i]);
        else if (arg == "--sleep-duration" && i + 1 < argc) a.sleep_duration = std::atoi(argv[++i]);
        else if (arg == "--fps-threshold" && i + 1 < argc) a.fps_threshold = std::atof(argv[++i]);
        else if (arg == "--output-json" && i + 1 < argc) a.output_json = argv[++i];
        else if (arg == "--inference-cmd" && i + 1 < argc) a.inference_cmd = argv[++i];
        else if (arg == "--help" || arg == "-h") {
            std::cout << "Usage: low_power_poc [OPTIONS]\n"
                      << "  --inference-duration <s>  Duration of each inference phase (default: 15)\n"
                      << "  --sleep-duration <s>      Sleep mode duration (default: 40)\n"
                      << "  --fps-threshold <pct>     Max allowed FPS delta % (default: 5.0)\n"
                      << "  --output-json <path>      JSON report path (default: low_power_report.json)\n"
                      << "  --inference-cmd <cmd>     Custom inference command\n";
            std::exit(0);
        }
    }
    return a;
}

// ---------------------------------------------------------------------------
// Logging
// ---------------------------------------------------------------------------

static void poc_log(const std::string& msg) {
    std::cout << "[PoC] " << msg << std::endl;
}

// ---------------------------------------------------------------------------
// Shell command execution
// ---------------------------------------------------------------------------

struct CmdResult {
    int         rc = -1;
    std::string output;
};

static CmdResult run_cmd(const std::string& cmd, int timeout_s = 15) {
    CmdResult r;
    std::string full_cmd = cmd + " 2>&1";
    FILE* pipe = popen(full_cmd.c_str(), "r");
    if (!pipe) return r;

    std::array<char, 4096> buf;
    while (fgets(buf.data(), buf.size(), pipe)) {
        r.output += buf.data();
    }
    int status = pclose(pipe);
    r.rc = WIFEXITED(status) ? WEXITSTATUS(status) : -1;
    (void)timeout_s; // popen doesn't support timeout natively; keep param for API compat
    return r;
}

// ---------------------------------------------------------------------------
// Architecture name helper
// ---------------------------------------------------------------------------

static std::string arch_to_string(hailo_device_architecture_t arch) {
    switch (arch) {
        case HAILO_ARCH_HAILO8:    return "HAILO8";
        case HAILO_ARCH_HAILO8L:   return "HAILO8L";
        case HAILO_ARCH_HAILO10H:  return "HAILO10H";
        case HAILO_ARCH_HAILO15H:  return "HAILO15H";
        case HAILO_ARCH_HAILO8_A0: return "HAILO8_A0";
        default:                   return "UNKNOWN";
    }
}

static std::string arch_to_cli_flag(hailo_device_architecture_t arch) {
    switch (arch) {
        case HAILO_ARCH_HAILO8:    return "hailo8";
        case HAILO_ARCH_HAILO8L:   return "hailo8l";
        case HAILO_ARCH_HAILO10H:  return "hailo10h";
        case HAILO_ARCH_HAILO15H:  return "hailo15h";
        case HAILO_ARCH_HAILO8_A0: return "hailo8";
        default:                   return "";
    }
}

// ---------------------------------------------------------------------------
// Power measurement helpers
// ---------------------------------------------------------------------------

static double measure_single_power(Device& device) {
    auto result = device.power_measurement(HAILO_DVM_OPTIONS_AUTO, HAILO_POWER_MEASUREMENT_TYPES__AUTO);
    if (!result) {
        poc_log("  WARNING: Single power measurement failed (status " + std::to_string(result.status()) + ")");
        return -1.0;
    }
    return static_cast<double>(result.value());
}

static PowerStats measure_periodic_power(Device& device, int duration_s) {
    PowerStats stats;
    std::vector<double> samples;

    // Stop any previous measurement
    device.stop_power_measurement();

    // Configure and start
    auto st = device.set_power_measurement(
        HAILO_MEASUREMENT_BUFFER_INDEX_0,
        HAILO_DVM_OPTIONS_AUTO,
        HAILO_POWER_MEASUREMENT_TYPES__AUTO);
    if (HAILO_SUCCESS != st) {
        poc_log("  WARNING: set_power_measurement failed (status " + std::to_string(st) + ")");
        return stats;
    }

    st = device.start_power_measurement(
        HAILO_AVERAGE_FACTOR_1, HAILO_SAMPLING_PERIOD_1100US);
    if (HAILO_SUCCESS != st) {
        poc_log("  WARNING: start_power_measurement failed (status " + std::to_string(st) + ")");
        return stats;
    }

    for (int i = 0; i < duration_s; ++i) {
        std::this_thread::sleep_for(std::chrono::seconds(1));
        auto meas = device.get_power_measurement(HAILO_MEASUREMENT_BUFFER_INDEX_0, true);
        if (meas) {
            samples.push_back(static_cast<double>(meas->average_value));
        } else {
            poc_log("  WARNING: power sample " + std::to_string(i)
                    + " failed (status " + std::to_string(meas.status()) + ")");
        }
    }

    device.stop_power_measurement();

    if (samples.empty()) return stats;

    // Log samples
    std::ostringstream ss;
    ss << "  Collected " << samples.size() << " power samples: [";
    for (size_t i = 0; i < samples.size(); ++i) {
        if (i > 0) ss << ", ";
        ss << std::fixed << std::setprecision(3) << samples[i];
    }
    ss << "]";
    poc_log(ss.str());

    stats.avg     = std::accumulate(samples.begin(), samples.end(), 0.0) / samples.size();
    stats.min_val = *std::min_element(samples.begin(), samples.end());
    stats.max_val = *std::max_element(samples.begin(), samples.end());
    stats.samples = static_cast<int>(samples.size());
    return stats;
}

// ---------------------------------------------------------------------------
// Video preparation (looped video for high-speed decoding)
// ---------------------------------------------------------------------------

static std::string prepare_video(int inference_duration_s, int margin_s = 5) {
    const std::string src = "/usr/local/hailo/resources/videos/example_640.mp4";
    if (!fs::exists(src)) {
        poc_log("  WARNING: Source video not found: " + src);
        return "";
    }

    // Get source frame count
    auto probe_result = run_cmd(
        "ffprobe -v error -count_frames -select_streams v:0 "
        "-show_entries stream=nb_read_frames -of csv=p=0 \"" + src + "\"", 30);

    int src_frames = 0;
    if (probe_result.rc == 0 && !probe_result.output.empty()) {
        src_frames = std::atoi(probe_result.output.c_str());
    }
    if (src_frames <= 0) {
        poc_log("  WARNING: Could not get frame count, estimating from duration");
        auto dur_result = run_cmd(
            "ffprobe -v error -show_entries format=duration -of csv=p=0 \"" + src + "\"");
        if (dur_result.rc == 0 && !dur_result.output.empty()) {
            src_frames = static_cast<int>(std::atof(dur_result.output.c_str()) * 30);
        }
        if (src_frames <= 0) return "";
    }

    const int estimated_fps = 350;
    const int target_frames = (inference_duration_s + margin_s) * estimated_fps;
    const int loops = static_cast<int>(std::ceil(static_cast<double>(target_frames) / src_frames));

    poc_log("  Source: " + std::to_string(src_frames) + " frames. Need ~"
            + std::to_string(target_frames) + " frames for "
            + std::to_string(inference_duration_s) + "+" + std::to_string(margin_s)
            + "s @ ~" + std::to_string(estimated_fps) + " FPS. Loops: " + std::to_string(loops));

    if (loops <= 1) return src;

    // Output next to our binary
    fs::path exe_dir = fs::canonical("/proc/self/exe").parent_path();
    fs::path out_path = exe_dir / ("example_640_looped_" + std::to_string(loops) + "x.mp4");

    if (fs::exists(out_path)) {
        poc_log("  Reusing existing looped video: " + out_path.string());
        return out_path.string();
    }

    // Create concat list
    std::string concat_path = "/tmp/poc_concat_list.txt";
    {
        std::ofstream concat(concat_path);
        for (int i = 0; i < loops; ++i) {
            concat << "file '" << src << "'\n";
        }
    }

    poc_log("  Creating looped video: " + std::to_string(loops) + "x "
            + std::to_string(src_frames) + " frames = "
            + std::to_string(loops * src_frames) + " frames");

    auto ffmpeg_result = run_cmd(
        "ffmpeg -y -f concat -safe 0 -i \"" + concat_path
        + "\" -c copy \"" + out_path.string() + "\"", 30);
    std::remove(concat_path.c_str());

    if (ffmpeg_result.rc != 0) {
        poc_log("  WARNING: ffmpeg failed: " + ffmpeg_result.output);
        return "";
    }

    poc_log("  Looped video ready: " + out_path.string());
    return out_path.string();
}

// ---------------------------------------------------------------------------
// Inference subprocess management
// ---------------------------------------------------------------------------

struct InferenceProcess {
    pid_t       pid          = -1;
    Clock::time_point start;
    std::string stdout_path;
    std::string stderr_path;
};

static InferenceProcess launch_inference(const Args& args, const std::string& video_path) {
    InferenceProcess ip;

    // Create temp files for stdout/stderr
    char stdout_tmpl[] = "/tmp/poc_stdout_XXXXXX";
    char stderr_tmpl[] = "/tmp/poc_stderr_XXXXXX";
    int fd_out = mkstemp(stdout_tmpl);
    int fd_err = mkstemp(stderr_tmpl);
    ip.stdout_path = stdout_tmpl;
    ip.stderr_path = stderr_tmpl;

    std::string cmd = args.inference_cmd;
    if (!video_path.empty()) {
        cmd += " --input " + video_path;
    }

    poc_log("  Launching inference subprocess...");
    poc_log("  CMD: " + cmd);

    ip.pid = fork();
    if (ip.pid == 0) {
        // Child: redirect stdout/stderr to temp files
        dup2(fd_out, STDOUT_FILENO);
        dup2(fd_err, STDERR_FILENO);
        close(fd_out);
        close(fd_err);
        // Create new process group
        setpgid(0, 0);
        // Execute via bash (needed for 'source setup_env.sh &&' chain)
        execl("/bin/bash", "bash", "-c", cmd.c_str(), nullptr);
        _exit(127);
    }

    close(fd_out);
    close(fd_err);

    // Parent: set child's process group
    setpgid(ip.pid, ip.pid);
    ip.start = Clock::now();
    return ip;
}

static std::string read_file_contents(const std::string& path) {
    std::ifstream f(path);
    if (!f) return "";
    return std::string(std::istreambuf_iterator<char>(f), {});
}

struct InferenceOutput {
    std::string stdout_text;
    std::string stderr_text;
};

static InferenceOutput stop_inference(InferenceProcess& ip) {
    InferenceOutput out;

    if (ip.pid > 0) {
        int status = 0;
        pid_t ret = waitpid(ip.pid, &status, WNOHANG);
        if (ret == 0) {
            // Still running — send SIGTERM to process group
            poc_log("  Sending SIGTERM to inference subprocess...");
            kill(-ip.pid, SIGTERM);

            // Wait up to 5s
            for (int i = 0; i < 50 && waitpid(ip.pid, &status, WNOHANG) == 0; ++i) {
                std::this_thread::sleep_for(std::chrono::milliseconds(100));
            }

            ret = waitpid(ip.pid, &status, WNOHANG);
            if (ret == 0) {
                poc_log("  Sending SIGINT...");
                kill(-ip.pid, SIGINT);
                for (int i = 0; i < 30 && waitpid(ip.pid, &status, WNOHANG) == 0; ++i) {
                    std::this_thread::sleep_for(std::chrono::milliseconds(100));
                }

                ret = waitpid(ip.pid, &status, WNOHANG);
                if (ret == 0) {
                    poc_log("  WARNING: Grace period expired, sending SIGKILL.");
                    kill(-ip.pid, SIGKILL);
                    waitpid(ip.pid, &status, 0);
                }
            }
        }
    }

    out.stdout_text = read_file_contents(ip.stdout_path);
    out.stderr_text = read_file_contents(ip.stderr_path);
    std::remove(ip.stdout_path.c_str());
    std::remove(ip.stderr_path.c_str());
    return out;
}

// ---------------------------------------------------------------------------
// FPS parsing
// ---------------------------------------------------------------------------

struct FPSResult {
    double frame_count_fps   = 0.0;
    double fpsdisplaysink_fps = 0.0;
};

static FPSResult parse_fps(const std::string& stdout_text, const std::string& stderr_text, double elapsed_s) {
    FPSResult fps;
    std::string combined = stdout_text + "\n" + stderr_text;

    // Primary: frame count / elapsed
    std::regex fc_re(R"(Frame count:\s*(\d+))");
    int max_frames = 0;
    for (std::sregex_iterator it(combined.begin(), combined.end(), fc_re), end; it != end; ++it) {
        int fc = std::stoi((*it)[1].str());
        max_frames = std::max(max_frames, fc);
    }
    if (max_frames > 0 && elapsed_s > 0) {
        fps.frame_count_fps = max_frames / elapsed_s;
        poc_log("  Frame count FPS: " + std::to_string(max_frames) + " frames / "
                + std::to_string(elapsed_s).substr(0, 5) + "s = "
                + std::to_string(fps.frame_count_fps).substr(0, 6) + " FPS");
    }

    // Secondary: fpsdisplaysink
    std::regex sink_re(R"(FPS measurement:\s*([\d.]+),\s*drop=([\d.]+),\s*avg=([\d.]+))");
    double last_avg = 0.0;
    int sink_count = 0;
    for (std::sregex_iterator it(combined.begin(), combined.end(), sink_re), end; it != end; ++it) {
        last_avg = std::stod((*it)[3].str());
        ++sink_count;
    }
    if (sink_count > 0) {
        fps.fpsdisplaysink_fps = last_avg;
        poc_log("  fpsdisplaysink FPS: " + std::to_string(last_avg).substr(0, 6)
                + " (from " + std::to_string(sink_count) + " reports)");
    }

    return fps;
}

// ---------------------------------------------------------------------------
// Run inference phase (inference + power measurement)
// ---------------------------------------------------------------------------

static PhaseResult run_inference_phase(Device& device, const Args& args,
                                       int duration_s, const std::string& phase_name,
                                       const std::string& video_path)
{
    PhaseResult result;
    poc_log("--- " + phase_name + ": inference for " + std::to_string(duration_s) + "s ---");

    auto ip = launch_inference(args, video_path);

    // 3s warmup before power measurement
    std::this_thread::sleep_for(std::chrono::seconds(3));

    int power_duration = std::max(1, duration_s - 3);
    poc_log("  Measuring power for " + std::to_string(power_duration)
            + "s (after 3s pipeline warmup)...");
    result.power = measure_periodic_power(device, power_duration);
    poc_log("  Power: " + result.power.as_str());

    auto output = stop_inference(ip);
    auto elapsed = std::chrono::duration<double>(Clock::now() - ip.start).count();

    auto fps = parse_fps(output.stdout_text, output.stderr_text, elapsed);

    std::ostringstream log_msg;
    log_msg << std::fixed << std::setprecision(1)
            << "  Elapsed: " << elapsed << "s"
            << " | FPS (frame-count): " << fps.frame_count_fps
            << " | FPS (sink): " << fps.fpsdisplaysink_fps;
    poc_log(log_msg.str());

    result.fps = (fps.frame_count_fps > 0) ? fps.frame_count_fps : fps.fpsdisplaysink_fps;
    return result;
}

// ---------------------------------------------------------------------------
// Report printing & JSON output
// ---------------------------------------------------------------------------

static void print_report(const Report& r, double fps_threshold) {
    const int w = 60;
    auto line = [&]() { std::cout << std::string(w, '-') << "\n"; };
    auto dline = [&]() { std::cout << std::string(w, '=') << "\n"; };

    std::cout << "\n";
    dline();
    std::cout << "       HAILO LOW-POWER MODE PoC REPORT (C++)\n";
    dline();
    std::cout << std::fixed << std::setprecision(3);
    std::cout << " Device              : " << r.device_arch << " (M.2, PCIe)\n";
    std::cout << " Device ID           : " << r.device_id << "\n";
    std::cout << " Firmware            : " << r.fw_version << "\n";
    std::cout << " Model               : " << r.model << "\n";
    std::cout << " Video               : " << r.video << "\n";
    std::cout << " Inference duration  : " << r.inference_duration_s << "s per phase\n";
    std::cout << " Sleep duration      : " << r.sleep_duration_s << "s\n";
    line();
    std::cout << std::left << std::setw(22) << " PHASE"
              << "| " << std::right << std::setw(7) << "FPS"
              << " | Power (avg/min/max)\n";
    line();
    std::cout << std::left << std::setw(22) << " Idle (startup)"
              << "| " << std::right << std::setw(7) << "—"
              << " | " << r.idle_power_w << " W\n";
    std::cout << std::left << std::setw(22) << " Baseline infer"
              << "| " << std::right << std::setw(7) << std::setprecision(1) << r.baseline.fps
              << " | " << r.baseline.power.as_str() << "\n";
    std::cout << std::left << std::setw(22) << " Sleep mode"
              << "| " << std::right << std::setw(7) << "—"
              << " | " << r.sleep_power.as_str() << "\n";
    std::cout << std::left << std::setw(22) << " Post-wake infer"
              << "| " << std::right << std::setw(7) << r.postwake.fps
              << " | " << r.postwake.power.as_str() << "\n";
    line();
    std::cout << std::left << std::setw(22) << " TRANSITIONS"
              << "| " << std::right << std::setw(10) << "Time (ms)" << "\n";
    line();
    std::cout << std::setprecision(2);
    std::cout << std::left << std::setw(22) << " Sleep entry"
              << "| " << std::right << std::setw(10)
              << (r.sleep_entry_ms >= 0 ? std::to_string(r.sleep_entry_ms).substr(0,7) : "FAILED") << "\n";
    std::cout << std::left << std::setw(22) << " Wake exit"
              << "| " << std::right << std::setw(10)
              << (r.wake_exit_ms >= 0 ? std::to_string(r.wake_exit_ms).substr(0,7) : "FAILED") << "\n";
    line();
    std::cout << std::left << std::setw(22) << " VALIDATION"
              << "| " << "Result\n";
    line();

    if (r.fps_delta_pct >= 0) {
        std::cout << std::left << std::setw(22) << " FPS delta"
                  << "| " << std::setprecision(1) << r.fps_delta_pct << "% -> "
                  << (r.fps_pass ? "PASS" : "FAIL")
                  << " (<" << fps_threshold << "%)\n";
    } else {
        std::cout << std::left << std::setw(22) << " FPS delta"
                  << "| N/A (missing FPS data)\n";
    }

    if (r.power_reduction_pct > 0) {
        std::cout << std::left << std::setw(22) << " Power reduction"
                  << "| " << std::setprecision(1) << r.power_reduction_pct
                  << "% (sleep vs idle)\n";
    } else {
        std::cout << std::left << std::setw(22) << " Power reduction"
                  << "| N/A\n";
    }

    std::cout << std::left << std::setw(22) << " Device alive"
              << "| " << (r.device_alive_after ? "YES" : "NO") << "\n";
    dline();
}

static void write_json_report(const Report& r, const std::string& path) {
    std::ofstream f(path);
    f << std::fixed << std::setprecision(3);
    f << "{\n"
      << "  \"device_id\": \"" << r.device_id << "\",\n"
      << "  \"device_arch\": \"" << r.device_arch << "\",\n"
      << "  \"fw_version\": \"" << r.fw_version << "\",\n"
      << "  \"model\": \"" << r.model << "\",\n"
      << "  \"video\": \"" << r.video << "\",\n"
      << "  \"inference_duration_s\": " << r.inference_duration_s << ",\n"
      << "  \"sleep_duration_s\": " << r.sleep_duration_s << ",\n"
      << "  \"idle_power_w\": " << r.idle_power_w << ",\n"
      << "  \"baseline\": {\n"
      << "    \"fps\": " << std::setprecision(1) << r.baseline.fps << ",\n"
      << "    \"power_avg_w\": " << std::setprecision(3) << r.baseline.power.avg << ",\n"
      << "    \"power_min_w\": " << r.baseline.power.min_val << ",\n"
      << "    \"power_max_w\": " << r.baseline.power.max_val << "\n"
      << "  },\n"
      << "  \"sleep\": {\n"
      << "    \"entry_ms\": " << std::setprecision(2) << r.sleep_entry_ms << ",\n"
      << "    \"power_avg_w\": " << std::setprecision(3) << r.sleep_power.avg << ",\n"
      << "    \"power_min_w\": " << r.sleep_power.min_val << ",\n"
      << "    \"power_max_w\": " << r.sleep_power.max_val << ",\n"
      << "    \"exit_ms\": " << std::setprecision(2) << r.wake_exit_ms << "\n"
      << "  },\n"
      << "  \"postwake\": {\n"
      << "    \"fps\": " << std::setprecision(1) << r.postwake.fps << ",\n"
      << "    \"power_avg_w\": " << std::setprecision(3) << r.postwake.power.avg << ",\n"
      << "    \"power_min_w\": " << r.postwake.power.min_val << ",\n"
      << "    \"power_max_w\": " << r.postwake.power.max_val << "\n"
      << "  },\n"
      << "  \"validation\": {\n"
      << "    \"fps_delta_pct\": " << std::setprecision(1) << r.fps_delta_pct << ",\n"
      << "    \"fps_pass\": " << (r.fps_pass ? "true" : "false") << ",\n"
      << "    \"power_reduction_pct\": " << r.power_reduction_pct << ",\n"
      << "    \"device_alive_after\": " << (r.device_alive_after ? "true" : "false") << "\n"
      << "  }\n"
      << "}\n";
    poc_log("  JSON report written to " + path);
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

int main(int argc, char** argv) {
    Args args = parse_args(argc, argv);

    poc_log(std::string(60, '='));
    poc_log("   HAILO LOW-POWER MODE PoC (C++)");
    poc_log(std::string(60, '='));

    // ---- Phase 1: Pre-flight ----
    poc_log("\n[Phase 1] Pre-flight check");

    auto device_expected = Device::create();
    if (!device_expected) {
        poc_log("FATAL: Failed to create device (status "
                + std::to_string(device_expected.status()) + ")");
        return 1;
    }
    auto device = device_expected.release();

    auto identity = device->identify();
    if (!identity) {
        poc_log("FATAL: Failed to identify device");
        return 1;
    }

    Report report;
    auto& id = identity.value();
    report.device_arch = arch_to_string(id.device_architecture);
    report.fw_version = std::to_string(id.fw_version.major) + "."
                      + std::to_string(id.fw_version.minor) + "."
                      + std::to_string(id.fw_version.revision);
    report.device_id = device->get_dev_id();
    report.inference_duration_s = args.inference_duration;
    report.sleep_duration_s = args.sleep_duration;

    // Inject --arch flag into inference command to override env var
    auto cli_arch = arch_to_cli_flag(id.device_architecture);
    if (!cli_arch.empty()) {
        args.inference_cmd += " --arch " + cli_arch;
    }

    poc_log("  Device: " + report.device_id + ", Arch: " + report.device_arch
            + ", FW: " + report.fw_version);

    double idle_power = measure_single_power(*device);
    if (idle_power >= 0) {
        report.idle_power_w = idle_power;
        std::ostringstream ss;
        ss << std::fixed << std::setprecision(3) << idle_power;
        poc_log("  Idle power: " + ss.str() + " W");
    } else {
        poc_log("  WARNING: Power measurement not available — continuing without power data.");
    }

    // Prepare looped video
    poc_log("  Preparing test video...");
    std::string video_path = prepare_video(args.inference_duration);
    if (!video_path.empty()) {
        poc_log("  Using video: " + video_path);
    } else {
        poc_log("  WARNING: Using default video (may rewind during test)");
    }

    // ---- Phase 2: Baseline inference ----
    poc_log("\n[Phase 2] Baseline inference (" + std::to_string(args.inference_duration) + "s)");
    report.baseline = run_inference_phase(*device, args, args.inference_duration, "BASELINE", video_path);

    // ---- Phase 3: Enter sleep ----
    poc_log("\n[Phase 3] Entering sleep mode");
    {
        auto tic = Clock::now();
        auto st = device->set_sleep_state(HAILO_SLEEP_STATE_SLEEPING);
        auto toc = Clock::now();
        if (HAILO_SUCCESS == st) {
            report.sleep_entry_ms = std::chrono::duration<double, std::milli>(toc - tic).count();
            std::ostringstream ss;
            ss << std::fixed << std::setprecision(2) << report.sleep_entry_ms;
            poc_log("  Sleep entry time: " + ss.str() + " ms");
        } else {
            poc_log("  RISK RAISED: Sleep entry failed (status " + std::to_string(st) + ")");
            poc_log("  Continuing with remaining phases...");
            report.sleep_entry_ms = -1;
        }
    }

    // ---- Phase 4: Sleep mode power measurement ----
    if (report.sleep_entry_ms >= 0) {
        poc_log("\n[Phase 4] Sleep mode (" + std::to_string(args.sleep_duration) + "s total)");
        const int stabilize_s = 3;
        const int measure_s = args.sleep_duration - stabilize_s;
        poc_log("  Waiting " + std::to_string(stabilize_s) + "s for power stabilization...");
        std::this_thread::sleep_for(std::chrono::seconds(stabilize_s));

        poc_log("  Measuring sleep power for " + std::to_string(measure_s) + "s...");
        report.sleep_power = measure_periodic_power(*device, measure_s);

        if (report.sleep_power.samples == 0) {
            // Fallback: single measurements
            poc_log("  Periodic measurement failed during sleep. Trying single samples...");
            std::vector<double> samples;
            for (int i = 0; i < std::min(5, measure_s); ++i) {
                std::this_thread::sleep_for(std::chrono::seconds(1));
                double p = measure_single_power(*device);
                if (p >= 0) samples.push_back(p);
            }
            if (!samples.empty()) {
                report.sleep_power.avg = std::accumulate(samples.begin(), samples.end(), 0.0) / samples.size();
                report.sleep_power.min_val = *std::min_element(samples.begin(), samples.end());
                report.sleep_power.max_val = *std::max_element(samples.begin(), samples.end());
                report.sleep_power.samples = static_cast<int>(samples.size());
            } else {
                poc_log("  RISK RAISED: Cannot measure power during sleep.");
                int remaining = measure_s - 5;
                if (remaining > 0) {
                    std::this_thread::sleep_for(std::chrono::seconds(remaining));
                }
            }
        }
        poc_log("  Sleep power: " + report.sleep_power.as_str());
    } else {
        poc_log("\n[Phase 4] Skipped (sleep entry failed). Waiting "
                + std::to_string(args.sleep_duration) + "s...");
        std::this_thread::sleep_for(std::chrono::seconds(args.sleep_duration));
    }

    // ---- Phase 5: Exit sleep ----
    poc_log("\n[Phase 5] Exiting sleep mode");
    if (report.sleep_entry_ms >= 0) {
        auto tic = Clock::now();
        auto st = device->set_sleep_state(HAILO_SLEEP_STATE_AWAKE);
        auto toc = Clock::now();
        if (HAILO_SUCCESS == st) {
            report.wake_exit_ms = std::chrono::duration<double, std::milli>(toc - tic).count();
            std::ostringstream ss;
            ss << std::fixed << std::setprecision(2) << report.wake_exit_ms;
            poc_log("  Wake exit time: " + ss.str() + " ms");
        } else {
            poc_log("  RISK RAISED: Wake exit failed (status " + std::to_string(st) + ")");
            report.wake_exit_ms = -1;
        }
        poc_log("  Waiting 3s for device stabilization...");
        std::this_thread::sleep_for(std::chrono::seconds(3));
    } else {
        poc_log("  Skipped (sleep was not entered)");
        report.wake_exit_ms = -1;
    }

    // ---- Phase 6: Post-wake inference ----
    poc_log("\n[Phase 6] Post-wake inference (" + std::to_string(args.inference_duration) + "s)");
    report.postwake = run_inference_phase(*device, args, args.inference_duration, "POST-WAKE", video_path);

    // ---- Phase 7: Post-flight & Report ----
    poc_log("\n[Phase 7] Post-flight check");
    auto post_id = device->identify();
    report.device_alive_after = post_id.has_value();
    poc_log(std::string("  Device alive after test: ") + (report.device_alive_after ? "YES" : "NO"));

    // Compute validation metrics
    if (report.baseline.fps > 0 && report.postwake.fps > 0) {
        report.fps_delta_pct = std::abs(report.postwake.fps - report.baseline.fps)
                               / report.baseline.fps * 100.0;
        report.fps_pass = report.fps_delta_pct < args.fps_threshold;
    }

    if (report.idle_power_w > 0 && report.sleep_power.avg > 0) {
        report.power_reduction_pct = (1.0 - report.sleep_power.avg / report.idle_power_w) * 100.0;
    }

    print_report(report, args.fps_threshold);
    write_json_report(report, args.output_json);

    poc_log("\nPoC complete. JSON report: " + args.output_json);
    return 0;
}
