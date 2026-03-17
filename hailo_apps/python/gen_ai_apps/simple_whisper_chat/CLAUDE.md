# Simple Whisper Chat

## What This App Does
A minimal example demonstrating audio transcription using Hailo's Whisper speech-to-text model. The script loads a WAV audio file (default: `audio.wav` in the same directory), converts it to float32 format, runs it through the Whisper-Base model on Hailo-10H, and prints the transcribed text. This is a non-interactive, single-shot example for learning the Speech2Text API. Models are auto-downloaded on first run.

## Architecture
- **Type:** GenAI app (Hailo-10H only)
- **Models:** Whisper-Base (speech-to-text)
- **SDK:** `hailo_platform.genai` (Speech2Text class with `generate_all_segments`)
- **Dependencies:** NumPy, Hailo Platform SDK (uses Python's built-in `wave` module for audio loading)

## Key Files
| File | Purpose |
|------|---------|
| `simple_whisper_chat.py` | Single-file example: VDevice init, Whisper load, WAV file reading, audio preprocessing, transcription, cleanup |
| `audio.wav` | Sample audio file for testing |

## How It Works
1. Parse optional `--hef-path`, `--list-models`, and `--audio` arguments
2. Resolve Whisper HEF path with auto-download (Hailo-10H only)
3. Create VDevice with shared group ID, initialize Speech2Text
4. Load WAV file using Python's `wave` module, read raw PCM frames
5. Convert int16 audio to float32 normalized to [-1, 1] range, ensure little-endian format
6. Call `speech2text.generate_all_segments()` with task=TRANSCRIBE, language="en", timeout=15s
7. Combine all segments into complete transcription, print result, clean up resources

## Common Use Cases
- Learning the Hailo GenAI Speech2Text API
- Verifying Whisper model installation and device setup
- Batch transcription of audio files
- Starting point for building speech-to-text applications

## How to Extend
- Custom audio: use `--audio /path/to/file.wav` for different audio files
- Change language: modify the `language` parameter in `generate_all_segments()`
- Add real-time recording: use `sounddevice` to capture microphone audio (see `voice_assistant` app)
- Process multiple files: wrap the transcription in a loop over a directory of WAV files
- Add translation: change `task` from `Speech2TextTask.TRANSCRIBE` to `Speech2TextTask.TRANSLATE`

## Related Apps
| App | When to use instead |
|-----|-------------------|
| `voice_assistant` | Need real-time microphone recording + LLM response + TTS |
| `simple_llm_chat` | Need text-only LLM without audio input |
| `agent_tools_example` | Need speech input with tool calling capabilities |
