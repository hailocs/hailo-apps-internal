# Voice Processing Module

This module provides components for building voice-enabled applications using Hailo's AI platform.
It handles audio recording, speech-to-text, text-to-speech, and interaction management with robust cross-platform support.

## Components

- **`VoiceInteractionManager`**: Manages the interaction loop, recording, user input, and callbacks.
- **`AudioRecorder`**: Handles microphone recording using `sounddevice` with auto-detection.
- **`SpeechToTextProcessor`**: Wraps Hailo's Speech2Text API (Whisper model).
- **`TextToSpeechProcessor`**: Handles speech synthesis using Piper TTS and playback via `AudioPlayer`.
- **`AudioPlayer`**: Cross-platform audio playback using `sounddevice`.
- **`AudioDiagnostics`**: Tools for device enumeration, testing, and troubleshooting.

## Installation

### Prerequisites

The module relies on `sounddevice` (PortAudio wrapper) for audio I/O and Piper TTS for speech synthesis.

### Piper TTS Model Installation

The Piper TTS model files must be installed in: `local_resources/piper_models/`

#### Quick Installation

```bash
# 1. Navigate to the repository root
cd /path/to/hailo-apps-infra

# 2. Navigate to the piper_models directory
cd local_resources/piper_models

# 3. Download the default voice model (en_US-amy-low)
python3 -m piper.download_voices en_US-amy-low
```

This will download two files (~65MB total):
- `en_US-amy-low.onnx` - The neural network model
- `en_US-amy-low.onnx.json` - Model configuration

#### Verify Installation

```bash
ls -lh local_resources/piper_models/
```

You should see:
```
en_US-amy-low.onnx
en_US-amy-low.onnx.json
```

### Using Alternative Voice Models

Piper supports many voice models in different languages and styles. To use a different voice:

1. **Browse available voices:**
   - Visit: https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/API_PYTHON.md
   - Or list voices: `python3 -m piper.download_voices --list`

2. **Download your chosen voice:**
   ```bash
   cd local_resources/piper_models
   python3 -m piper.download_voices <voice-name>
   ```

3. **Update the configuration:**
   Edit `hailo_apps/python/core/common/defines.py`:
   ```python
   TTS_MODEL_NAME = "your-chosen-voice-name"
   ```

### Common Voice Options

| Voice Name          | Language     | Gender | Size   | Quality    |
| ------------------- | ------------ | ------ | ------ | ---------- |
| `en_US-amy-low`     | English (US) | Female | ~65MB  | Low (fast) |
| `en_US-amy-medium`  | English (US) | Female | ~100MB | Medium     |
| `en_GB-alan-low`    | English (UK) | Male   | ~65MB  | Low (fast) |
| `en_GB-alan-medium` | English (UK) | Male   | ~100MB | Medium     |

## Audio Configuration & Troubleshooting

### Device Selection

The module automatically selects the best available input and output devices. On systems with multiple audio devices (especially Raspberry Pi), you can manually select and save your preferred devices:

```bash
# Interactive device selection
hailo-audio-troubleshoot --select-devices

# Command-line selection
hailo-audio-troubleshoot --select-devices --input-device 2 --output-device 3
```

**How it works:**
- Preferences are saved to `local_resources/audio_device_preferences.json`
- `AudioRecorder`, `AudioPlayer`, and `TextToSpeechProcessor` automatically use saved preferences when `device_id=None`
- Falls back to auto-detection if saved devices are unavailable
- Preferences persist across reboots and sessions

### Troubleshooting

For audio issues, use the built-in troubleshooting tool:

```bash
hailo-audio-troubleshoot
```

This tool lists devices, tests hardware, and provides platform-specific troubleshooting tips.

## Usage

### Voice Interaction Manager

The `VoiceInteractionManager` is the high-level entry point.

```python
from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.interaction import VoiceInteractionManager

def on_audio_ready(audio_data):
    # Process audio here (e.g., transcribe)
    print("Audio received")

manager = VoiceInteractionManager(
    title="My Voice App",
    on_audio_ready=on_audio_ready
)

# Start the interaction loop
manager.run()
```

### Individual Components

#### Speech-to-Text

```python
from hailo_platform import VDevice
from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.speech_to_text import SpeechToTextProcessor

vdevice = VDevice()
s2t = SpeechToTextProcessor(vdevice)

# Transcribe audio
text = s2t.transcribe(audio_data, language="en")
print(f"Transcribed: {text}")
```

#### Text-to-Speech

```python
from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.text_to_speech import TextToSpeechProcessor

tts = TextToSpeechProcessor()  # Uses saved preferences or auto-detects
tts.queue_text("Hello, this is a test.")
tts.interrupt()  # Stop current speech
tts.stop()  # Cleanup
```

#### Audio Recording

```python
from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.audio_recorder import AudioRecorder

recorder = AudioRecorder(debug=True)  # Uses saved preferences or auto-detects
recorder.start()
# ... user speaks ...
audio_data = recorder.stop()
recorder.close()
```

## Platform Specifics

### Raspberry Pi

- **USB Audio**: Strongly recommended over built-in audio
- **Device Profiles**: Use `hailo-audio-troubleshoot --configure` to set USB device profiles (Pro Audio or Duplex)
- See troubleshooting tool for Raspberry Pi-specific setup instructions

### x86 / Desktop

- Works out-of-the-box with standard ALSA/PulseAudio setups
- Ensure microphone is not muted in system settings

## API Reference

See the docstrings in each module for detailed API info:
- `audio_diagnostics.py`
- `audio_player.py`
- `audio_recorder.py`
- `interaction.py`
- `speech_to_text.py`
- `text_to_speech.py`
