# Depth Anything (C++ Standalone)

## What This App Does
Monocular depth estimation using Depth Anything V1 or V2 on a Hailo accelerator without GStreamer. Produces colorized depth maps from images, video, or camera input using the HailoRT C++ API and OpenCV.

## Architecture
- **Type:** Standalone app (C++)
- **Pattern:** HailoInfer (C++ API) + OpenCV; 3-thread async pipeline (no GStreamer)
- **Models:** depth_anything_vits (V1) or depth_anything_v2_vits (V2)
- **Hardware:** hailo8, hailo8l, hailo10h (see README)
- **Postprocess:** C++ — dequantize, min-max normalize to 0-255, OpenCV INFERNO colormap

## Key Files
| File | Purpose |
|------|---------|
| `depth_anything.cpp` | Main: async inference, dequantize, normalize, colormap |
| `CMakeLists.txt` | C++17 build config using hailo-apps C++ common libs |
| `build.sh` | CMake build; outputs `build/<arch>/depth_anything` |

## How to Run
```bash
cd community/apps/standalone_apps/depth_anything_cpp && ./build.sh
./build/x86_64/depth_anything -n /path/to/depth_anything_v2.hef -i input.mp4
```
Optional: `-b <batch>`, `-s` (save), `-o results/`. (Use the arch-matching subdir under `build/`.)

## How to Extend
- Add alternative colormaps (PLASMA/MAGMA/TURBO) selectable from the command line.
- Compare against `depth_anything_python` (sibling app) when you need a no-build Python equivalent.
