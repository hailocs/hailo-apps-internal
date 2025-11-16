# Open WebUI
Open WebUI is an extensible, feature-rich, and user-friendly self-hosted AI platform designed to operate entirely offline: https://github.com/open-webui/open-webui.

Once hailo-ollama is up and running (please refer to [Ollama Readme](Ollama.md)) - it's possible to consume it with the popular Open WebUI.

### Prerequisites - Docker

Please foolow up here: https://docs.docker.com/engine/

## Installation

Based on this guide: https://docs.openwebui.com/getting-started/quick-start

- Download and run the **slim** variant
- **Important:** Run with host network

```bash
docker pull ghcr.io/open-webui/open-webui:main-slim

# Run with host network (container shares host's network)
docker run -d --network host \
  -v open-webui:/app/backend/data \
  --name open-webui \
  ghcr.io/open-webui/open-webui:main-slim
```

### Configure Open WebUI

1. Open your browser and navigate to the Open WebUI interface at: **http://localhost:8080**

2. In **Settings → Admin Settings → Connections**, add the Hailo-Ollama API URL: 
   ```
   http://localhost:8000
   ```

3. Under the "Ollama API" section:
   - Set "Connection Type" to "Local"
   - Set "Auth" to "None"

Now in the chat, select one of the models served by Hailo-Ollama from the available models.