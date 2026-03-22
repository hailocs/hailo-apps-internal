# Gen AI App Patterns — Memory

## VLM Application Architecture

### Multiprocessing Backend (CRITICAL)
VLM inference blocks for 1-3 seconds. **Always** run inference in a separate process:

```
Main Process          Worker Process
├── Camera loop       ├── VDevice init
├── OpenCV display    ├── VLM model load
├── User input        └── Inference loop
├── State machine         ├── request_queue.get()
└── Signal handling       ├── vlm.generate() → stream tokens
                          ├── response_queue.put(result)
                          └── vlm.clear_context()
```

- Use `mp.Queue(maxsize=10)` for both request and response
- Send `None` sentinel to stop worker process
- Worker must call `vlm.release()` and `vdevice.release()` on exit

### VLM Prompt Format
```python
prompt = [
    {"role": "system", "content": [{"type": "text", "text": system_prompt}]},
    {"role": "user", "content": [
        {"type": "image"},
        {"type": "text", "text": user_prompt}
    ]}
]
```
- `{"type": "image"}` is a placeholder — matched to `frames=[numpy_image]` in `vlm.generate()`
- Multiple images: add multiple `{"type": "image"}` entries, pass matching `frames` list

### Token Streaming
```python
with vlm.generate(prompt=prompt, frames=[image], temperature=0.1, 
                   seed=42, max_generated_tokens=200) as generation:
    for chunk in generation:
        if chunk != '<|im_end|>':
            response += chunk
vlm.clear_context()  # ALWAYS clear after each inference
```

### Image Preprocessing
- VLM expects **RGB 336×336** (`np.uint8`)
- OpenCV gives **BGR** — must convert with `cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)`
- Use central crop (not letterbox/pad) to fill target resolution
- `Backend.convert_resize_image()` handles this correctly — reuse it

## LLM Tool Calling
- LLM generates JSON tool calls in response
- Parse with `llm_utils.tool_parsing.parse_tool_call()`
- Execute with `llm_utils.tool_execution.execute_tool()`
- Tool results are formatted back into conversation context

## Voice Pipeline
```
Audio In → VAD → Whisper (STT) → LLM/VLM → Piper (TTS) → Audio Out
```
- Whisper runs on Hailo-10H (fast)
- Piper TTS runs on CPU (lightweight)
- VAD uses webrtcvad for voice activity detection

## Discovered Issues

### Continuous Monitoring Pattern (Dog Monitor Variant)
When building continuous monitoring apps that reuse the VLM Chat Backend:
- **Timer-based capture**: Use `time.time()` delta check in the display loop, NOT `time.sleep(interval)` — sleep blocks the display.
- **Non-blocking inference**: Submit via `ThreadPoolExecutor.submit()` and track with a `_inference_pending` flag to avoid queue overflow.
- **Event classification**: Keyword matching on VLM response is sufficient — no need for a second LLM call.
- **Signal handler pitfall**: Only set `self.running = False` in the handler. Do cleanup in the main loop's `finally` block to avoid deadlocks.
- **Display overlay**: Use `cv2.addWeighted()` for semi-transparent overlays on the camera feed.

### Queue Deadlock on Shutdown
If the main process exits without sending the `None` sentinel to the worker, the worker blocks on `request_queue.get()` forever → orphaned process.
**Fix**: Always send sentinel in `close()`, use `join(timeout=2)`, then `terminate()`.

### Camera Release Race Condition
If `cv2.VideoCapture.release()` is called from a different thread than `read()`, OpenCV can crash.
**Fix**: Camera init and release must happen in the same thread (the video thread).

### QT_QPA_PLATFORM Must Be Set Early
```python
import os
os.environ["QT_QPA_PLATFORM"] = 'xcb'  # BEFORE any cv2 or Qt import
import cv2  # OK now
```
If set after import, OpenCV GUI functions may crash on headless Linux.
