# Gesture Detection — Benchmark Report

**Date:** 2026-03-08
**Comparison:** Native MediaPipe (CPU) vs Hailo-8 Python vs Hailo-8 C++ Standalone

## System

| Parameter | Value |
|-----------|-------|
| CPU | 12th Gen Intel Core i7-1270P |
| Cores | 12 physical / 16 logical |
| RAM | 30.6 GB |
| OS | Ubuntu 22.04 (Linux 5.15.0-60-generic, x86_64) |
| Python | 3.10.12 |
| numpy | 1.26.4 |
| Hailo device | Hailo-8 (M.2 M-key), FW 4.23.0 |
| HailoRT | 4.23.0 |
| MediaPipe | 0.10.32 (TFLite + XNNPACK CPU backend) |
| OpenCV | 4.5.4 |
| GCC | 11.4.0 |

## Test Setup

- **Input:** 300 frames, 640x480, 30fps (cycling 3 test photos: open hand, thumbs up, peace sign)
- **Mode:** Headless (no display overhead)
- **Native config:** MediaPipe HandLandmarker task, `hand_landmarker.task` float16, `num_hands=2`. All pre/post processing runs inside MediaPipe's C++ graph (TFLite + XNNPACK).
- **Hailo Python config:** `palm_detection_lite.hef` + `hand_landmark_lite.hef`, InferVStreams API, shared VDevice. Pre/post processing (resize, anchor decode, NMS, affine warp, landmark denorm) runs in **Python/numpy**.
- **Hailo C++ config:** Same HEF models, HailoRT async C++ API with `group_id` shared VDevice. All pre/post processing (resize, anchor decode, NMS, affine warp, landmark denorm) runs in **C++ with OpenCV**. No GStreamer, no xtensor, no TAPPAS dependencies.

## Results — Side by Side

### Frame Throughput

| Metric | Native CPU | Hailo-8 Python | Hailo-8 C++ | C++ vs Native |
|--------|-----------|----------------|-------------|---------------|
| Total frames | 300 | 300 | 300 | — |
| Wall time | 6.5 s | 4.3 s | **4.1 s** | **1.6x faster** |
| **Avg FPS** | **46.1** | **69.9** | **72.3** | **1.57x** |
| Avg frame time | 21.3 ms | 13.9 ms | **13.2 ms** | 38% faster |
| Median frame time | 19.4 ms | 13.5 ms | **13.2 ms** | 32% faster |
| P5 frame time (best) | 17.7 ms | 12.2 ms | **11.4 ms** | 36% faster |
| P95 frame time (worst) | 31.2 ms | 15.6 ms | **14.8 ms** | **2.1x better** |

### Hailo-8 Python Timing Breakdown

| Stage | Avg | Median | Notes |
|-------|-----|--------|-------|
| Pre-process (Python) | 0.2 ms | 0.2 ms | BGR→RGB, resize_pad to 192x192 |
| Palm detect (Hailo) | 7.2 ms | 6.8 ms | HailoRT InferVStreams + anchor decode + NMS |
| Post-process (Python) | 0.9 ms | 0.9 ms | detection2roi, affine warp, landmark denorm |
| Hand landmark (Hailo) | 5.6 ms | 5.5 ms | HailoRT InferVStreams per detected hand |
| **Hailo inference total** | **12.7 ms** | | Palm + hand landmark on NPU |
| **Python pre/post total** | **1.1 ms** | | Resize, decode, warp, denorm |

Note: "Palm detect" time includes both the HailoRT inference call and the Python anchor decoding + NMS postprocess, since `BlazePalmDetector.detect()` wraps both.

### Hailo-8 C++ Timing Breakdown

| Stage | Avg | Median | Notes |
|-------|-----|--------|-------|
| Pre-process (C++) | 0.5 ms | 0.5 ms | BGR→RGB, resize_pad to 192x192 |
| Palm detect (Hailo) | 6.0 ms | 6.0 ms | HailoRT async API + anchor decode + NMS |
| Post-process (C++) | 1.5 ms | 1.5 ms | detection2roi, affine warp, landmark denorm, draw |
| Hand landmark (Hailo) | 5.2 ms | 5.2 ms | HailoRT async API per detected hand |
| **Hailo inference total** | **11.2 ms** | | Palm + hand landmark on NPU |
| **C++ pre/post total** | **2.0 ms** | | Resize, decode, warp, denorm, draw |

### Native MediaPipe Inference

| Metric | Value |
|--------|-------|
| Avg inference | 21.0 ms |
| Median inference | 19.0 ms |
| P95 inference | 30.9 ms |

MediaPipe's `detect()` call includes all pre/post processing in C++ — there is no separate Python overhead.

### CPU & Memory Usage

| Metric | Native CPU | Hailo-8 Python | Hailo-8 C++ |
|--------|-----------|----------------|-------------|
| Process avg | 109.5% | 76.6% | ~104% |
| Process max | 112.0% | 81.4% | — |
| System avg | 12.7% | 21.1% | — |
| System max | 19.8% | 28.1% | — |
| Peak RSS | — | — | 120 MB |

*Process CPU >100% means multi-threaded. Native MediaPipe XNNPACK uses ~1.1 cores; Hailo-8 Python uses ~0.8 cores. C++ process CPU measured via `/usr/bin/time -v` (includes HailoRT internal threads).*

### Detection

| Metric | Native CPU | Hailo-8 Python | Hailo-8 C++ |
|--------|-----------|----------------|-------------|
| Frames with hand | 300/300 (100%) | 300/300 (100%) | 300/300 (100%) |

## Key Observations

1. **Hailo-8 C++ is 1.57x faster than native MediaPipe** — 72.3 FPS vs 46.1 FPS on a strong x86 laptop CPU. The advantage would be much larger on weaker CPUs (Raspberry Pi).

2. **C++ is 5% faster than Python+Hailo** — 72.3 vs 69.9 FPS. The gain comes primarily from lower HailoRT API overhead (async C++ API vs Python InferVStreams): 11.2 ms vs 12.7 ms total Hailo time.

3. **Hailo-8 uses ~30% less CPU** — 76.6% vs 109.5% process CPU. The NPU handles inference, freeing CPU for application logic.

4. **Native MediaPipe benefits from C++ pre/post processing** — The entire MediaPipe pipeline (detection, NMS, crop, landmark) runs as an optimized C++ graph. The Hailo Python pipeline only offloads inference to the NPU; all pre/post (anchor decode, NMS, affine warp) runs in Python. Despite this disadvantage, Hailo-8 is still 1.5x faster.

5. **P95 latency is the biggest Hailo win** — 14.8 ms (C++) vs 31.2 ms (native). The Hailo pipeline is **2.1x more consistent** in worst-case frame times. Native MediaPipe alternates between palm detection and tracking, causing more variance.

6. **C++ pre/post is slightly slower than Python/numpy** — 2.0 ms vs 1.1 ms. This includes `frame.clone()` for display buffer and OpenCV's affine warp. NumPy's vectorized operations are highly optimized on x86. However, the C++ Hailo inference time is 1.5 ms faster, more than compensating.

7. **Native MediaPipe is fast on x86** — XNNPACK is highly optimized for Intel CPUs. On ARM (RPi), expect 5-10x slower, making the Hailo-8 advantage much larger.

## Expected Performance on Other Platforms

| Platform | Native CPU FPS | Hailo-8 C++ FPS | Speedup |
|----------|---------------|-----------------|---------|
| Intel i7-1270P (this test) | ~46 | ~72 | 1.6x |
| Raspberry Pi 5 + Hailo-8 | ~5-8 | ~30-50* | 5-8x |
| Raspberry Pi 4 + Hailo-8 | ~2-4 | ~20-35* | 7-12x |

*RPi Hailo-8 estimates assume C++ standalone app. Python overhead would reduce FPS by ~5%.

## How to Reproduce

```bash
source setup_env.sh

# Create benchmark video (or use your own)
python3 -c "
import cv2, os
photos = ['photo.jpg', 'photo1.jpg', 'photo2.jpg']
d = 'hailo_apps/python/pipeline_apps/gesture_detection'
frames = [cv2.resize(cv2.imread(os.path.join(d, p)), (640,480)) for p in photos]
w = cv2.VideoWriter(os.path.join(d, 'benchmark_input.mp4'), cv2.VideoWriter_fourcc(*'mp4v'), 30, (640,480))
for i in range(300): w.write(frames[i % len(frames)])
w.release()
"

# 1. Native CPU baseline
pip install mediapipe psutil
python -m hailo_apps.python.pipeline_apps.gesture_detection.gesture_detection_native \
    --input hailo_apps/python/pipeline_apps/gesture_detection/benchmark_input.mp4 \
    --headless

# 2. Hailo-8 Python
python -m hailo_apps.python.pipeline_apps.gesture_detection.gesture_detection_h8 \
    --input hailo_apps/python/pipeline_apps/gesture_detection/benchmark_input.mp4 \
    --headless

# 3. Hailo-8 C++ standalone
cd hailo_apps/cpp/gesture_detection && ./build.sh && cd -
hailo_apps/cpp/gesture_detection/build/gesture_detection \
    --palm-model hailo_apps/python/pipeline_apps/gesture_detection/models/palm_detection_lite.hef \
    --hand-model hailo_apps/python/pipeline_apps/gesture_detection/models/hand_landmark_lite.hef \
    --input hailo_apps/python/pipeline_apps/gesture_detection/benchmark_input.mp4 \
    --headless
```

## Notes

- `mediapipe 0.10.32` installs `numpy>=2.0` but HailoRT 4.23.0 requires `numpy<2`. After installing mediapipe, downgrade: `pip install "numpy<2"`. MediaPipe works fine with numpy 1.26.x.
- The C++ standalone app requires only OpenCV4 + HailoRT. No GStreamer, xtensor, or TAPPAS postprocess headers needed.
