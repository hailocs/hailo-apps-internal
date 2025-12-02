# Hailo OLLAMA

The Hailo Model Zoo GenAI is a curated collection of pre-trained models and example applications optimized for Hailo's AI processors, designed to accelerate GenAI application development. It includes Hailo-Ollama, an Ollama-compatible API written in C++ on top of HailoRT, enabling seamless integration with various external tools and frameworks.

Ollama simplifies running large language models locally by managing model downloads, deployments, and interactions through a convenient REST API.

Models are specifically optimized for Hailo hardware, providing efficient, high-performance inference tailored for GenAI tasks. For full details: https://github.com/hailo-ai/hailo_model_zoo_genai?tab=readme-ov-file#basic-usage


#### Installation and Setup

12. **Download and Install Hailo GenAI Model Zoo:**
   - Visit: https://hailo.ai/developer-zone/
   - Download the appropriate package for your architecture
   - Install the package:
     ```bash
     sudo apt install hailo_gen_ai_model_zoo_<ver>_<arch>.deb
     ```

2. **Start Hailo-Ollama Service:**
   ```bash
   # In a new terminal window
   hailo-ollama
   ```

3. **Pull a Model:**
   ```bash
   # In another terminal window
   curl --silent http://localhost:8000/api/pull \
        -H 'Content-Type: application/json' \
        -d '{ "model": "qwen2.5-instruct:1.5b", "stream" : true }'
   ```

   The models will be downloaded to: `~/usr/share/hailo-ollama/models/blob/`

4. **Test the Model:**
   ```bash
   # Test the model via API
   curl --silent http://localhost:8000/api/chat \
        -H 'Content-Type: application/json' \
        -d '{"model": "qwen2.5-instruct:1.5b", "messages": [{"role": "user", "content": "Translate to French: The cat is on the table."}]}'
   ```