# Hailo GenAI Chat Examples

This directory contains three basic example applications demonstrating the use of Hailo's GenAI platform for different AI tasks:
- Large Language Models (LLM)
- Vision Language Models (VLM)
- Speech-to-Text (Whisper)

For full GenAI applications, please see: [VLM full application](../vlm_chat) and [Whisper full application](../voice_asistant/).

## Files Overview

- Open WebUI example with Hailo Ollama API
- `llm_chat.py` - Text-based conversational AI using Large Language Models
- `vlm_chat.py` - Image analysis and description using Vision Language Models
- `whisper_chat.py` - Audio transcription using Whisper speech-to-text models

## Usage

### LLM Chat (`llm_chat.py`)
Demonstrates text-based conversation with an AI assistant.

```bash
python llm_chat.py
```

**Features:**
- Simple text prompt processing
- Configurable temperature and token limits
- System message for assistant behavior definition

### VLM Chat (`vlm_chat.py`)
Analyzes and describes images using vision-language models.

```bash
python vlm_chat.py
```

**Features:**
- Image loading and preprocessing
- Visual question answering
- Image description generation

### Whisper Chat (`whisper_chat.py`)
Transcribes audio files to text using Whisper models.

```bash
python whisper_chat.py
```

**Features:**
- Audio file loading and processing
- Speech-to-text transcription
- Segment-based output

## Prerequisites

### Hardware Requirements
- Hailo AI accelerator device (H10 or compatible)

### Software Requirements
- Python 3.8+
- Hailo Platform SDK
- Required Python packages:
  ```bash
  pip install opencv-python open-webui
  ```

### Model Requirements
All examples use models that should be available in your Hailo resources directory:
- LLM/VLM: Uses `VLM_MODEL_NAME_H10` model
- Whisper: Uses `WHISPER_MODEL_NAME_H10` model
- Open WebUI: Uses models from Hailo GenAI Model Zoo

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