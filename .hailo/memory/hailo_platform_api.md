# Hailo Platform API — Memory

## VDevice Creation (ALWAYS use this pattern)

```python
from hailo_platform import VDevice
from hailo_apps.python.core.common.defines import SHARED_VDEVICE_GROUP_ID

params = VDevice.create_params()
params.group_id = SHARED_VDEVICE_GROUP_ID  # "SHARED"
vdevice = VDevice(params)
```

**Why group_id**: Enables multi-process device sharing. Without it, only one process can use the Hailo chip.

**Cleanup**: Always `vdevice.release()` on shutdown. In worker processes, release in a `finally` block.

## HEF Path Resolution (ALWAYS use resolve_hef_path)

```python
from hailo_apps.python.core.common.core import resolve_hef_path

hef_path = resolve_hef_path(
    user_path,          # From --hef-path CLI (may be None)
    app_name="my_app",  # Registered in defines.py
    arch="hailo10h"     # Or detect_hailo_arch()
)
```

**Resolution chain**: User path → default model lookup → resource directory → auto-download.

**Never hardcode**: `/usr/local/hailo/resources/models/hailo10h/model.hef` ← WRONG

## Model Classes (hailo_platform.genai)

| Class | Constructor | Key Methods |
|---|---|---|
| `VLM` | `VLM(vdevice, hef_path)` | `.generate(prompt, frames, ...)`, `.clear_context()`, `.release()` |
| `LLM` | `LLM(vdevice, hef_path)` | `.generate(prompt, ...)`, `.generate_all(prompt)`, `.clear_context()`, `.release()` |
| `Speech2Text` | `Speech2Text(vdevice, hef_path)` | `.generate_all_segments(audio)`, `.release()` |

## VLM.generate() — Context Manager Pattern

```python
with vlm.generate(
    prompt=prompt_list,              # List of message dicts
    frames=[rgb_numpy_array],        # List of RGB images (336x336)
    temperature=0.1,                 # 0.0-1.0
    seed=42,                         # Reproducibility
    max_generated_tokens=200         # Max output length
) as generation:
    for chunk in generation:         # Streaming tokens
        if chunk != '<|im_end|>':
            response += chunk

vlm.clear_context()                  # MUST clear after each inference
```

## HailoInfer (Standalone Inference)

```python
from hailo_apps.python.core.common.hailo_inference import HailoInfer

infer = HailoInfer(hef_path)
shape = infer.get_input_shape()      # (H, W, C)
output = infer.run(preprocessed_array)
future = infer.run_async(preprocessed_array)
result = future.get()
```

## Architecture Detection

```python
from hailo_apps.python.core.common.installation_utils import detect_hailo_arch
arch = detect_hailo_arch()  # "hailo8", "hailo8l", or "hailo10h"
```

## Constants Registry

All app names, model names, paths registered in `hailo_apps/python/core/common/defines.py`.

New apps MUST add:
```python
MY_APP = "my_app"
MY_APP_TITLE = "My App"
```

## Config Manager

```python
from hailo_apps.config.config_manager import (
    get_available_apps,
    get_default_model_name,
    get_model_info,
    get_supported_architectures,
)
```

Uses `@lru_cache(maxsize=8)` on YAML loading — no performance concern for repeated calls.

## Discovered Patterns

### VDevice Release Order
When using both VLM and VDevice in same process:
```python
vlm.release()      # Release model first
vdevice.release()  # Then release device
```
Reversing this order can cause segfaults.

### HEF Model Versions
Different HailoRT versions may require different HEF compilations. Model Zoo versions are pinned per architecture in `config.yaml`:
- H8 → Model Zoo v2.17.0
- H10 → Model Zoo v5.1.0 / v5.2.0
