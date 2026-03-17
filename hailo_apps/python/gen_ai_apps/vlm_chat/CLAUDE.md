# VLM Chat

## What This App Does
An interactive computer vision application that uses Hailo's Vision Language Model (VLM) to analyze camera frames and answer questions about them in real time. The app displays a live video feed in an OpenCV window; users capture a frame by pressing Enter in the terminal, type a question about the image, and receive a streamed text response from the Qwen2-VL-2B-Instruct model. The video freezes during Q&A mode and resumes after viewing the result.

## Architecture
- **Type:** GenAI app (Hailo-10H only)
- **Models:** Qwen2-VL-2B-Instruct (VLM)
- **SDK:** `hailo_platform.genai` (VLM class via shared VDevice)
- **Dependencies:** OpenCV, NumPy, Hailo Platform SDK
- **Multiprocessing:** VLM inference runs in a separate worker process to avoid blocking the video display thread

## Key Files
| File | Purpose |
|------|---------|
| `vlm_chat.py` | Main application: `VLMChatApp` with state machine (STREAMING/CAPTURED/PROCESSING/RESULT), camera handling, terminal input |
| `backend.py` | `Backend` class: multiprocessing VLM worker, image preprocessing (central crop to 336x336), inference request/response queues |

## How It Works
1. Parse CLI args, resolve VLM HEF path, initialize camera (USB or RPi)
2. Start `Backend` which spawns a separate process with VLM model loaded
3. Main loop displays live video with state machine:
   - STREAMING: live camera feed, Enter captures frame
   - CAPTURED: frozen frame, user types question (default: "Describe the image")
   - PROCESSING: VLM inference runs in background process, response streamed to terminal
   - RESULT: user presses Enter to return to live video
4. Images preprocessed with central crop (scale-to-cover + center crop to 336x336)
5. VLM generates response with configurable temperature (0.1), max tokens (200), and system prompt

## Common Use Cases
- Interactive image analysis and visual question answering
- Real-time scene description from camera feeds
- Prototyping vision-language applications on edge hardware
- Educational tool for understanding VLM capabilities

## How to Extend
- Change model parameters: modify `MAX_TOKENS`, `TEMPERATURE`, `SYSTEM_PROMPT` constants in `vlm_chat.py`
- Save captured frames: set `SAVE_FRAMES = True` in `vlm_chat.py`
- Custom image preprocessing: modify `Backend.convert_resize_image()` for different crop/resize strategies
- Add follow-up questions: extend the state machine to allow multiple questions per captured frame

## Related Apps
| App | When to use instead |
|-----|-------------------|
| `simple_vlm_chat` | Just want to test VLM on a static image without camera |
| `voice_assistant` | Need voice-based interaction without vision |
| `agent_tools_example` | Need LLM with tool calling capabilities |
