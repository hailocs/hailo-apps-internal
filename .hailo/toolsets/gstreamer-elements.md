# Toolset: GStreamer Elements Reference

> Complete reference of GStreamer elements available in the Hailo TAPPAS framework.

## Hailo-Specific Elements

### hailonet
Run neural network inference on Hailo accelerator.
```
hailonet hef-path=/path/to/model.hef batch-size=1 multi-process-service=true vdevice-group-id=SHARED
```
| Property | Type | Description |
|---|---|---|
| `hef-path` | string | Path to HEF model file |
| `batch-size` | int | Inference batch size |
| `multi-process-service` | bool | Enable multi-process device sharing |
| `vdevice-group-id` | string | VDevice group for sharing |

### hailofilter
Apply postprocessing to inference results.
```
hailofilter so-path=/path/to/libpostprocess.so function-name=my_postprocess config-path=/path/to/config.json
```
| Property | Type | Description |
|---|---|---|
| `so-path` | string | Path to postprocess shared library |
| `function-name` | string | Function name within .so to call |
| `config-path` | string | Optional JSON config for postprocess |

### hailooverlay
Draw detection boxes, labels, and landmarks on video frames.
```
hailooverlay
```
No configuration needed — automatically renders all Hailo metadata on frames.

### hailocropper / hailoaggregator
Crop detected regions for second-stage inference, then merge results back.
```
hailocropper so-path=libcropper.so function-name=crop_func ! queue ! {second_stage} ! hailoaggregator
```

### hailotilecropper / hailotileaggregator
Split frame into tiles for inference on high-resolution images.
```
hailotilecropper tiles-along-x-axis=2 tiles-along-y-axis=2 overlap-x-ratio=0.1 overlap-y-ratio=0.1
```

### hailotracker
Object tracking using ByteTrack algorithm.
```
hailotracker class-id=-1 kalman-dist-thr=0.7 iou-thr=0.8 init-iou-thr=0.9 keep-tracked=true
```

### hailomuxer
Merge multiple inference branches.
```
hailomuxer name=mux
```

## Standard GStreamer Elements Used

### Sources
| Element | Usage |
|---|---|
| `v4l2src` | USB camera (use `--input usb` to auto-detect; do NOT hardcode `/dev/video0` — it may be the integrated webcam, not the USB camera. Use `v4l2-ctl --list-devices` to identify the correct device) |
| `libcamerasrc` | RPi camera |
| `filesrc` | Video file input |
| `rtspsrc` | RTSP stream |
| `videotestsrc` | Test pattern generator |
| `ximagesrc` | X11 screen capture |

### Processing
| Element | Usage |
|---|---|
| `videoconvert` | Pixel format conversion |
| `videoscale` | Resolution scaling |
| `videorate` | Frame rate adjustment |
| `queue` | Buffer queue (thread boundary) |
| `tee` | Split pipeline into branches |
| `identity` | Pass-through (used for Python callbacks) |

### Sinks
| Element | Usage |
|---|---|
| `xvimagesink` | X11 video display |
| `fpsdisplaysink` | Display with FPS overlay |
| `fakesink` | Discard output (headless) |
| `appsink` | Pass frames to application |
| `filesink` | Save to file |
| `shmsink` | Shared memory output |
| `udpsink` | UDP streaming |

### Encoding
| Element | Usage |
|---|---|
| `x264enc` | H.264 encoding |
| `matroskamux` | MKV container |

## Pipeline String Syntax

GStreamer elements are connected with `!` (pipe operator):
```
source ! queue ! process ! queue ! sink
```

Named elements use `name=xxx` and can be referenced: 
```
tee name=t ! queue ! branch1 t. ! queue ! branch2
```

## Helper Function Mapping

| Helper Function | GStreamer Elements Created |
|---|---|
| `SOURCE_PIPELINE()` | v4l2src/filesrc + videoconvert + videoscale + videorate |
| `INFERENCE_PIPELINE()` | queue + hailonet + queue + hailofilter |
| `DISPLAY_PIPELINE()` | hailooverlay + queue + fpsdisplaysink/xvimagesink |
| `USER_CALLBACK_PIPELINE()` | identity (with Python callback) |
| `TRACKER_PIPELINE()` | hailotracker |
| `QUEUE()` | queue with configurable buffer sizes |

