# Speech Recognition — Hailo-8/8L/10H

Whisper speech-to-text that runs on **all Hailo accelerators** (Hailo-8, Hailo-8L, Hailo-10H).

Record from your microphone and get real-time transcription, or transcribe audio files.

Unlike `simple_whisper_chat` (H10-only, uses `hailo_platform.genai.Speech2Text`), this app uses the low-level HailoRT `InferModel` API with separate encoder/decoder HEFs — compatible with all Hailo devices.

## Prerequisites

- Hailo-8, Hailo-8L, or Hailo-10H accelerator
- Python 3.10+, HailoRT 4.20+
- `ffmpeg` and `libportaudio2`: `sudo apt install ffmpeg libportaudio2`

## Installation

```bash
pip install -e ".[speech-rec]"
```

Models (HEF files and decoder assets) are managed by the repo's central resource system
(`resources_config.yaml`) and **auto-downloaded on first run** via `resolve_hef_paths()`.
No manual download step is needed.

## Usage

**Live microphone recording (interactive loop):**
```bash
python -m hailo_apps.python.standalone_apps.speech_recognition.speech_recognition
```
Press Enter to start recording, Enter again to stop. Press 'q' to quit.

**Transcribe an audio file:**
```bash
python -m hailo_apps.python.standalone_apps.speech_recognition.speech_recognition \
    --audio /path/to/audio.wav
```

### Options

| Flag | Description |
|---|---|
| `--audio PATH` | Transcribe a file instead of recording |
| `--arch {hailo8,hailo8l,hailo10h}` | Target architecture (auto-detected if omitted) |
| `--variant {base,tiny,tiny.en}` | Whisper variant (default: `base`) |
| `--duration N` | Max recording length in seconds (default: 10) |
| `--list-models` | List available models and exit |

## Supported Models

| Variant | Hailo-8 | Hailo-8L | Hailo-10H |
|---|---|---|---|
| `base` | ✓ | ✓ | ✓ |
| `tiny` | ✓ | ✓ | ✓ |
| `tiny.en` | — | — | ✓ |
