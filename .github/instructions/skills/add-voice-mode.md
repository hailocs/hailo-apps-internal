# Skill: Add Voice Mode to Application

> Add speech-to-text input and text-to-speech output to any Hailo app.

## When to Use This Skill

- User wants **hands-free voice control** of an application
- User needs **speech-to-text** (Whisper on Hailo) for input
- User wants **text-to-speech** (Piper TTS) for responses
- User wants **voice activity detection** (VAD) for push-to-talk or auto-detect

## Available Voice Components

| Component | Module | Purpose |
|---|---|---|
| Speech-to-Text | `voice_processing.speech_to_text` | Whisper STT on Hailo |
| Text-to-Speech | `voice_processing.text_to_speech` | Piper TTS (CPU) |
| Audio Recorder | `voice_processing.audio_recorder` | Microphone capture |
| Audio Player | `voice_processing.audio_player` | Speaker playback |
| VAD | `voice_processing.vad` | Voice Activity Detection |
| Interaction | `voice_processing.interaction` | High-level VoiceInteractionManager |

## Integration Pattern

### Basic Voice I/O

```python
from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.speech_to_text import SpeechToText
from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.text_to_speech import TextToSpeech
from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.audio_recorder import AudioRecorder

# Initialize STT (uses Whisper on Hailo)
stt = SpeechToText(vdevice, whisper_hef_path)

# Initialize TTS (uses Piper, CPU-based)
tts = TextToSpeech()

# Record and transcribe
recorder = AudioRecorder()
audio_data = recorder.record(duration=5)
text = stt.transcribe(audio_data)

# Speak response
tts.speak("The dog is drinking water")
```

### VoiceInteractionManager (High-Level)

```python
from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.interaction import VoiceInteractionManager

vim = VoiceInteractionManager(
    vdevice=vdevice,
    whisper_hef_path=whisper_hef_path,
    vad_enabled=True,
    vad_aggressiveness=3,
)

# Listen for voice input
user_text = vim.listen()

# Speak response
vim.speak("I detected the dog near the water bowl")
```

## CLI Arguments for Voice

Add voice-specific arguments:
```python
from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.vad import add_vad_args

parser = get_standalone_parser()
parser.add_argument("--voice", action="store_true", help="Enable voice mode")
parser.add_argument("--no-tts", action="store_true", help="Disable text-to-speech")
add_vad_args(parser)  # Adds --vad, --vad-aggressiveness, --vad-energy-threshold
```

## Dependencies

Voice mode requires the `[gen-ai]` optional dependencies:
```
PyAudio
piper-tts
sounddevice
webrtcvad-wheels
```

Install with: `pip install hailo-apps[gen-ai]`

## Audio Troubleshooting

```python
from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.audio_troubleshoot import troubleshoot_audio
troubleshoot_audio()  # Diagnoses microphone/speaker issues
```

CLI: `hailo-audio-troubleshoot`
