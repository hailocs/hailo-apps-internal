# Gen AI Application Development Guide

> How to build Hailo-10H generative AI applications: VLM, LLM, Whisper, and hybrid apps.

## Available Gen AI Models

| Model | Class | Use Case | Import |
|---|---|---|---|
| Qwen2-VL-2B-Instruct | `VLM` | Image understanding, visual Q&A | `from hailo_platform.genai import VLM` |
| Qwen2.5-1.5B-Instruct | `LLM` | Text generation, chat, tool calling | `from hailo_platform.genai import LLM` |
| Whisper-Base | `Speech2Text` | Audio transcription | `from hailo_platform.genai import Speech2Text` |

## VLM Application Pattern

### Minimal VLM Inference

```python
from hailo_platform import VDevice
from hailo_platform.genai import VLM
from hailo_apps.python.core.common.defines import SHARED_VDEVICE_GROUP_ID

# Create device
params = VDevice.create_params()
params.group_id = SHARED_VDEVICE_GROUP_ID
vdevice = VDevice(params)

# Load model
vlm = VLM(vdevice, "path/to/model.hef")

# Build prompt
prompt = [
    {"role": "system", "content": [{"type": "text", "text": "You are a helpful assistant."}]},
    {"role": "user", "content": [
        {"type": "image"},
        {"type": "text", "text": "What do you see in this image?"}
    ]}
]

# Run inference (image must be RGB numpy array, typically 336×336)
with vlm.generate(prompt=prompt, frames=[image], temperature=0.1, seed=42, max_generated_tokens=200) as generation:
    response = ""
    for chunk in generation:
        if chunk != '<|im_end|>':
            response += chunk

vlm.clear_context()
```

### Image Preprocessing

VLM expects **RGB images at 336×336** with central crop:

```python
import cv2
import numpy as np

def convert_resize_image(image_array: np.ndarray, target_size=(336, 336)) -> np.ndarray:
    """Convert BGR→RGB and central-crop to target size."""
    image_array = cv2.cvtColor(image_array, cv2.COLOR_BGR2RGB)
    h, w = image_array.shape[:2]
    target_w, target_h = target_size
    scale = max(target_w / w, target_h / h)
    new_w, new_h = int(w * scale), int(h * scale)
    resized = cv2.resize(image_array, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    x_start = (new_w - target_w) // 2
    y_start = (new_h - target_h) // 2
    return resized[y_start:y_start+target_h, x_start:x_start+target_w].astype(np.uint8)
```

## Multiprocessing Backend Pattern

For responsive apps, run inference in a **separate process**:

```python
import multiprocessing as mp

def worker_process(request_queue, response_queue, hef_path, **kwargs):
    """Worker process: init model once, loop on requests."""
    params = VDevice.create_params()
    params.group_id = SHARED_VDEVICE_GROUP_ID
    vdevice = VDevice(params)
    vlm = VLM(vdevice, hef_path)

    while True:
        item = request_queue.get()
        if item is None:  # Sentinel to stop
            break
        result = do_inference(vlm, item)
        response_queue.put(result)

    vlm.release()
    vdevice.release()


class Backend:
    def __init__(self, hef_path, **kwargs):
        self._request_queue = mp.Queue(maxsize=10)
        self._response_queue = mp.Queue(maxsize=10)
        self._process = mp.Process(target=worker_process, args=(...))
        self._process.start()

    def inference(self, image, prompt, timeout=30):
        self._request_queue.put({"image": image, "prompt": prompt})
        return self._response_queue.get(timeout=timeout)

    def close(self):
        self._request_queue.put(None)  # Sentinel
        self._process.join(timeout=2)
```

## LLM Application Pattern

```python
from hailo_platform.genai import LLM

llm = LLM(vdevice, hef_path)

# Single-turn
response = llm.generate_all(prompt)

# Streaming with tool-calling
from hailo_apps.python.gen_ai_apps.gen_ai_utils.llm_utils import streaming, tool_parsing
```

## Camera Integration for Gen AI Apps

```python
from hailo_apps.python.core.common.camera_utils import get_usb_video_devices
from hailo_apps.python.core.gstreamer.gstreamer_helper_pipelines import get_source_type

# USB camera
devices = get_usb_video_devices()
cap = cv2.VideoCapture(devices[0])
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

# RPi camera
from picamera2 import Picamera2
picam2 = Picamera2()
config = picam2.create_preview_configuration(main={"size": (640, 480), "format": "RGB888"})
picam2.configure(config)
picam2.start()
```

## Voice Integration

```python
from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.speech_to_text import SpeechToText
from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.text_to_speech import TextToSpeech
from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.audio_recorder import AudioRecorder
from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.vad import VAD
```

## Common Gotchas

1. **Always clear VLM context** after each inference: `vlm.clear_context()`
2. **Image format**: VLM expects RGB, OpenCV gives BGR — convert with `cv2.cvtColor`
3. **Process cleanup**: Always send `None` sentinel to worker process on shutdown
4. **Queue deadlocks**: Use `maxsize` on queues and `timeout` on `.get()`
5. **Token filtering**: Filter out `<|im_end|>` tokens from VLM output
6. **Environment**: Set `QT_QPA_PLATFORM=xcb` before importing OpenCV

