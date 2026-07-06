# Hailo Ollama

## What This App Does
Integration guide (not a Python application) for using Hailo-Ollama with Open WebUI to create a web-based AI chat interface. Hailo-Ollama is an Ollama-compatible C++ REST API built on HailoRT that exposes Hailo-accelerated LLM models via a standard Ollama API on `http://localhost:8000`. Combined with Open WebUI (via Docker), it provides a full-featured chat interface accessible through a web browser at `http://localhost:8080`.

## Architecture
- **Type:** GenAI integration guide (Hailo-10H only)
- **Models:** Ollama-compatible models (e.g., qwen2.5-instruct:1.5b) pulled via API
- **SDK:** Hailo GenAI Model Zoo (`hailo_gen_ai_model_zoo` deb package)
- **Dependencies:** Docker (for Open WebUI), Hailo GenAI Model Zoo deb package (v5.1.1 or v5.2.0)

## Key Files
| File | Purpose |
|------|---------|
| `README.md` | Complete setup guide for Hailo-Ollama service and Open WebUI Docker integration |

## How It Works
1. Install Hailo GenAI Model Zoo deb package from Hailo Developer Zone
2. Start `hailo-ollama` service (listens on port 8000)
3. Pull a model via REST API: `curl http://localhost:8000/api/pull -d '{"model": "qwen2.5-instruct:1.5b"}'`
4. Test model via chat API: `curl http://localhost:8000/api/chat -d '{"model": "...", "messages": [...]}'`
5. Optionally deploy Open WebUI Docker container with host networking pointing to localhost:8000
6. Access web chat interface at http://localhost:8080

## Common Use Cases
- Web-based chat interface for Hailo-accelerated LLMs
- Integration with any tool that supports the Ollama API format
- Serving LLM models over REST API for multi-client access
- Replacing cloud-based chat with local edge AI

## How to Extend
- Pull different models: use the `/api/pull` endpoint with different model names
- Custom web UI: replace Open WebUI with any Ollama-compatible frontend
- API integration: use the REST API directly from custom applications
- Multi-model serving: pull and switch between multiple models

## Related Apps
| App | When to use instead |
|-----|-------------------|
| `simple_llm_chat` | Need a quick Python-based LLM test without REST API |
| `voice_assistant` | Need voice interaction rather than web chat |
| `agent_tools_example` | Need function calling capabilities with LLM |
| `vlm_chat` | Need vision + language model for image analysis |
