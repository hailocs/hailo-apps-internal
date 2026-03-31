# Coding Standards & Conventions

> Mandatory rules for all code in this repository. AI agents MUST follow these conventions exactly.

## Import Rules

### Always Use Absolute Imports
```python
# ✅ CORRECT — Always absolute from package root
from hailo_apps.python.core.common.core import resolve_hef_path, get_standalone_parser
from hailo_apps.python.core.common.defines import VLM_CHAT_APP, HAILO10H_ARCH
from hailo_apps.python.core.common.hailo_logger import get_logger

# ❌ WRONG — Never use relative imports in app code
from ..core.common.core import resolve_hef_path
from .backend import Backend  # Only OK inside __init__.py or local module references
```

### Import Order (enforced by ruff)
1. Standard library (`os`, `sys`, `time`, `json`)
2. Third-party (`cv2`, `numpy`, `yaml`)
3. Hailo platform (`hailo_platform`, `hailo_platform.genai`)
4. Hailo apps framework (`hailo_apps.python.core.*`)
5. Local app modules

## Logging

```python
from hailo_apps.python.core.common.hailo_logger import get_logger

logger = get_logger(__name__)

# Usage
logger.info("Starting VLM inference...")
logger.debug(f"HEF path: {hef_path}")
logger.warning("Camera timeout, retrying...")
logger.error(f"Inference failed: {e}")
```

**Never use `print()` for operational messages**. Use `print()` only for direct user interaction (prompts, real-time streamed output).

## HEF Model Path Resolution

```python
from hailo_apps.python.core.common.core import resolve_hef_path
from hailo_apps.python.core.common.defines import MY_APP_NAME, HAILO10H_ARCH

# ✅ CORRECT — Use resolve_hef_path with app_name and arch
hef_path = resolve_hef_path(
    args.hef_path,       # User-provided path (may be None)
    app_name=MY_APP_NAME,
    arch=HAILO10H_ARCH   # or detect_hailo_arch()
)

# ❌ WRONG — Never hardcode paths
hef_path = "/usr/local/hailo/resources/models/hailo10h/Qwen2-VL.hef"
```

## Device Creation (VDevice)

```python
from hailo_platform import VDevice
from hailo_apps.python.core.common.defines import SHARED_VDEVICE_GROUP_ID

# ✅ CORRECT — Always use shared group ID
params = VDevice.create_params()
params.group_id = SHARED_VDEVICE_GROUP_ID
vdevice = VDevice(params)

# ❌ WRONG — Never create VDevice without shared group
vdevice = VDevice()
```

## CLI Parser Usage

### Gen AI / Standalone Apps
```python
from hailo_apps.python.core.common.core import get_standalone_parser, handle_list_models_flag

parser = get_standalone_parser()
# Add app-specific arguments
parser.add_argument("--continuous", action="store_true", help="Enable continuous monitoring")
handle_list_models_flag(parser, APP_NAME)
args = parser.parse_args()
```

### GStreamer Pipeline Apps
```python
from hailo_apps.python.core.common.core import get_pipeline_parser

parser = get_pipeline_parser()
args = parser.parse_args()
```

## App Constants Registration

**Official apps** (in `hailo_apps/python/`) MUST be registered in `hailo_apps/python/core/common/defines.py`:

```python
# App name constant
MY_VLM_APP = "my_vlm_app"
MY_VLM_APP_TITLE = "My VLM App"

# Default model (reuses VLM model)
MY_VLM_APP_MODEL_NAME_H10 = "Qwen2-VL-2B-Instruct"
```

## File Structure for New Apps

```
hailo_apps/python/<type>/{app_name}/
├── __init__.py              # Empty or minimal
├── {app_name}.py            # Main app class + entry point
├── backend.py               # Inference backend (if needed)
├── README.md                # Usage documentation (required)
└── requirements.txt         # Extra dependencies (if any)
```

Where `<type>` is `gen_ai_apps/`, `pipeline_apps/`, or `standalone_apps/`.

## Code Style (ruff-enforced)

- **Python**: 3.10+, use type hints
- **Line length**: 100 characters max
- **Formatting**: ruff format (PEP 8 compatible)
- **Docstrings**: Google style, required for all public methods
- **Type hints**: Required for function signatures

```python
def process_frame(
    self,
    frame: np.ndarray,
    prompt: str,
    timeout: int = 30,
) -> dict[str, Any]:
    """
    Process a single video frame with VLM inference.

    Args:
        frame: Input image in BGR format (OpenCV default).
        prompt: Question to ask about the image.
        timeout: Inference timeout in seconds.

    Returns:
        Dictionary with 'answer' and 'time' keys.
    """
```

## Error Handling

```python
# ✅ CORRECT — Catch specific exceptions, log with context
try:
    result = self.backend.vlm_inference(frame, prompt)
except mp.TimeoutError:
    logger.warning(f"Inference timed out after {timeout}s")
    return {"answer": "Timeout", "time": "N/A"}
except Exception as e:
    logger.error(f"Inference failed: {e}")
    raise

# ❌ WRONG — Bare except, silencing errors
try:
    result = self.backend.vlm_inference(frame, prompt)
except:
    pass
```

## Signal Handling & Graceful Shutdown

All apps MUST handle SIGINT for clean shutdown:

```python
import signal

class MyApp:
    def __init__(self):
        self.running = True
        signal.signal(signal.SIGINT, self.signal_handler)

    def signal_handler(self, sig, frame):
        logger.info("Signal received, shutting down...")
        self.stop()

    def stop(self):
        self.running = False
        if self.backend:
            self.backend.close()
```

## Environment Variables

- `QT_QPA_PLATFORM=xcb` — Required for OpenCV GUI on Linux
- `HAILO_LOG_LEVEL` — Override log level (DEBUG, INFO, WARNING, ERROR)
- Set via `os.environ` at module top, before any GUI imports
