# Hailo GenAI Chat Examples

This directory contains three basic example applications demonstrating the use of Hailo's GenAI platform for different AI tasks:
- Large Language Models (LLM)
- Vision Language Models (VLM)
- Speech-to-Text (Whisper)

For full GenAI applications, please see: [VLM full application](../vlm_chat) and [Whisper full application](../voice_assistant/).

## Files Overview

- Open WebUI example with Hailo Ollama API
- `llm_chat.py` - Text-based conversational AI using Large Language Models
- `vlm_chat.py` - Image analysis and description using Vision Language Models
- `whisper_chat.py` - Audio transcription using Whisper speech-to-text models

## Usage

### LLM Chat (`llm_chat.py`)
Demonstrates text-based conversation with an AI assistant.

```bash
python -m hailo_apps.python.gen_ai_apps.examples.llm_chat
```

**Features:**
- Simple text prompt processing
- Configurable temperature and token limits
- System message for assistant behavior definition
- Auto-downloads model on first run

### VLM Chat (`vlm_chat.py`)
Analyzes and describes images using vision-language models.

```bash
python -m hailo_apps.python.gen_ai_apps.examples.vlm_chat
```

**Features:**
- Image loading and preprocessing
- Visual question answering
- Image description generation
- Uses example image from doc/images/ directory
- Auto-downloads model on first run

### Whisper Chat (`whisper_chat.py`)
Transcribes audio files to text using Whisper models.

```bash
python -m hailo_apps.python.gen_ai_apps.examples.whisper_chat --audio audio.wav
```

**Features:**
- Audio file loading and processing
- Speech-to-text transcription
- Segment-based output
- Default audio file: `audio.wav` (in examples directory)
- Auto-downloads model on first run

## Prerequisites

### Hardware Requirements
- Hailo AI accelerator device (H10 or compatible)

### Software Requirements
- Python 3.10+
- Hailo Platform SDK
- Required Python packages (installed with main package):
  - OpenCV (opencv-python)
  - NumPy

### Model Requirements
All examples use models that are automatically downloaded on first run:
- **LLM**: Uses `LLM_MODEL_NAME_H10` model (auto-downloaded)
- **VLM**: Uses `VLM_MODEL_NAME_H10` model (auto-downloaded)
- **Whisper**: Uses `WHISPER_MODEL_NAME_H10` model (auto-downloaded)
- **Open WebUI**: Uses models from Hailo GenAI Model Zoo

**Note:** Models are downloaded automatically when you run each example for the first time. No manual download required.

## Troubleshooting

### Open WebUI Issues
- **Service not starting:** Ensure hailo-ollama is running first
- **Model not found:** Verify the model was pulled successfully using the curl command
- **Connection issues:** Check that the API URL in Open WebUI settings matches the hailo-ollama service URL
- **Port conflicts:** Default ports are 8000 (hailo-ollama) and 8080 (open-webui)

### Common Issues for Other Examples
1. **Model not found error**
   - Ensure Hailo models are properly installed
   - Check model paths in the resource directory

2. **Device initialization failed**
   - Verify Hailo device is connected and recognized
   - Check device permissions

3. **File not found errors**
   - Verify required files exist at specified paths
   - Update file paths if using different locations

## License

These examples are part of the Hailo Apps Infrastructure and follow the project's