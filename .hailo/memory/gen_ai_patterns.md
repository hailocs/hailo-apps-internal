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
- **NEVER freeze video**: Keep playing live video at all times. VLM inference takes 10-30s; freezing makes the app feel broken and wastes video. Inference runs in a background thread.
- **Timer-based capture**: Use `time.time()` delta check in the display loop, NOT `time.sleep(interval)` — sleep blocks the display.
- **Non-blocking inference**: Submit via `ThreadPoolExecutor.submit()` and track with a `_inference_pending` flag to avoid queue overflow.
- **Event classification**: Keyword matching on VLM response is sufficient — no need for a second LLM call.
- **Signal handler pitfall**: Only set `self.running = False` in the handler. Do cleanup in the main loop's `finally` block to avoid deadlocks.
- **Display overlay**: Use `cv2.addWeighted()` for semi-transparent overlays on the camera feed.
- **Display size**: Resize frames to 640×640 before display — the raw 336×336 VLM crop is too small to read.
- **Text wrapping**: VLM responses are long. Wrap text into lines of ~70 chars max and use a dynamic banner height.
- **Print to terminal**: Always `print()` the classified activity and description to the terminal on each event — `logger.info()` is not visible at default log level.
- **End-of-video**: When `get_frame()` returns `None`, wait for any pending `vlm_future` to finish, then redraw overlay with the result and hold 5 seconds before exiting.
- **Freeze pattern is ONLY for interactive apps**: `vlm_chat` freezes because the user explicitly captures a frame and types a question. Continuous monitoring apps must never freeze.

### App Registration (CRITICAL — Two Places)
New VLM apps must be registered in **two** files or `resolve_hef_path()` will fail:
1. `hailo_apps/python/core/common/defines.py` — add `MY_APP = "my_app"` constant
2. `hailo_apps/config/resources_config.yaml` — add `my_app: *vlm_chat_app` (or custom model entry)
Forgetting #2 causes `KeyError: 'my_app'` at runtime.

### Pre-Launch Environment Checks
Before launching a VLM app, verify in this order:
1. `hailortcli fw-control identify` — confirms device is accessible, shows architecture
2. `python3 -c "import hailo_platform"` — SDK installed
3. `python3 -c "from hailo_apps.python.core.common.defines import *"` — framework importable
4. Input file exists (for file sources): `ls -la /path/to/video`
5. For short videos: check duration and set `--interval` lower than video length
Note: `lsmod | grep hailo_pci` is NOT reliable — some setups have built-in drivers.

### Queue Deadlock on Shutdown
If the main process exits without sending the `None` sentinel to the worker, the worker blocks on `request_queue.get()` forever → orphaned process.
**Fix**: Always send sentinel in `close()`, use `join(timeout=2)`, then `terminate()`.

### Camera Release Race Condition
If `cv2.VideoCapture.release()` is called from a different thread than `read()`, OpenCV can crash.
**Fix**: Camera init and release must happen in the same thread (the video thread).

### YAML Config — Safe Alias Insertion Point
When adding `new_app: *vlm_chat_app` to `resources_config.yaml`, place it **after**
the complete block of the preceding key — never between a key and its value mapping.
Breaking the YAML structure causes `Invalid YAML` errors at runtime that reference
a line far from the actual insertion point, making debugging confusing.
**Always validate** after editing: `python3 -c "import yaml; yaml.safe_load(open('...'))"`

### CLI Custom Args Must Precede handle_list_models_flag()
In `main()`, add all `parser.add_argument("--interval", ...)` calls **before**
`handle_list_models_flag(parser, APP)`. Otherwise `--help` won't show them because
argparse renders help from whatever args are registered when `--help` is parsed.

### MAX_TOKENS for Monitoring vs Interactive Apps
| Use Case | MAX_TOKENS | Why |
|---|---|---|
| Monitoring (continuous) | 100–150 | Concise; avoids repetitive loops |
| Interactive Q&A | 200–300 | Detailed answers expected |
| JSON output | 150–200 | Structured but bounded |

Qwen2-VL tends to produce repetitive text when `max_generated_tokens` is high and
the answer is short. Always pair a low `MAX_TOKENS` with a prompt that says
"Be concise — one or two sentences."

### Event Keyword Classification — Priority Order
Put specific-action keywords (sniffing, chewing, running) before generic-state
keywords (sitting, idle). The classifier matches the first hit in iteration order.
Alternatively, instruct the VLM to output a structured label:
`"Respond with exactly one word from: sleeping, eating, drinking, playing, ..."`
and parse the first word — this eliminates keyword ambiguity entirely.

### Video Duration Check Before Launch
For file inputs, always check video duration and ensure `--interval` is well below
the total length. A 60s video with `--interval 15` (default) only gets ~2 analyses
because inference takes 5-45s each. Use `--interval 5` for short clips.
```python
import cv2
cap = cv2.VideoCapture(path)
duration = cap.get(cv2.CAP_PROP_FRAME_COUNT) / cap.get(cv2.CAP_PROP_FPS)
cap.release()
```

### QT_QPA_PLATFORM Must Be Set Early
```python
import os
os.environ["QT_QPA_PLATFORM"] = 'xcb'  # BEFORE any cv2 or Qt import
import cv2  # OK now
```
If set after import, OpenCV GUI functions may crash on headless Linux.

## Build Session Benchmarks (Hailo-10H, Qwen2-VL-2B)

### VLM Inference Timing
Measured on Hailo-10H with Qwen2-VL-2B-Instruct, `MAX_TOKENS=300`, `temperature=0.1`:
| Metric | Value |
|---|---|
| Average inference time | 4.7s per frame |
| Range | 3.2s – 5.4s |
| Throughput at `--interval 5` | ~8 analyses per 51s video |

These timings include token generation overhead. Shorter `MAX_TOKENS` (100–150)
can reduce inference time by ~30% since less tokens need to be generated.

### Build Efficiency Metrics (Dog Monitor App Reference)
Full app build (3 files, 475 LOC, validated, tested, launched):
| Metric | Value |
|---|---|
| Wall-clock time | ~8 minutes |
| Tool calls | 46 |
| Files read | 14 |
| Validation pass | 20/20 first try |
| VLM events detected | 8 in 51s test run |

### Context Efficiency — Local Docs vs External (Kapa MCP)
The local `.hailo/` documentation (SKILL.md, memory files, toolset references,
reference implementations) provided **100% of the context** needed to build a
complete VLM app. Kapa MCP was not invoked.

**When Kapa IS needed** (for future reference):
- Undocumented `hailo_platform.genai` API parameters
- HEF compatibility questions across SDK versions
- HailoRT driver troubleshooting for non-standard setups
- Model Zoo version-specific download URLs or naming changes

**When local docs are sufficient** (Kapa NOT needed):
- Building VLM apps following the existing pattern
- Event tracking, display overlay, camera integration
- CLI argument parsing, HEF resolution, signal handling
- Any task where SKILL.md + memory files + reference implementation cover the pattern

### Short Video Strategy
For video files under 120s, inference throughput matters. Each VLM call takes ~5s.
- `--interval 15` (default) on a 60s video = only ~2 analyses
- `--interval 5` on a 60s video = ~8 analyses (almost every 5s boundary triggers)
- Always set `--interval` lower than `video_duration / 3` for meaningful monitoring
