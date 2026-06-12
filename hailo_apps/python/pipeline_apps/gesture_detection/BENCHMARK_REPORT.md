# Gesture Detection — Benchmark Report

**Date:** 2026-03-08

## Summary

| Platform | Native CPU | Hailo-8 Python | Hailo-8 C++ | Speedup (C++ vs Native) |
|----------|-----------|----------------|-------------|-------------------------|
| **Raspberry Pi 5** | **26 FPS** | **50 FPS** | **62 FPS** | **2.4x** |
| Intel i7-1270P | 46 FPS | 70 FPS | 72 FPS | 1.6x |

The Hailo-8 NPU runs at the same speed on both platforms (~11 ms inference). The weaker the host CPU, the larger the Hailo advantage.

---

## Test Setup

**Input:** 300 frames, 640x480, headless mode (no display overhead).

**Pipelines tested:**

| Pipeline | Inference backend | Pre/post processing | Notes |
|----------|-------------------|---------------------|-------|
| Native CPU | TFLite XNNPACK (float16) | Python / numpy | x86: `mediapipe` package. RPi: `ai-edge-litert` + same models |
| Hailo-8 Python | HailoRT InferVStreams | Python / numpy | `palm_detection_lite.hef` + `hand_landmark_lite.hef` |
| Hailo-8 C++ | HailoRT async API | C++ / OpenCV | Same HEFs. No GStreamer or TAPPAS deps |

All pipelines run the same two-stage architecture: palm detection (192x192) followed by hand landmark (224x224) per detected hand.

---

## Raspberry Pi 5 Results

### System

| | |
|-|-|
| Board | Raspberry Pi 5 Model B Rev 1.1 |
| CPU | Cortex-A76, 4 cores (aarch64) |
| RAM | 7.9 GB |
| OS | Debian 13, Linux 6.12.62 |
| Hailo | Hailo-8 PCIe, FW 4.23.0, HailoRT 4.23.0 |
| OpenCV | 4.10.0, GCC 14.2.0, Python 3.13.5 |

### Throughput

| Metric | Native CPU | Hailo-8 Python | Hailo-8 C++ |
|--------|-----------|----------------|-------------|
| **Avg FPS** | **26.3** | **50.4** | **62.4** |
| Wall time | 11.4 s | 6.0 s | 4.8 s |
| Avg frame time | 36.4 ms | 18.1 ms | 14.1 ms |
| Median frame time | 35.6 ms | 17.3 ms | 13.8 ms |
| P5 (best) | 32.1 ms | 16.8 ms | 13.5 ms |
| P95 (worst) | 43.8 ms | 22.3 ms | 15.6 ms |

### Timing Breakdown

#### Native CPU (TFLite/XNNPACK)

| Stage | Avg | Median |
|-------|-----|--------|
| Pre-process | 0.8 ms | 0.8 ms |
| Palm detect (CPU) | 19.8 ms | 19.5 ms |
| Post-process | 2.0 ms | 1.9 ms |
| Hand landmark (CPU) | 13.7 ms | 13.5 ms |
| **Inference total** | **33.6 ms** | |
| **Pre/post total** | **2.8 ms** | |

#### Hailo-8 Python

| Stage | Avg | Median |
|-------|-----|--------|
| Pre-process | 0.9 ms | 0.8 ms |
| Palm detect (NPU) | 7.9 ms | 7.5 ms |
| Post-process | 2.5 ms | 2.5 ms |
| Hand landmark (NPU) | 6.7 ms | 6.3 ms |
| **Inference total** | **14.6 ms** | |
| **Pre/post total** | **3.4 ms** | |

#### Hailo-8 C++

| Stage | Avg | Median |
|-------|-----|--------|
| Pre-process | 0.8 ms | 0.7 ms |
| Palm detect (NPU) | 6.1 ms | 6.0 ms |
| Post-process | 1.8 ms | 1.8 ms |
| Hand landmark (NPU) | 5.3 ms | 5.2 ms |
| **Inference total** | **11.4 ms** | |
| **Pre/post total** | **2.6 ms** | |

### CPU Usage

| Metric | Native CPU | Hailo-8 Python |
|--------|-----------|----------------|
| Process avg | 271.7% | 73.1% |
| Process max | 288.4% | 76.5% |
| System avg | 81.9% | 24.6% |
| System max | 85.5% | 28.3% |

Native TFLite uses ~2.7 of 4 cores. Hailo offloads inference to the NPU, using <1 core.

---

## x86_64 Dev Machine Results

### System

| | |
|-|-|
| CPU | 12th Gen Intel Core i7-1270P, 12P/16L cores |
| RAM | 30.6 GB |
| OS | Ubuntu 22.04, Linux 5.15.0 |
| Hailo | Hailo-8 M.2 M-key, FW 4.23.0, HailoRT 4.23.0 |
| MediaPipe | 0.10.32 (TFLite + XNNPACK) |
| OpenCV | 4.5.4, GCC 11.4.0, Python 3.10.12 |

### Throughput

| Metric | Native CPU | Hailo-8 Python | Hailo-8 C++ |
|--------|-----------|----------------|-------------|
| **Avg FPS** | **46.1** | **69.9** | **72.3** |
| Wall time | 6.5 s | 4.3 s | 4.1 s |
| Avg frame time | 21.3 ms | 13.9 ms | 13.2 ms |
| Median frame time | 19.4 ms | 13.5 ms | 13.2 ms |
| P5 (best) | 17.7 ms | 12.2 ms | 11.4 ms |
| P95 (worst) | 31.2 ms | 15.6 ms | 14.8 ms |

### Timing Breakdown

#### Native MediaPipe (CPU)

| Metric | Value |
|--------|-------|
| Avg inference | 21.0 ms |
| Median inference | 19.0 ms |
| P95 inference | 30.9 ms |

MediaPipe's `detect()` includes all pre/post processing in its C++ graph — no separate Python overhead.

#### Hailo-8 Python

| Stage | Avg | Median |
|-------|-----|--------|
| Pre-process | 0.2 ms | 0.2 ms |
| Palm detect (NPU) | 7.2 ms | 6.8 ms |
| Post-process | 0.9 ms | 0.9 ms |
| Hand landmark (NPU) | 5.6 ms | 5.5 ms |
| **Inference total** | **12.7 ms** | |
| **Pre/post total** | **1.1 ms** | |

#### Hailo-8 C++

| Stage | Avg | Median |
|-------|-----|--------|
| Pre-process | 0.5 ms | 0.5 ms |
| Palm detect (NPU) | 6.0 ms | 6.0 ms |
| Post-process | 1.5 ms | 1.5 ms |
| Hand landmark (NPU) | 5.2 ms | 5.2 ms |
| **Inference total** | **11.2 ms** | |
| **Pre/post total** | **2.0 ms** | |

### CPU Usage

| Metric | Native CPU | Hailo-8 Python | Hailo-8 C++ |
|--------|-----------|----------------|-------------|
| Process avg | 109.5% | 76.6% | ~104% |
| Process max | 112.0% | 81.4% | — |
| Peak RSS | — | — | 120 MB |

---

## Cross-Platform Comparison

| Metric | x86 Native | x86 C++ | RPi Native | RPi C++ | RPi Python |
|--------|-----------|---------|------------|---------|------------|
| **Avg FPS** | **46.1** | **72.3** | **26.3** | **62.4** | **50.4** |
| Inference total | 21.0 ms | 11.2 ms | 33.6 ms | 11.4 ms | 14.6 ms |
| Pre/post total | — | 2.0 ms | 2.8 ms | 2.6 ms | 3.4 ms |
| P95 frame time | 31.2 ms | 14.8 ms | 43.8 ms | 15.6 ms | 22.3 ms |
| CPU (process) | 110% | ~104% | 272% | — | 73% |

---

## Key Observations

**Hailo-8 NPU is platform-independent.** C++ inference totals are 11.4 ms (RPi) vs 11.2 ms (x86) — virtually identical. The NPU runs at full speed regardless of the host CPU.

**The weaker the CPU, the bigger the Hailo win.** On x86 (strong i7), Hailo C++ is 1.6x faster than native. On RPi 5 (Cortex-A76), it jumps to 2.4x. The CPU inference slowdown (21→34 ms) is fully absorbed by the NPU.

**Hailo frees the CPU.** Native TFLite on RPi saturates ~2.7 of 4 cores (272% process CPU, 82% system). Hailo Python uses <1 core (73%), leaving 3+ cores for application logic — critical for robotics workloads.

**C++ vs Python matters more on RPi.** On x86, C++ is only 5% faster than Python (72 vs 70 FPS). On RPi, the gap grows to 24% (62 vs 50 FPS). ARM's weaker single-core performance amplifies Python/numpy overhead: pre/post processing takes 3.4 ms on RPi vs 1.1 ms on x86.

**P95 latency is the biggest win.** RPi Hailo C++ P95 is 15.6 ms vs 43.8 ms native — **2.8x more consistent**. Native CPU jitter comes from OS scheduling pressure at high utilization.

**RPi C++ is within 14% of x86 C++.** 62.4 vs 72.3 FPS — the small gap is entirely from pre/post processing overhead (2.6 ms vs 2.0 ms), not from the NPU.

---

## How to Reproduce

Prepare a 300-frame 640x480 benchmark video (use any video with hands visible, or record from camera).

```bash
source setup_env.sh
INPUT=path/to/benchmark_video.avi

# --- Hailo-8 C++ (recommended) ---
cd hailo_apps/cpp/gesture_detection && ./build.sh && cd -
hailo_apps/cpp/gesture_detection/build/gesture_detection \
    --palm-model hailo_apps/python/pipeline_apps/gesture_detection/models/palm_detection_lite.hef \
    --hand-model hailo_apps/python/pipeline_apps/gesture_detection/models/hand_landmark_lite.hef \
    --input $INPUT --headless

# --- Hailo-8 Python ---
python -m hailo_apps.python.pipeline_apps.gesture_detection.gesture_detection_h8 \
    --input $INPUT --headless

# --- Native CPU baseline (x86, uses mediapipe package) ---
pip install mediapipe psutil
python -m hailo_apps.python.pipeline_apps.gesture_detection.gesture_detection_native \
    --input $INPUT --headless

# --- Native CPU baseline (RPi / aarch64, uses TFLite directly) ---
# Run in a separate venv to avoid dependency conflicts:
python3 -m venv /tmp/mp_bench --system-site-packages
/tmp/mp_bench/bin/pip install ai-edge-litert opencv-python-headless numpy psutil
curl -sL -o /tmp/hand_landmarker.task \
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task"
python3 -c "import zipfile; zipfile.ZipFile('/tmp/hand_landmarker.task').extractall('/tmp/mediapipe_models')"
/tmp/mp_bench/bin/python3 benchmark_native_tflite.py --input $INPUT
```

## Notes

- On RPi, use MJPEG codec (`.avi`) — OpenCV's RPi build may not support `mp4v`.
- The `mediapipe` PyPI package has no aarch64 wheels. The RPi native benchmark uses `ai-edge-litert` (Google's TFLite runtime with XNNPACK) with models extracted from `hand_landmarker.task`. Pre/post processing uses the same `blaze_base.py` as the Hailo pipeline.
- On x86, `mediapipe 0.10.32` pulls `numpy>=2.0` but HailoRT needs `numpy<2`. Fix: `pip install "numpy<2"` after installing mediapipe.
- The C++ app requires only OpenCV4 + HailoRT — no GStreamer, xtensor, or TAPPAS.
