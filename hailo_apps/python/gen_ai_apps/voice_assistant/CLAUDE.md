# Voice Assistant

## What This App Does
An interactive voice-controlled AI assistant that runs entirely on Hailo-10H hardware. The app captures speech via microphone, transcribes it using Whisper speech-to-text, generates a response using an LLM (Qwen2.5-1.5B-Instruct), and speaks the response back using Piper TTS. It provides a terminal-based interface with keyboard controls for recording, context management, and generation interruption.

## Architecture
- **Type:** GenAI app (Hailo-10H only)
- **Models:** Whisper-Base (speech-to-text) + Qwen2.5-1.5B-Instruct (LLM response generation)
- **SDK:** `hailo_platform.genai` (LLM, Speech2Text via shared VDevice)
- **Dependencies:** `pip install -e ".[gen-ai]"` (piper-tts, sounddevice); Piper TTS voice model must be installed separately

## Key Files
| File | Purpose |
|------|---------|
| `voice_assistant.py` | Main application: `VoiceAssistantApp` class orchestrating STT, LLM, and TTS components |

## How It Works
1. Initialize shared VDevice with group ID for multi-model usage
2. Load Whisper-Base for speech-to-text and Qwen2.5-1.5B-Instruct for LLM responses
3. Optionally initialize Piper TTS for text-to-speech output
4. `VoiceInteractionManager` handles the terminal UI with keyboard controls (Space=record, Q=quit, C=clear, X=abort)
5. On audio ready: transcribe with Whisper, format prompt, stream LLM response token-by-token
6. During streaming, tokens are buffered and chunked into sentences for TTS playback
7. After TTS finishes playing, listening automatically restarts (handshake pattern)

## Common Use Cases
- Hands-free AI assistant on edge devices
- Voice-controlled home automation interface
- Accessibility tool for text-based AI interaction
- Prototyping voice AI applications on Hailo hardware

## How to Extend
- Change LLM model: modify `VOICE_ASSISTANT_MODEL_NAME` in defines or provide custom HEF path
- Customize personality: edit the `LLM_PROMPT_PREFIX` in defines
- Disable TTS: run with `--no-tts` for text-only output
- Enable VAD: use `--vad` flag for voice activity detection (auto-detect speech start/stop)
- Add tool calling: see the `agent_tools_example` app which extends this pattern with function calling

## Related Apps
| App | When to use instead |
|-----|-------------------|
| `agent_tools_example` | Need voice + tool calling (function execution) capabilities |
| `simple_llm_chat` | Just want to test LLM text generation without voice |
| `simple_whisper_chat` | Just want to test speech-to-text transcription from audio files |
