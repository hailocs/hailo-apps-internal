# Prompt: Build Voice Assistant App

> **Template** for creating a new voice-enabled application for Hailo-10H
> with Whisper (STT on Hailo) and Piper (TTS on CPU).
> Replace all `<PLACEHOLDERS>` with your specific values.

## The Prompt

---

Build a voice assistant application for Hailo-10H with these specifications:

**App name**: `<app_name>` (snake_case)
**Style**: `<voice_llm_assistant / voice_vlm_assistant / stt_only / add_voice_to_existing>`
**Backend**: `<LLM (text only) / VLM (with camera)>`
**System prompt**: `<your system prompt, e.g., "You are a friendly voice assistant. Keep responses under 2 sentences.">`

**Custom requirements**:
- <requirement 1, e.g., "support VAD for hands-free operation">
- <requirement 2, e.g., "add interrupt support (user can stop agent mid-speech)">
- <requirement 3, e.g., "support --no-tts for text-only fallback">

Follow all conventions from `copilot-instructions.md`:
- Register constant in `defines.py`
- STT (Whisper) runs on Hailo, TTS (Piper) runs on CPU — never reverse
- Use `redirect_stderr(StringIO())` to suppress ALSA noise during audio init
- Use `add_vad_args(parser)` for VAD CLI flags
- Always support `--no-tts` text-only fallback
- Init order: VDevice → STT → LLM/VLM → TTS → VoiceInteractionManager
- Cleanup in reverse order in finally block
- Use `abort_event = threading.Event()` for interruption
- Use `SHARED_VDEVICE_GROUP_ID` for VDevice
- Absolute imports only
- `get_logger(__name__)` for logging

Required dependencies: `[gen-ai]` extras — PyAudio, piper-tts, sounddevice, webrtcvad-wheels

Create files in `hailo_apps/python/gen_ai_apps/<app_name>/`:
- `__init__.py`
- `<app_name>.py` — main app
- `README.md` — usage instructions (include audio setup notes)

Validate:
```bash
python3 -m hailo_apps.python.gen_ai_apps.<app_name>.<app_name> --help
grep -rn "^from \.\|^import \." hailo_apps/python/gen_ai_apps/<app_name>/*.py
# Optional: test audio system
python3 -m hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.audio_troubleshoot