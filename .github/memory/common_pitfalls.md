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
