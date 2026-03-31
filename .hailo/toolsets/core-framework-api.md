# Toolset: Core Framework API Reference

> Complete API reference for the hailo-apps core framework modules.

## hailo_apps.python.core.common.core

### resolve_hef_path()
```python
def resolve_hef_path(
    hef_path: Optional[str],    # User-provided path (from CLI)
    app_name: str,              # App registry name (e.g., "vlm_chat")
    arch: str,                  # Target architecture ("hailo8", "hailo8l", "hailo10h")
    app_type: Optional[str] = None  # Auto-detected from call stack
) -> Optional[Path]:
```
Resolves HEF model path with auto-download. Returns `Path` or `None` on failure.

### get_standalone_parser()
```python
def get_standalone_parser() -> argparse.ArgumentParser:
```
Returns parser with: `--input`, `--hef-path`, `--list-models`, `--batch-size`, `--show-fps`, `--frame-rate`, `--camera-resolution`, `--no-display`, `--output-resolution`, `--output-dir`, `--save-output`, logging flags.

### get_pipeline_parser()
```python
def get_pipeline_parser() -> argparse.ArgumentParser:
```
Returns parser with all standalone args plus: `--use-frame`, `--disable-sync`, `--disable-callback`, `--dump-dot`, `--enable-watchdog`, `--width`, `--height`, `--labels`, `--arch`.

### handle_list_models_flag()
```python
def handle_list_models_flag(parser: argparse.ArgumentParser, app_name: str) -> None:
```
Checks for `--list-models` flag, prints available models, and exits if set.

### list_models_for_app()
```python
def list_models_for_app(app_name: str, arch: str) -> None:
```
Prints available models for given app and architecture.

### get_resource_path()
```python
def get_resource_path(
    pipeline_name: str,
    resource_type: str,    # "models", "videos", "images", "json", "so"
    arch: str,
    model: Optional[str] = None
) -> Path:
```

---

## hailo_apps.python.core.common.hailo_logger

### get_logger()
```python
def get_logger(name: str) -> logging.Logger:
```
Returns configured logger with color formatting and file output support.

### init_logging()
```python
def init_logging(level: str = "INFO") -> None:
```
Initialize logging system. Called once at app startup.

### level_from_args()
```python
def level_from_args(args: argparse.Namespace) -> str:
```
Extract log level from parsed CLI arguments.

---

## hailo_apps.python.core.common.hailo_inference

### HailoInfer
```python
class HailoInfer:
    def __init__(self, hef_path: str):
        """Initialize inference engine with HEF model."""

    def get_input_shape(self) -> tuple:
        """Returns (H, W, C) input shape."""

    def run(self, input_data: np.ndarray) -> dict:
        """Synchronous inference."""

    def run_async(self, input_data: np.ndarray) -> Future:
        """Asynchronous inference, returns future."""
```

---

## hailo_apps.python.core.common.camera_utils

### get_usb_video_devices()
```python
def get_usb_video_devices() -> list[int]:
```
Returns list of available USB camera device indices using `udevadm`.

### is_rpi_camera_available()
```python
def is_rpi_camera_available() -> bool:
```
Checks if RPi camera is connected and accessible.

---

## hailo_apps.python.core.common.hef_utils

### get_hef_input_size()
```python
def get_hef_input_size(hef_path: str) -> tuple[int, int]:
```
Returns `(height, width)` of model input.

### get_hef_input_shape()
```python
def get_hef_input_shape(hef_path: str) -> tuple[int, int, int]:
```
Returns full `(H, W, C)` shape.

---

## hailo_apps.python.core.common.installation_utils

### detect_hailo_arch()
```python
def detect_hailo_arch() -> str:
```
Auto-detects connected Hailo hardware. Returns `"hailo8"`, `"hailo8l"`, or `"hailo10h"`.

### detect_host_arch()
```python
def detect_host_arch() -> str:
```
Returns host CPU architecture: `"x86_64"` or `"aarch64"`.

---

## hailo_apps.python.core.gstreamer.gstreamer_app

### GStreamerApp
```python
class GStreamerApp:
    def __init__(self, args: argparse.Namespace, user_data: app_callback_class):
        """Initialize GStreamer application."""

    def get_pipeline_string(self) -> str:
        """ABSTRACT: Return GStreamer pipeline string. Must override."""

    def run(self):
        """Start pipeline and main loop."""

    def shutdown(self):
        """Stop pipeline and cleanup."""

    def _on_pipeline_rebuilt(self):
        """Hook called after pipeline rebuild (override for custom behavior)."""
```

### app_callback_class
```python
class app_callback_class:
    def __init__(self):
        self.frame_count = 0
        self.use_frame = False
        self.frame_queue = multiprocessing.Queue(maxsize=3)
        self.running = True

    def get_count(self) -> int:
        """Get current frame count."""

    def set_frame(self, frame: np.ndarray):
        """Store frame for cross-thread access."""

    def get_frame(self) -> Optional[np.ndarray]:
        """Retrieve stored frame."""
```

---

## hailo_apps.python.core.common.buffer_utils

### get_numpy_from_buffer()
```python
def get_numpy_from_buffer(buffer, format: str, width: int, height: int) -> np.ndarray:
```
Converts GStreamer buffer to numpy array. `format`, `width`, `height` come from `get_caps_from_pad()`. Supports RGB, NV12, YUYV formats.

**Usage pattern:**
```python
from hailo_apps.python.core.common.buffer_utils import get_caps_from_pad, get_numpy_from_buffer

pad = element.get_static_pad("src")
format, width, height = get_caps_from_pad(pad)
frame = get_numpy_from_buffer(buffer, format, width, height)  # Returns RGB numpy array (H, W, 3)
```

### get_caps_from_pad()
```python
def get_caps_from_pad(pad) -> tuple:
```
Extracts (format, width, height) from GStreamer pad capabilities. Returns tuple of (str, int, int).
