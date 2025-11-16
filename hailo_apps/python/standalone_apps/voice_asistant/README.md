# Hailo Voice Assistant Interactive Application

An interactive voice-controlled AI assistant using Hailo's Speech-to-Text and Large Language Model for real-time audio processing and conversational AI.

## Required Dependency!

Piper TTS (Text To Speach) requires downloading the voice files: 2 Files will be downloaded - an .onnx file (~65MB) & a .json file.
For more details please see: https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/API_PYTHON.md

   ```bash
   python3 -m piper.download_voices en_US-amy-low
   ```

In case differen voice selected, please modify:
   ```bash
   In file: ~/hailo-apps-infra/hailo_apps/python/api_apps/voice_asistant/processing.py
   self.piper_voice = PiperVoice.load(TTS_ONNX_PATH)
   ```

## Microphone quality

**High-quality microphone input is crucial for optimal speech recognition performance.** Poor audio quality, background noise, or incorrect microphone configuration can significantly impact transcription accuracy. Before using the voice assistant, ensure your microphone is properly configured and functioning.

### Troubleshooting Microphone on Raspberry Pi

Testing your microphone is essential, particularly on Raspberry Pi systems. If your microphone is not recording, follow these steps to configure the audio profile:

**Common Fix for USB Headsets:**

1. Connect your USB microphone to the Raspberry Pi
2. Locate the **Volume Control** icon on the upper Task Bar (system tray)
3. Right-click the Volume Control icon
4. Select **"Device Profiles"** from the menu
5. Choose the **"Pro Audio"** profile for your USB device

**Why "Pro Audio"?**  
The Pro Audio profile provides direct, low-level access to your audio device's capabilities, bypassing potential compatibility issues with the audio server (PipeWire or PulseAudio). This often resolves recording problems with USB headsets on Raspberry Pi OS.

After applying this profile, verify your microphone is working using the testing commands below.

### Testing Microphone

**1. List available audio devices:**
```bash
arecord -l
```

**2. Test microphone recording:**
```bash
# Record 5 seconds of audio
arecord -d 5 -f cd -t wav test.wav

# Play back the recording
aplay test.wav
```

**3. Adjust microphone volume (if needed):**
```bash
# Open audio mixer
alsamixer

# Press F4 to select capture devices
# Use arrow keys to adjust microphone gain
# Press Esc to exit
```

**4. Set default microphone (if multiple devices exist):**
```bash
# Create or edit ~/.asoundrc
nano ~/.asoundrc

# Add the following (replace X with your card number from arecord -l):
pcm.!default {
    type asoundrc
    card X
}

ctl.!default {
    type asoundrc
    card X
}
```

**Tips for best results:**
- Use a USB microphone for better quality than built-in mics
- Position microphone 15-30cm from your mouth
- Minimize background noise during recording
- Speak clearly at a normal volume
- Test in the same environment where you will use the assistant

## Features

- **Real-time speech processing** with Hailo AI acceleration
- **Interactive voice mode** - press Space to start/stop recording
- **Streaming text-to-speech** - responsive audio playback with interruption support
- **Context management** - maintains conversation history with clear option
- **Debug mode** - saves recorded audio for analysis
- **Low-resource mode** - optional TTS disable for reduced system load

## Requirements

- Hailo AI processor and SDK
- Python 3.8+
- PyAudio
- NumPy
- Piper TTS (for voice synthesis)
- Hailo Platform libraries

## Files

- `main.py` - Main application with terminal-based voice interface
- `processing.py` - AI pipeline with S2T, LLM, and TTS integration
- `recorder.py` - Audio recording and processing module

## Usage

1. Run the application:
   ```bash
   python main.py
   ```

2. Optional flags:
   ```bash
   python main.py --debug      # Enable audio file saving
   python main.py --no-tts     # Disable text-to-speech
   ```

3. **Interactive controls**:
   - Press `Space` to start/stop recording
   - Press `Q` to quit the application
   - Press `C` to clear conversation context
   - Speak naturally during recording

## How it works

The application uses a threaded architecture to handle:
- Real-time audio capture and processing
- Hailo Speech-to-Text transcription
- Large Language Model inference for responses
- Streaming text-to-speech synthesis with interruption support
- Non-blocking user input handling

The voice assistant can engage in natural conversations, answer questions, and provide assistance while maintaining context
