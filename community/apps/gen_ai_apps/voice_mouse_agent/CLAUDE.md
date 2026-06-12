# Voice Mouse Agent

## What This App Does
A voice-controlled mouse agent for Hailo-10H. It listens continuously on the microphone, transcribes with Whisper STT, interprets the request with an LLM via tool-calling, and executes mouse actions (move, click, scroll, drag) on the local display through `pyautogui`.

## Architecture
- **Type:** Gen AI app (voice agent with tool-calling)
- **Pattern:** Whisper STT → LLM tool-calling (`mouse_control` tool) → `pyautogui` action execution
- **Models:** Whisper-Base (STT on Hailo-10H), Qwen2.5-1.5B-Instruct (LLM tool-calling on Hailo-10H)
- **Hardware:** hailo10h
- **Postprocess:** LLM tool generation (single `mouse_control` tool: move, move_to, left/right/double click, scroll, drag); `pyautogui` executes on the host

## Key Files
| File | Purpose |
|------|---------|
| `voice_mouse_agent.py` | Main: voice-listen loop, Whisper + LLM inference, tool parse/execute, mouse dispatch |
| `tools/config.yaml` | `mouse_control` tool definition with action examples |
| `app.yaml` | App metadata (type gen_ai, hailo_arch hailo10h, tags agent/voice/mouse) |

## How to Run
```bash
source setup_env.sh
./community/apps/gen_ai_apps/voice_mouse_agent/run.sh
# or: python -m hailo_apps.python.gen_ai_apps.voice_mouse_agent.voice_mouse_agent
```
Optional: `--vad`, `--debug`.

## How to Extend
- Add new actions (window management, app shortcuts, macros) by extending `tools/config.yaml` and the tool handler.
- Add voice feedback (TTS) to confirm executed actions.
