# Face Landmarks Detection

Real-time 468-point face mesh landmark detection with both models on Hailo.

## Pipeline Modes

### GStreamer cascade (default, `--pipeline-mode gstreamer`)

Full GStreamer cascade — all inference on Hailo, CPU only draws landmarks.
Best throughput, lowest CPU usage.

```
SOURCE -> SCRFD (hailonet) -> Tracker -> CROPPER(face_landmarks_lite + postprocess) -> Callback -> Display
```

Requires the C++ postprocess SO — build it first:
```bash
cd community/apps/pipeline_apps/face_landmarks/postprocess && ./build.sh
```

### Python InferVStreams (`--pipeline-mode python`)

SCRFD in GStreamer, face_landmarks_lite via HailoRT InferVStreams in the callback.
More flexible for custom processing. No C++ build required.

```
SOURCE -> SCRFD (hailonet) -> Tracker -> Callback(InferVStreams) -> Display
```

## Usage

```bash
# Default (GStreamer cascade) — uses face_recognition.mp4 sample video
python -m community.apps.pipeline_apps.face_landmarks.face_landmarks

# USB camera
python -m community.apps.pipeline_apps.face_landmarks.face_landmarks --input usb

# Python InferVStreams mode
python -m community.apps.pipeline_apps.face_landmarks.face_landmarks --pipeline-mode python

# With FPS counter
python -m community.apps.pipeline_apps.face_landmarks.face_landmarks --show-fps

# With shell script
bash community/apps/pipeline_apps/face_landmarks/run.sh --input usb
```

## Standalone Reference Demo

`face_landmarks_standalone.py` is a non-GStreamer reference (SCRFD + face_landmarks_lite
on Hailo, MediaPipe-style rotation-aligned crop and drawing). It has one extra dependency
not needed by the pipeline app:

```bash
pip install mediapipe   # required only by the standalone demo, for drawing utilities
```

```bash
python -m community.apps.pipeline_apps.face_landmarks.face_landmarks_standalone --image face.jpg
python -m community.apps.pipeline_apps.face_landmarks.face_landmarks_standalone --camera 0
```

The `mediapipe` import is deferred to runtime, so the GStreamer pipeline app
(`face_landmarks.py`) runs without `mediapipe` installed. The standalone demo exits with a
clear install hint if it is missing. On `hailo8l` it selects `scrfd_2.5g` automatically;
`hailo8`/`hailo10h` use `scrfd_10g` (pass `--arch`).

## Models

| Model | Runs on | Purpose | Input | FPS (Hailo-8) |
|-------|---------|---------|-------|---------------|
| scrfd_10g | Hailo (hailonet) | Face detection + 5 landmarks | 640x640 | ~100 |
| face_landmarks_lite | Hailo (cascade or InferVStreams) | 468 3D face mesh | 192x192 | ~600 |

SCRFD is auto-downloaded from the Hailo Model Zoo.
`face_landmarks_lite.hef` must be placed at:
```
/usr/local/hailo/resources/models/<arch>/face_landmarks_lite.hef
```

## Benchmarks

Tested with face_recognition.mp4 sample video (30fps source):

| Mode | Steady FPS | Frame Drop | Notes |
|------|-----------|------------|-------|
| GStreamer cascade | 30.0 | 0% | Both models in GStreamer, CPU draws only |
| Python InferVStreams | 30.0 | 0% | SCRFD in GStreamer, landmarks in callback |

Both modes saturate the 30fps video source with zero drops. The GStreamer cascade
has lower CPU overhead and scales better with multiple faces.

## Output

Color-coded face mesh regions on each detected face:
- **Green** -- Face oval contour
- **Azure** (light blue) -- Eye contours
- **Teal** -- Eyebrow lines
- **Red** -- Lip contours
- **Gray dots** -- Individual mesh points (468 total)

## Building the Postprocess SO (GStreamer mode only)

```bash
cd community/apps/pipeline_apps/face_landmarks/postprocess
./build.sh              # Build + install to /usr/local/hailo/resources/so/
./build.sh --no-install # Build only (library in build/)
```

Requires `hailo-tappas-core >= 3.30.0` development package.

## Supported Hardware

- Hailo-8 (scrfd_10g + face_landmarks_lite)
- Hailo-8L (scrfd_2.5g + face_landmarks_lite)
- Hailo-10H (scrfd_10g + face_landmarks_lite)
