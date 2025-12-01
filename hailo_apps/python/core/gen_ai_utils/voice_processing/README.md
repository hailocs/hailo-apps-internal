# Voice Processing Module

This module provides components for building voice-enabled applications using Hailo's AI platform.

## Components

- **`VoiceInteractionManager`**: Manages the interaction loop, including recording, user input handling, and callback execution.
- **`AudioRecorder`**: Handles microphone recording using PyAudio
- **`SpeechToTextProcessor`**: Wraps Hailo's Speech2Text API (Whisper model)
- **`TextToSpeechProcessor`**: Handles speech synthesis using Piper TTS

## Installation

### Prerequisites

Before using the voice processing module, you need to install the Piper TTS voice model.

### Piper TTS Model Installation

The Piper TTS model files must be installed in the centralized location: `local_resources/piper_models/`

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

## Usage

### Voice Interaction Manager

The `VoiceInteractionManager` simplifies building voice applications by handling the main loop and user controls.

```python
from hailo_apps.python.core.gen_ai_utils.voice_processing.interaction import VoiceInteractionManager

def on_audio_ready(audio_data):
    # Process audio here (e.g., transcribe)
    print("Audio received")

def on_processing_start():
    # Optional: Stop TTS playback or prepare system
    pass

def on_abort():
    # Optional: Abort current operation
    print("Aborting...")

manager = VoiceInteractionManager(
    title="My Voice App",
    on_audio_ready=on_audio_ready,
    on_processing_start=on_processing_start,
    on_abort=on_abort
)

# Start the interaction loop
manager.run()
```

### Individual Components

#### Speech-to-Text

```python
from hailo_platform import VDevice
from hailo_apps.python.core.gen_ai_utils.voice_processing.speech_to_text import SpeechToTextProcessor

vdevice = VDevice()
s2t = SpeechToTextProcessor(vdevice)

# Transcribe audio
text = s2t.transcribe(audio_data, language="en")
print(f"Transcribed: {text}")
```

#### LLM Processing

```python
from hailo_platform.genai import LLM
from hailo_apps.python.core.common.core import get_resource_path
from hailo_apps.python.core.common.defines import RESOURCES_MODELS_DIR_NAME, LLM_MODEL_NAME_H10

# Get model path
model_path = str(get_resource_path(
    pipeline_name=None,
    resource_type=RESOURCES_MODELS_DIR_NAME,
    model=LLM_MODEL_NAME_H10
))

llm = LLM(vdevice, model_path)

# Generate response
prompt = [{'role': 'user', 'content': "Hello, how are you?"}]
with llm.generate(prompt) as gen:
    for token in gen:
        print(token, end="", flush=True)

# Clear context
llm.clear_context()
```

#### Text-to-Speech

```python
from hailo_apps.python.core.gen_ai_utils.voice_processing.text_to_speech import TextToSpeechProcessor

tts = TextToSpeechProcessor()

# Queue text for speech
tts.queue_text("Hello, this is a test.")

# Interrupt ongoing speech
tts.interrupt()

# Cleanup
tts.stop()
```

#### Audio Recording

```python
from hailo_apps.python.core.gen_ai_utils.voice_processing.audio_recorder import AudioRecorder

recorder = AudioRecorder(debug=True)

# Start recording
recorder.start()

# ... user speaks ...

# Stop and get audio
audio_data = recorder.stop()

# Cleanup
recorder.close()
```

## Microphone Configuration

**High-quality microphone input is crucial for optimal speech recognition performance.**

### Testing Your Microphone

```bash
# List available audio devices
arecord -l

# Test recording (5 seconds)
arecord -d 5 -f cd test.wav

# Play back the recording
aplay test.wav
```

### Raspberry Pi Microphone Setup

If your microphone is not working on Raspberry Pi:

1. Connect your USB microphone
2. Right-click the **Volume Control** icon in the system tray
3. Select **"Device Profiles"**
4. Choose **"Pro Audio"** profile for your USB device

The Pro Audio profile provides direct access to the audio device, bypassing potential compatibility issues.

### Audio Quality Tips

- Use a USB microphone for best results
- Minimize background noise
- Speak clearly and at a consistent volume
- Position the microphone 6-12 inches from your mouth
- Test your setup before running the application

## Troubleshooting

### "PIPER TTS MODEL NOT FOUND" Error

If you see this error, the Piper model files are not installed. Follow the installation instructions above.

### Poor Transcription Quality

1. **Check microphone quality:**
   ```bash
   arecord -d 5 -f cd test.wav && aplay test.wav
   ```

2. **Verify audio device selection:**
   ```bash
   arecord -l  # List devices
   ```

3. **Reduce background noise**

4. **Speak clearly and at moderate pace**

### TTS Not Working

1. **Verify Piper installation:**
   ```bash
   ls -lh local_resources/piper_models/
   python3 -c "from piper import PiperVoice; print('Piper OK')"
   ```

2. **Check audio output:**
   ```bash
   speaker-test -t wav -c 2
   ```

3. **Verify file permissions:**
   ```bash
   chmod -R 755 local_resources/piper_models/
   ```

## Applications Using This Module

- **voice_asistant**: Interactive voice-controlled AI assistant
- **voice_chat_agent**: Voice-enabled tool-calling agent

See their respective README files for application-specific setup and usage.

## API Reference

For detailed API documentation, see the docstrings in each module:
- `interaction.py`
- `audio_recorder.py`
- `speech_to_text.py`
- `text_to_speech.py`

## Additional Resources

- **Piper TTS Documentation**: https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/API_PYTHON.md
- **Hailo Platform Documentation**: https://hailo.ai/developer-zone/documentation/
- **PyAudio Documentation**: https://people.csail.mit.edu/hubert/pyaudio/docs/
