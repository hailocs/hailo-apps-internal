# Hailo Voice Assistant Interactive Application

An interactive voice-controlled AI assistant using Hailo's Speech-to-Text and Large Language Model for real-time audio processing and conversational AI.

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
