# System Architecture

> Deep dive into hailo-apps architecture for AI agents building applications.

## Three-Tier App Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      User Applications                       │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────┐  │
│  │ Pipeline Apps│  │Standalone Apps│  │   Gen AI Apps      │  │
│  │ (GStreamer)  │  │ (HailoInfer) │  │ (VLM/LLM/Whisper) │  │
│  └──────┬──────┘  └──────┬───────┘  └────────┬───────────┘  │
│         │                │                    │              │
│  ┌──────┴────────────────┴────────────────────┴───────────┐  │
│  │              Core Framework Layer                       │  │
│  │  GStreamerApp │ HailoInfer │ Parsers │ Logger │ Config  │  │
│  └──────┬────────────────┬────────────────────┬───────────┘  │
│         │                │                    │              │
│  ┌──────┴────────────────┴────────────────────┴───────────┐  │
│  │              Hailo Platform SDK                         │  │
│  │   HailoRT  │  TAPPAS  │  GStreamer Plugins │  genai    │  │
│  └────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## App Archetypes

### 1. Pipeline Apps (GStreamer-based)

**When to use**: Real-time video processing with hardware-accelerated inference pipelines.

**Structure**:
```
pipeline_apps/{app_name}/
├── {app_name}.py          # Subclasses GStreamerApp, overrides get_pipeline_string()
├── README.md              # Usage documentation
└── requirements.txt       # Optional extra dependencies
```

**Key classes**:
- `GStreamerApp` — Base class that manages GStreamer lifecycle
- `app_callback_class` — User data object passed to frame callbacks
- Helper functions in `gstreamer_helper_pipelines.py` compose pipeline strings

**Data flow**: Camera → GStreamer → hailonet (inference) → hailofilter (postprocess) → Python callback → display

### 2. Standalone Apps (HailoInfer-based)

**When to use**: Direct inference without GStreamer, custom pre/post-processing, single-image analysis.

**Structure**:
```
standalone_apps/{app_name}/
├── {app_name}.py           # Uses HailoInfer for async inference
├── {app_name}_post_process.py  # Custom postprocessing
├── config.json             # Model-specific configuration
├── README.md
└── requirements.txt
```

**Key classes**:
- `HailoInfer` — Async inference wrapper around `hailo_platform`
- Uses `cv2.VideoCapture` for camera, `cv2.imshow` for display

**Data flow**: Camera (OpenCV) → preprocess → HailoInfer.run_async() → postprocess → display (OpenCV)

### 3. Gen AI Apps (Hailo-10H)

**When to use**: Generative AI — VLM image understanding, LLM chat, speech-to-text, voice assistants, agents.

**Structure**:
```
gen_ai_apps/{app_name}/
├── {app_name}.py          # Main app with camera loop + inference
├── backend.py             # VLM/LLM inference in separate process
├── system_prompt.py       # System prompt configuration (optional)
├── README.md
└── requirements.txt
```

**Key classes**:
- `VLM` from `hailo_platform.genai` — Vision-Language Model
- `LLM` from `hailo_platform.genai` — Large Language Model  
- `Speech2Text` from `hailo_platform.genai` — Whisper STT
- `Backend` — Multiprocessing wrapper for non-blocking inference

**Data flow**: Camera (OpenCV) → capture frame → VLM.generate(prompt, frame) → stream tokens → display

## Module Dependency Graph

```
hailo_apps/
├── config/
│   ├── config_manager.py      # ConfigPaths, model registry, resource resolution
│   ├── resources_config.yaml  # Per-app model definitions
│   └── config.yaml            # Global settings
│
├── python/core/
│   ├── common/
│   │   ├── defines.py         # ALL constants: app names, paths, model names
│   │   ├── core.py            # resolve_hef_path(), parsers, resource helpers  
│   │   ├── parser.py          # CLI argument parsers (base, pipeline, standalone)
│   │   ├── hailo_logger.py    # get_logger(), init_logging()
│   │   ├── hailo_inference.py # HailoInfer class for standalone apps
│   │   ├── hef_utils.py       # HEF file inspection utilities
│   │   ├── camera_utils.py    # USB/RPI camera discovery
│   │   ├── buffer_utils.py    # GStreamer buffer → numpy conversion
│   │   └── installation_utils.py  # detect_hailo_arch()
│   │
│   └── gstreamer/
│       ├── gstreamer_app.py            # GStreamerApp base class
│       └── gstreamer_helper_pipelines.py  # Pipeline string factory
│
├── python/gen_ai_apps/
│   ├── gen_ai_utils/
│   │   ├── llm_utils/        # Streaming, tool parsing, context management
│   │   └── voice_processing/ # Audio I/O, VAD, STT, TTS
│   ├── vlm_chat/             # Interactive VLM chat (reference implementation)
│   ├── voice_assistant/      # Full voice assistant pipeline
│   └── agent_tools_example/  # Agent with YAML-configured tools
│
└── python/standalone_apps/   # Direct inference apps (no GStreamer)
```

## Multiprocessing Architecture (Gen AI)

Gen AI apps use **multiprocessing** to keep the UI responsive while inference runs:

```
┌──────────────────┐     mp.Queue      ┌──────────────────┐
│   Main Process   │ ───────────────→  │  Worker Process   │
│                  │                    │                   │
│  - Camera loop   │  request_queue     │  - VDevice init   │
│  - OpenCV display│                    │  - VLM/LLM init   │
│  - User input    │ ←───────────────   │  - Inference loop │
│  - State machine │  response_queue    │  - Token streaming│
└──────────────────┘                    └──────────────────┘
```

**Why**: Hailo inference blocks for hundreds of milliseconds; a separate process ensures the camera feed stays smooth.

## Configuration System

### Resource Resolution Chain

1. **User provides `--hef-path`** → use directly
2. **No path provided** → look up default model in `resources_config.yaml`
3. **Model not on disk** → auto-download from Model Zoo or S3
4. **Store at** `/usr/local/hailo/resources/models/{arch}/{model_name}.hef`

### Config Manager API

```python
from hailo_apps.config.config_manager import (
    get_available_apps,
    get_default_model_name,
    get_model_info,
    get_supported_architectures,
)
```

## Hardware Architecture Support

| Architecture | Constant | Apps Supported |
|---|---|---|
| Hailo-8 | `HAILO8_ARCH = "hailo8"` | Pipeline, Standalone |
| Hailo-8L | `HAILO8L_ARCH = "hailo8l"` | Pipeline, Standalone |
| Hailo-10H | `HAILO10H_ARCH = "hailo10h"` | Pipeline, Standalone, **Gen AI** |

Gen AI apps (VLM, LLM, Whisper) are **Hailo-10H only**. Always check or assert architecture.
