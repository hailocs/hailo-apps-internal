# Hailo GenAI Chat Examples

This directory contains three basic example applications demonstrating the use of Hailo's GenAI platform for different AI tasks: 
- Large Language Models (LLM)
- Vision Language Models (VLM)
- Speech-to-Text (Whisper)

For full GenAI applications, please see: [VLM full application](../VLM_Chat) and [Whisper full application](../Voice_Asistant/).

## Files Overview

- Open WebUI example with Hailo Ollama API
- `llm_chat.py` - Text-based conversational AI using Large Language Models
- `vlm_chat.py` - Image analysis and description using Vision Language Models  
- `whisper_chat.py` - Audio transcription using Whisper speech-to-text models

## Usage

### Open WebUI

Open WebUI is an extensible, feature-rich, and user-friendly self-hosted AI platform designed to operate entirely offline: `https://github.com/open-webui/open-webui`

The Hailo Model Zoo GenAI is a curated collection of pre-trained models and example applications optimized for Hailo's AI processors, designed to accelerate GenAI application development. It includes Hailo-Ollama, an Ollama-compatible API written in C++ on top of HailoRT, enabling seamless integration with various external tools and frameworks.

Ollama simplifies running large language models locally by managing model downloads, deployments, and interactions through a convenient REST API.

Models are specifically optimized for Hailo hardware, providing efficient, high-performance inference tailored for GenAI tasks: `https://github.com/hailo-ai/hailo_model_zoo_genai`


#### Installation and Setup

1. **Install Open WebUI:**
   ```bash
   pip install open-webui
   ```

2. **Download and Install Hailo GenAI Model Zoo:**
   - Visit: https://hailo.ai/developer-zone/
   - Download the appropriate package for your architecture
   - Install the package:
     ```bash
     sudo dpkg -i hailo_gen_ai_model_zoo_<ver>_<arch>.deb
     ```

3. **Start Hailo-Ollama Service:**
   ```bash
   # In a new terminal window
   hailo-ollama
   ```

4. **Pull a Model:**
   ```bash
   # In another terminal window
   curl --silent http://localhost:8000/api/pull \
        -H 'Content-Type: application/json' \
        -d '{ "model": "qwen2:1.5b", "stream" : true }'
   ```

   The models will be downloaded to: `~/usr/share/hailo-ollama/models/blob/`

5. **Test the Model:**
   ```bash
   # Test the model via API
   curl --silent http://localhost:8000/api/chat \
        -H 'Content-Type: application/json' \
        -d '{"model": "qwen2:1.5b", "messages": [{"role": "user", "content": "Translate to French: The cat is on the table."}]}'
   ```

6. **Start Open WebUI:**
   ```bash
   # In a new terminal window
   open-webui serve
   ```

7. **Configure Open WebUI:**
   - Open your browser and navigate to the Open WebUI interface http://localhost:8080
   - In the settings->admin Settings->Connections add the Hailo-Ollama API URL: http://localhost:8000 under "Ollama API" section, select "Connection Type" to "Local" and select "Auth" to "None".
   - Select the `qwen2:1.5b` model from the available models

#### Features
- Web-based chat interface
- Multiple model support
- Conversation history
- Real-time streaming responses
- Integration with Hailo AI accelerators

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