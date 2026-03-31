# Toolset: HailoRT API Reference

> API reference for the Hailo Platform SDK (HailoRT) used in hailo-apps applications.

## hailo_platform

### VDevice (Virtual Device)

```python
from hailo_platform import VDevice

# Create with shared group (ALWAYS use this pattern)
params = VDevice.create_params()
params.group_id = "SHARED"  # Use SHARED_VDEVICE_GROUP_ID constant
vdevice = VDevice(params)

# Release when done
vdevice.release()
```

**Key points**:
- `group_id` enables multiple processes to share the same physical device
- Always release VDevice on shutdown
- Create params first, set group_id, then instantiate

### VDevice.create_params()
Returns a `VDeviceParams` object with configurable fields:
- `group_id: str` — Shared device group identifier

---

## hailo_platform.genai

### VLM (Vision-Language Model)

```python
from hailo_platform.genai import VLM

vlm = VLM(vdevice, hef_path)

# Generate response for image + prompt
prompt = [
    {"role": "system", "content": [{"type": "text", "text": "System prompt here"}]},
    {"role": "user", "content": [
        {"type": "image"},
        {"type": "text", "text": "User question here"}
    ]}
]

# Streaming generation (context manager)
with vlm.generate(
    prompt=prompt,
    frames=[rgb_numpy_image],     # List of RGB numpy arrays (336x336)
    temperature=0.1,              # Sampling temperature (0.0-1.0)
    seed=42,                      # Random seed for reproducibility
    max_generated_tokens=200      # Max output tokens
) as generation:
    response = ""
    for chunk in generation:
        if chunk != '<|im_end|>':
            response += chunk

# Clear context between conversations
vlm.clear_context()

# Release resources
vlm.release()
```

**Prompt format**: List of message dicts with roles (`system`, `user`, `assistant`).
Each message has `content` list with typed entries:
- `{"type": "text", "text": "..."}` — Text content
- `{"type": "image"}` — Image placeholder (matched to `frames` list)

**Image requirements**:
- RGB format (not BGR)
- Typically 336×336 pixels
- `np.uint8` dtype

### LLM (Large Language Model)

```python
from hailo_platform.genai import LLM

llm = LLM(vdevice, hef_path)

# Simple generation
response = llm.generate_all(prompt_string)

# Streaming generation
with llm.generate(prompt=prompt, temperature=0.7, max_generated_tokens=500) as gen:
    for token in gen:
        print(token, end="", flush=True)

llm.clear_context()
llm.release()
```

### Speech2Text (Whisper)

```python
from hailo_platform.genai import Speech2Text

stt = Speech2Text(vdevice, whisper_hef_path)

# Transcribe audio
segments = stt.generate_all_segments(audio_data)
# audio_data: numpy array of audio samples

stt.release()
```

---

## hailo (GStreamer Buffer API)

Used in GStreamer pipeline callbacks:

```python
import hailo

# Get Region of Interest from GStreamer buffer
roi = hailo.get_roi_from_buffer(buffer)

# Get detections
detections = roi.get_objects_typed(hailo.HAILO_DETECTION)
for det in detections:
    label = det.get_label()           # str: "person", "dog", etc.
    confidence = det.get_confidence() # float: 0.0-1.0
    bbox = det.get_bbox()             # HailoBBox object
    x = bbox.xmin()
    y = bbox.ymin()
    w = bbox.width()
    h = bbox.height()

# Get classifications
classifications = roi.get_objects_typed(hailo.HAILO_CLASSIFICATION)

# Get landmarks (pose estimation)
landmarks = det.get_objects_typed(hailo.HAILO_LANDMARKS)
```

---

## Constants Reference

```python
from hailo_apps.python.core.common.defines import (
    # Architectures
    HAILO8_ARCH,          # "hailo8"
    HAILO8L_ARCH,         # "hailo8l"
    HAILO10H_ARCH,        # "hailo10h"

    # Device sharing
    SHARED_VDEVICE_GROUP_ID,  # "SHARED"

    # Resource paths
    RESOURCES_ROOT_PATH_DEFAULT,  # "/usr/local/hailo/resources"
    RESOURCES_MODELS_DIR_NAME,    # "models"
    REPO_ROOT,                    # Path to repository root

    # Gen AI app names
    VLM_CHAT_APP,         # "vlm_chat"
    LLM_CHAT_APP,         # "llm_chat"
    WHISPER_CHAT_APP,     # "whisper_chat"
    AGENT_APP,            # "agent"
    VOICE_ASSISTANT_APP,  # "voice_assistant"

    # Default model names
    VLM_MODEL_NAME_H10,      # "Qwen2-VL-2B-Instruct"
    LLM_MODEL_NAME_H10,      # "Qwen2.5-1.5B-Instruct"
    WHISPER_MODEL_NAME_H10,  # "Whisper-Base"

    # Camera constants
    USB_CAMERA,    # "usb"
    RPI_NAME_I,    # "rpi"
)
```

