# Toolset: VLM Backend API Reference

> Complete API reference for the VLM Backend class used in gen AI applications.

## Backend Class

**Location**: `hailo_apps/python/gen_ai_apps/vlm_chat/backend.py`

Multiprocessing wrapper that runs VLM inference in a separate process for non-blocking operation.

### Constructor

```python
Backend(
    hef_path: str,                    # Path to VLM HEF model file
    max_tokens: int = 200,            # Maximum tokens to generate
    temperature: float = 0.1,         # Sampling temperature (0.0-1.0)
    seed: int = 42,                   # Random seed for reproducibility
    system_prompt: str = "You are a helpful assistant that analyzes images and answers questions about them."
)
```

**Behavior**: Spawns a worker process that:
1. Creates `VDevice` with `SHARED_VDEVICE_GROUP_ID`
2. Loads `VLM` model from HEF
3. Loops on request queue, running inference for each request
4. Streams tokens to stdout in real-time
5. Returns full result via response queue

### vlm_inference()

```python
def vlm_inference(
    self,
    image: np.ndarray,    # Input image (BGR format from OpenCV)
    prompt: str,          # User question/prompt
    timeout: int = 30     # Timeout in seconds
) -> dict:
```

**Returns**:
```python
{
    "answer": "A person is walking across the room carrying a bag.",  # Full text response
    "time": "2.34 seconds"                                     # Inference duration
}
```

**Error returns**:
```python
{"answer": "Error: ...", "time": "error"}           # Inference error
{"answer": "Request timed out after 30 seconds", "time": "30+ seconds"}  # Timeout
```

### convert_resize_image() (static)

```python
@staticmethod
def convert_resize_image(
    image_array: np.ndarray,          # Input image (BGR)
    target_size: tuple = (336, 336)   # Target (width, height)
) -> np.ndarray:
```

**Behavior**:
1. Converts BGR → RGB
2. Scales to cover target size
3. Center-crops to exact target dimensions
4. Returns `np.uint8` array

**Use this whenever passing images to VLM inference.**

### close()

```python
def close(self) -> None:
```

Sends `None` sentinel to worker process, waits for graceful shutdown (2s timeout), then terminates.

**Always call this on shutdown** — failing to do so leaves orphaned processes.

## Worker Process

```python
def vlm_worker_process(
    request_queue: mp.Queue,
    response_queue: mp.Queue,
    hef_path: str,
    max_tokens: int,
    temperature: float,
    seed: int
) -> None:
```

Runs in separate process. Handles inference loop:
1. Receives `{"numpy_image": ..., "prompts": {"system_prompt": ..., "user_prompt": ...}}`
2. Builds VLM prompt format
3. Runs `vlm.generate()` streaming
4. Filters `<|im_end|>` tokens
5. Returns `{"result": {...}, "error": None}`

## Reusing the Backend

The Backend class is **designed to be reusable**. To create a variant app:

1. **Import directly**: `from hailo_apps.python.gen_ai_apps.vlm_chat.backend import Backend`
2. **Customize via constructor**: Change `system_prompt`, `max_tokens`, `temperature`
3. **Different prompts per call**: Pass different `prompt` strings to `vlm_inference()`

```python
# Example: Scene monitor using same backend
backend = Backend(
    hef_path=str(hef_path),
    max_tokens=300,
    temperature=0.1,
    system_prompt="You are a scene monitoring assistant. Describe what is happening."
)
result = backend.vlm_inference(frame, "What is happening in the scene right now?")
```

## Thread Safety

- The Backend uses **multiprocessing** (not threading) — safe across processes
- Request/response queues are `mp.Queue` with `maxsize=10`
- Only **one inference at a time** per backend instance
- For concurrent inference, create multiple Backend instances (each gets its own worker)
