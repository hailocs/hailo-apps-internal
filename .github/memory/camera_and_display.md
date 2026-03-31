# Camera & Display — Memory

## Camera Types and Color Spaces

| Source | Library | Frame Format | Notes |
|---|---|---|---|
| USB camera | OpenCV `VideoCapture` | BGR (uint8) | Must convert to RGB for VLM |
| RPi camera | Picamera2 | RGB (uint8) | Already RGB if `format="RGB888"` |
| RTSP stream | OpenCV `VideoCapture` | BGR (uint8) | May have latency; use threading |
| Video file | OpenCV `VideoCapture` | BGR (uint8) | Loops handled by GStreamerApp |

## USB Camera Discovery

```python
from hailo_apps.python.core.common.camera_utils import get_usb_video_devices
devices = get_usb_video_devices()  # Uses udevadm, filters virtual devices
```

**Gotcha**: `get_usb_video_devices()` returns device indices (int), not paths.

### CRITICAL: Never assume `/dev/video0` is the USB camera
`/dev/video0` is usually the **integrated webcam** (e.g., laptop built-in camera).
External USB cameras are typically at `/dev/video4` or higher. Always use:
- `--input usb` for GStreamer pipeline apps (auto-detects USB camera)
- `v4l2-ctl --list-devices` to identify the correct device
- `get_usb_video_devices()` for standalone/OpenCV apps

**Never hardcode `/dev/video0` when the user asks for USB camera.**

## Camera Init Pattern

Always use a tuple-returning factory for clean abstraction:

```python
def init_camera(source, source_type):
    """Returns (get_frame_callback, cleanup_callback, camera_name)"""
```

This pattern allows the main loop to be camera-agnostic.

## RPi Camera Gotcha

`Picamera2` must be configured before `start()`:
```python
picam2 = Picamera2()
config = picam2.create_preview_configuration(main={"size": (640, 480), "format": "RGB888"})
picam2.configure(config)  # Must be before start()
picam2.start()
```

## OpenCV Display

### Window Creation
```python
cv2.imshow('Window Name', frame)  # Creates window on first call
key = cv2.waitKey(25) & 0xFF       # 25ms timeout, masked to 8 bits
cv2.destroyAllWindows()             # Always in finally block
```

### Text Overlay
```python
cv2.putText(frame, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
```
- Origin (x,y) is bottom-left of text
- Color is BGR (not RGB)

### Environment for Headless Linux
```python
os.environ["QT_QPA_PLATFORM"] = 'xcb'  # Must be before import cv2
```

## Color Conversion Cheat Sheet

```python
rgb = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)   # For VLM input
bgr = cv2.cvtColor(rgb_frame, cv2.COLOR_RGB2BGR)   # For OpenCV display
```

## VLM Image Preprocessing

VLM expects 336×336 RGB. Use central crop (not letterbox):

```python
# Scale to cover, then center crop
scale = max(target_w / w, target_h / h)
resized = cv2.resize(image, (int(w*scale), int(h*scale)))
cropped = resized[y_start:y_start+target_h, x_start:x_start+target_w]
```

**Why central crop**: Preserves aspect ratio, no black bars. VLM handles well.

## Frame Saving

```python
timestamp = time.strftime("%Y%m%d_%H%M%S")
cv2.imwrite(f"frame_{timestamp}.jpg", bgr_frame)  # imwrite expects BGR
```

## Known Issues

### Camera Release Must Match Init Thread
OpenCV `cv2.VideoCapture.release()` must be called from the same thread as `read()`. Calling from a signal handler or different thread can crash.

**Fix**: Always release in the camera loop's finally block.

### Multiple Camera Access
Two processes cannot access the same USB camera. Use `SHARED_VDEVICE_GROUP_ID` for Hailo device sharing, but camera access must be exclusive.
