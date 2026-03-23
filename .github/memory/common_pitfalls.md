# Common Pitfalls — Memory

> Bugs found, anti-patterns encountered, and lessons learned. Check before writing new code.

## Import Errors

### Wrong: Relative imports in app code
```python
# ❌ This breaks when running with python -m
from .backend import Backend
from ..core.common.core import resolve_hef_path
```

### Right: Always absolute
```python
# ✅ Works everywhere
from hailo_apps.python.gen_ai_apps.vlm_chat.backend import Backend
from hailo_apps.python.core.common.core import resolve_hef_path
```

**Exception**: `try/except ImportError` with fallback to relative is acceptable for dual-mode modules (see agent.py pattern).

## Signal Handling

### Wrong: Cleanup in signal handler directly
```python
def signal_handler(sig, frame):
    self.backend.close()  # May deadlock if caught during queue operation
    sys.exit(0)
```

### Right: Set flag, clean up in main loop
```python
def signal_handler(self, sig, frame):
    self.running = False  # Flag only

def run(self):
    try:
        while self.running:
            # ... main loop
    finally:
        self.backend.close()  # Clean up here
```

## Multiprocessing Queue Gotchas

### Deadlock on Full Queue
If `maxsize` is reached and you `put()` without timeout, the process blocks forever.
```python
# ❌ Can deadlock
self._request_queue.put(data)

# ✅ Always use timeout on both put and get
self._request_queue.put(data, timeout=5)
response = self._response_queue.get(timeout=timeout)
```

### Orphaned Worker Processes
If main process crashes without sending sentinel, worker blocks forever.
**Fix**: Always use `try/finally` in main process:
```python
try:
    app.run()
finally:
    app.stop()  # Sends None sentinel to worker
```

## OpenCV

### imshow Before waitKey
`cv2.imshow()` won't actually display until `cv2.waitKey()` is called. Both are needed.

### BGR vs RGB Confusion
- OpenCV reads as **BGR**
- VLM expects **RGB**  
- OpenCV displays **BGR**
- `cv2.imwrite()` expects **BGR**
- PIL/Pillow reads as **RGB**

**Rule**: Convert to RGB only when sending to VLM. Keep BGR for everything else.

## HEF Path Resolution

### Wrong: resolve_hef_path with wrong app_name
If `app_name` isn't registered in `resources_config.yaml`, resolution silently falls back to searching the filesystem — which may find the wrong model or fail.

**Fix**: Always register new apps in `resources_config.yaml` before using `resolve_hef_path`.

### Wrong: Register in defines.py but forget resources_config.yaml
Adding a constant to `defines.py` alone is NOT enough. `resolve_hef_path()` looks up the
app name in the config manager, which reads `resources_config.yaml`.
```
KeyError: 'my_new_app'  ← This means resources_config.yaml is missing the entry
```
**Fix**: For VLM apps that reuse the same model, add a YAML anchor alias:
```yaml
my_new_app: *vlm_chat_app
```

## Environment / Driver Checks (Pre-Launch)

### PCIe driver check is unreliable
`lsmod | grep hailo_pci` may return empty even when the device is functional
(e.g., built-in driver, different module name).

**Reliable check**: Use `hailortcli fw-control identify` instead — it directly
queries the device firmware and confirms the architecture:
```bash
hailortcli fw-control identify
# Expected: "Device Architecture: HAILO10H" + firmware version
```

### Full pre-launch verification sequence
```bash
# 1. Device accessible (reliable)
which hailortcli && hailortcli fw-control identify

# 2. Python SDK importable
python3 -c "import hailo_platform; print('hailo_platform OK')"

# 3. App framework importable
python3 -c "from hailo_apps.python.core.common.defines import *; print('hailo_apps OK')"

# 4. Input file exists (if file input)
ls -la /path/to/video.mp4
```

## OpenCV Display

### Window too small with VLM crop
`Backend.convert_resize_image()` returns 336×336 — too small for a display window.
Always resize to at least 640×640 before `cv2.imshow()`:
```python
display = cv2.resize(frame, (640, 640), interpolation=cv2.INTER_LINEAR)
```

### Overlay text overflows window
VLM responses can be 100+ characters. Never truncate to a fixed width — instead
wrap text into multiple lines and make the overlay banner height dynamic:
```python
banner_h = 35 + 22 * len(wrapped_lines)
```

### End-of-video drops pending inference
If you `break` when `get_frame()` returns `None`, any pending async inference is
lost. The user never sees the result.
**Fix**: Wait for `vlm_future.result()` before breaking, then redraw the overlay
and hold the frame on screen for ~5 seconds.

## GStreamer Pipeline

### Missing Queue Between Elements
GStreamer needs explicit `queue` elements to create thread boundaries. Without them, everything runs in one thread and performance suffers.

### Wrong Pipeline String Concatenation
```python
# ❌ Missing ! separator or double !!
pipeline = f"{source}{inference}{display}"
pipeline = f"{source} !! {inference}"

# ✅ Single ! with spaces
pipeline = f"{source} ! {inference} ! {display}"
```

## Resource Cleanup Checklist

When building an app, ensure ALL of these are handled:
- [ ] `cv2.VideoCapture.release()` / `picam2.stop()`
- [ ] `cv2.destroyAllWindows()`
- [ ] `backend.close()` (sends sentinel to worker)
- [ ] `vlm.release()` / `llm.release()` (in worker process)
- [ ] `vdevice.release()` (in worker process, after model release)
- [ ] `ThreadPoolExecutor.shutdown(wait=True)` (if used)

## Logging Anti-Patterns

### Wrong: print() for operational messages
```python
print("Starting inference...")  # Lost in output, no timestamp, no level
```

### Right: Logger
```python
logger.info("Starting inference...")
```

### Exception: print() IS correct for:
- Real-time streamed VLM output (user-facing)
- Interactive prompts ("Press Enter to continue")
- Summary reports at end of session
