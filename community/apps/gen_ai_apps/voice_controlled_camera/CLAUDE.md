# Voice-Controlled Smart Camera

## What This App Does
A hands-free smart camera that responds to voice commands for real-time object detection and scene description. Combines Whisper (STT), a Qwen LLM (intent parsing), Qwen2-VL (scene analysis), and Piper TTS (spoken responses), all running on Hailo-10H.

## Architecture
- **Type:** Gen AI app (voice + VLM)
- **Pattern:** Whisper STT → LLM intent classification → VLM image understanding → Piper TTS, all on Hailo-10H with a shared VDevice
- **Models:** Whisper-Base (STT), Qwen2.5-1.5B-Instruct (LLM), Qwen2-VL-2B-Instruct (VLM)
- **Hardware:** hailo10h
- **Postprocess:** LLM intent routing (describe / detect / read keywords), VLM scene description, TTS synthesis

## Key Files
| File | Purpose |
|------|---------|
| `voice_controlled_camera.py` | Main: voice-command loop, intent classification, backend management, camera thread, TTS, mic/keyboard I/O |

## How to Run
```bash
source setup_env.sh
python community/apps/gen_ai_apps/voice_controlled_camera/voice_controlled_camera.py --input usb
```
Optional: `--no-tts`, `--vad`.

## How to Extend
- Add conversational context memory across commands or command confirmation for complex actions.
- Add new intents by extending the keyword/intent-classification routing.
