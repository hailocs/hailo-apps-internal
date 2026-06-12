# Voice-Controlled Smart Camera

A hands-free smart camera application that responds to voice commands to detect and describe objects in real time. Built on Hailo-10H, it combines speech-to-text (Whisper), a language model (Qwen LLM) for intent parsing and chat, a vision-language model (Qwen2-VL) for scene analysis, and text-to-speech (Piper TTS) for audio responses.

## Prerequisites

- **Hardware:** Hailo-10H accelerator
- **Models:** Whisper-Base (STT), Qwen2.5-1.5B-Instruct (LLM), Qwen2-VL-2B-Instruct (VLM)
- **Input:** USB camera + microphone
- **Dependencies:** `pip install -e ".[gen-ai]"` (piper-tts, sounddevice, opencv-python)

## How to Run

```bash
# With USB camera (default)
python community/apps/gen_ai_apps/voice_controlled_camera/voice_controlled_camera.py --input usb

# Without TTS (text-only responses)
python community/apps/gen_ai_apps/voice_controlled_camera/voice_controlled_camera.py --input usb --no-tts

# With VAD (voice activity detection for hands-free operation)
python community/apps/gen_ai_apps/voice_controlled_camera/voice_controlled_camera.py --input usb --vad
```

## Voice Commands

| Say this | What happens |
|----------|-------------|
| "What do you see?" | VLM describes the entire scene |
| "Describe the scene" | VLM provides a detailed scene description |
| "Detect people" | VLM identifies and counts people in frame |
| "How many cars?" | VLM counts specific objects |
| "Read that sign" | VLM reads visible text/signs |
| Anything else | LLM responds as a general chat assistant |

## Architecture

```
Microphone                    USB Camera
    |                              |
    v                              v
Whisper STT               OpenCV Capture
    |                     (background thread)
    v                              |
Intent Classifier                  |
    |                              |
    +--[visual]----> VLM Backend --+
    |                (Qwen2-VL, separate process)
    +--[chat]------> LLM
    |                (Qwen2.5-1.5B)
    v
Piper TTS --> Speaker
```

The app uses a shared VDevice for Whisper and LLM models, while the VLM runs in a separate process via the `Backend` class from `vlm_chat`. The camera runs in a background thread, continuously updating frames that are captured on demand when visual commands are issued.

## Keyboard Controls

- **Space** - Start/stop recording
- **Q** - Quit (in camera window or terminal)
- **C** - Clear LLM context
- **X** - Abort current generation

## Customization

- **Intent keywords:** Edit `DESCRIBE_KEYWORDS`, `DETECT_KEYWORDS`, `READ_KEYWORDS` in the source
- **VLM parameters:** Adjust `VLM_MAX_TOKENS`, `VLM_TEMPERATURE` constants
- **System prompt:** Modify the VLM system prompt in the `VoiceControlledCameraApp.__init__` method
- **Camera resolution:** Change `CAMERA_WIDTH`, `CAMERA_HEIGHT` constants
