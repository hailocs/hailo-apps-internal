# GenAI App Template

## Overview

GenAI apps run on Hailo-10H hardware and use the `hailo_platform.genai` SDK for large language models (LLM), vision language models (VLM), and speech-to-text (Whisper). They range from simple single-shot scripts to complex voice assistants with streaming, TTS, and tool calling.

**When to use this type:**
- LLM text generation (chat, Q&A, summarization, agents)
- VLM image analysis (visual question answering, image captioning)
- Speech-to-text transcription (Whisper)
- Voice assistants combining STT + LLM + TTS
- Any generative AI workload on Hailo-10H

**When NOT to use this type:**
- Real-time video pipeline processing (use pipeline app)
- Object detection, pose estimation, segmentation (use pipeline or standalone app)
- Any non-Hailo-10H hardware (GenAI SDK requires Hailo-10H)

## File Structure

GenAI apps live in `hailo_apps/python/gen_ai_apps/<your_app>/`:

```
your_app/
  __init__.py          # Empty, makes this a Python package
  your_app.py          # Main script
```

For complex apps, shared utilities are in `hailo_apps/python/gen_ai_apps/gen_ai_utils/`:
```
gen_ai_utils/
  llm_utils/           # Context management, streaming, tool handling, terminal UI
    streaming.py       # Token streaming with XML tag filtering
    context_manager.py # Token tracking and context window management
    tool_discovery.py  # Auto-discover callable tools
    tool_execution.py  # Execute tool calls from LLM output
    message_formatter.py  # Format prompts for different models
    terminal_ui.py     # Terminal UI with keyboard controls
  voice_processing/    # Voice interaction components
    interaction.py     # VoiceInteractionManager (keyboard controls, recording flow)
    vad.py             # Voice Activity Detection
    speech_to_text.py  # SpeechToTextProcessor (Whisper wrapper)
    text_to_speech.py  # TextToSpeechProcessor (Piper TTS wrapper)
```

## Pattern 1: Simple LLM Chat (Single-Shot)

Use this for basic LLM apps, quick tests, or as a starting point.

### Template: `simple_your_app.py`

```python
"""
[CUSTOMIZE: Brief description of what your GenAI app does.]

Usage:
    python -m hailo_apps.python.gen_ai_apps.your_app.your_app
    python -m hailo_apps.python.gen_ai_apps.your_app.your_app --hef-path custom_model
"""
import argparse
import sys

from hailo_platform import VDevice
from hailo_platform.genai import LLM

from hailo_apps.python.core.common.core import handle_list_models_flag, resolve_hef_path
from hailo_apps.python.core.common.defines import SHARED_VDEVICE_GROUP_ID, HAILO10H_ARCH
from hailo_apps.python.core.common.hailo_logger import get_logger

logger = get_logger(__name__)


def main():
    """Main function."""
    # --- Argument Parsing ---
    parser = argparse.ArgumentParser(description="[CUSTOMIZE: Your app description]")
    parser.add_argument("--hef-path", type=str, default=None, help="Path to HEF model file")
    parser.add_argument("--list-models", action="store_true", help="List available models")

    # [CUSTOMIZE: Add app-specific arguments]
    parser.add_argument("--temperature", type=float, default=0.7, help="Sampling temperature")
    parser.add_argument("--max-tokens", type=int, default=256, help="Max tokens to generate")

    # Handle --list-models before full initialization (exits early if set)
    # [CUSTOMIZE: Replace "your_app" with your app name from resources_config.yaml]
    handle_list_models_flag(parser, "your_app")

    args = parser.parse_args()

    # --- Resolve Model Path ---
    # GenAI models are Hailo-10H only. resolve_hef_path handles auto-download.
    # [CUSTOMIZE: Replace "your_app" with your app name from resources_config.yaml]
    hef_path = resolve_hef_path(args.hef_path, app_name="your_app", arch=HAILO10H_ARCH)
    if hef_path is None:
        logger.error("Failed to resolve HEF path.")
        sys.exit(1)

    logger.info(f"Using HEF: {hef_path}")

    vdevice = None
    llm = None

    try:
        # --- Initialize Hailo Device ---
        # VDevice with shared group_id allows multiple models to share the device.
        params = VDevice.create_params()
        params.group_id = SHARED_VDEVICE_GROUP_ID
        vdevice = VDevice(params)

        # --- Load LLM ---
        # The LLM class handles tokenization internally.
        # [CUSTOMIZE: For VLM, use `from hailo_platform.genai import VLM` instead]
        llm = LLM(vdevice, str(hef_path))

        # --- Construct Prompt ---
        # Prompts use the OpenAI-style message format: list of role/content dicts.
        # [CUSTOMIZE: Modify the system prompt and user message for your use case]
        prompt = [
            {
                "role": "system",
                "content": [{"type": "text", "text": "You are a helpful assistant."}]
            },
            {
                "role": "user",
                "content": [{"type": "text", "text": "[CUSTOMIZE: Your user prompt here]"}]
            }
        ]

        # --- Generate Response (Single-Shot) ---
        # generate_all() blocks until the full response is ready.
        # Parameters:
        #   temperature: 0.0 = deterministic, 1.0 = creative (default: model-dependent)
        #   seed: For reproducible output (optional)
        #   max_generated_tokens: Stop after this many tokens
        response = llm.generate_all(
            prompt=prompt,
            temperature=args.temperature,
            seed=42,
            max_generated_tokens=args.max_tokens,
        )

        # Clean up response (models sometimes append metadata)
        response = response.split("<|im_end|>")[0]
        print(response)

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        sys.exit(1)

    finally:
        # --- Resource Cleanup ---
        # IMPORTANT: Always release LLM and VDevice to free hardware resources.
        if llm:
            try:
                llm.clear_context()  # Clear the conversation context/KV cache
                llm.release()        # Release model resources
            except Exception as e:
                logger.warning(f"Error releasing LLM: {e}")
        if vdevice:
            try:
                vdevice.release()    # Release device handle
            except Exception as e:
                logger.warning(f"Error releasing VDevice: {e}")


if __name__ == "__main__":
    main()
```

## Pattern 2: Interactive LLM Chat (Multi-Turn with Streaming)

Use this for interactive chat applications with token-by-token streaming output.

### Template: `interactive_chat.py`

```python
"""
[CUSTOMIZE: Interactive chat app with streaming responses.]
"""
import argparse
import sys

from hailo_platform import VDevice
from hailo_platform.genai import LLM

from hailo_apps.python.core.common.core import resolve_hef_path
from hailo_apps.python.core.common.defines import SHARED_VDEVICE_GROUP_ID, HAILO10H_ARCH
from hailo_apps.python.core.common.hailo_logger import get_logger

logger = get_logger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Interactive LLM Chat")
    parser.add_argument("--hef-path", type=str, default=None)
    args = parser.parse_args()

    hef_path = resolve_hef_path(args.hef_path, app_name="your_app", arch=HAILO10H_ARCH)
    if hef_path is None:
        logger.error("Failed to resolve HEF path.")
        sys.exit(1)

    params = VDevice.create_params()
    params.group_id = SHARED_VDEVICE_GROUP_ID
    vdevice = VDevice(params)
    llm = LLM(vdevice, str(hef_path))

    # [CUSTOMIZE: Set your system prompt]
    system_prompt = "You are a helpful assistant."
    conversation = [
        {"role": "system", "content": [{"type": "text", "text": system_prompt}]}
    ]

    print("Chat started. Type 'quit' to exit, 'clear' to reset context.\n")

    try:
        while True:
            user_input = input("You: ").strip()
            if not user_input:
                continue
            if user_input.lower() == "quit":
                break
            if user_input.lower() == "clear":
                llm.clear_context()
                conversation = [conversation[0]]  # Keep system prompt
                print("Context cleared.\n")
                continue

            # Add user message to conversation
            conversation.append(
                {"role": "user", "content": [{"type": "text", "text": user_input}]}
            )

            # --- Streaming Generation ---
            # generate() returns a context manager that yields tokens one at a time.
            # This enables real-time display as the model generates.
            print("Assistant: ", end="", flush=True)
            full_response = ""
            with llm.generate(
                prompt=conversation,
                temperature=0.7,
                max_generated_tokens=512,
            ) as stream:
                for token in stream:
                    # [CUSTOMIZE: Process each token as it arrives]
                    # You can send tokens to TTS, filter XML tags, etc.
                    print(token, end="", flush=True)
                    full_response += token

            print("\n")

            # Add assistant response to conversation history for multi-turn context
            conversation.append(
                {"role": "assistant", "content": [{"type": "text", "text": full_response}]}
            )

    except KeyboardInterrupt:
        print("\nShutting down...")

    finally:
        llm.clear_context()
        llm.release()
        vdevice.release()


if __name__ == "__main__":
    main()
```

## Pattern 3: VLM (Vision Language Model)

Use this for apps that analyze images with an LLM.

### Template: `vlm_app.py`

```python
"""
[CUSTOMIZE: VLM app that analyzes images.]
"""
import argparse
import sys

import cv2
import numpy as np

from hailo_platform import VDevice
from hailo_platform.genai import VLM  # Note: VLM, not LLM

from hailo_apps.python.core.common.core import resolve_hef_path
from hailo_apps.python.core.common.defines import SHARED_VDEVICE_GROUP_ID, HAILO10H_ARCH
from hailo_apps.python.core.common.hailo_logger import get_logger

logger = get_logger(__name__)


def main():
    parser = argparse.ArgumentParser(description="VLM Image Analysis")
    parser.add_argument("--hef-path", type=str, default=None)
    parser.add_argument("--image", type=str, required=True, help="Path to input image")
    parser.add_argument("--question", type=str, default="Describe this image.",
                        help="Question to ask about the image")
    args = parser.parse_args()

    # [CUSTOMIZE: Replace "your_vlm_app" with your app name]
    hef_path = resolve_hef_path(args.hef_path, app_name="your_vlm_app", arch=HAILO10H_ARCH)
    if hef_path is None:
        logger.error("Failed to resolve HEF path.")
        sys.exit(1)

    vdevice = None
    vlm = None

    try:
        params = VDevice.create_params()
        params.group_id = SHARED_VDEVICE_GROUP_ID
        vdevice = VDevice(params)

        # --- Load VLM ---
        # VLM class accepts image frames alongside text prompts
        vlm = VLM(vdevice, str(hef_path))

        # --- Load and Preprocess Image ---
        image = cv2.imread(args.image)
        if image is None:
            raise FileNotFoundError(f"Could not load image: {args.image}")

        # Convert BGR (OpenCV default) to RGB (model expects RGB)
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

        # [CUSTOMIZE: Resize to model's expected input size.
        #  Qwen2-VL-2B-Instruct expects 336x336. Check your model's requirements.]
        image = cv2.resize(image, (336, 336), interpolation=cv2.INTER_LINEAR).astype(np.uint8)

        # --- Construct Multi-Modal Prompt ---
        # The {"type": "image"} entry tells the model where the image goes in the prompt.
        # [CUSTOMIZE: Modify system prompt and user question]
        prompt = [
            {
                "role": "system",
                "content": [{"type": "text", "text": "You are a helpful assistant that analyzes images."}]
            },
            {
                "role": "user",
                "content": [
                    {"type": "image"},  # Placeholder -- the actual image is passed via frames=[]
                    {"type": "text", "text": args.question}
                ]
            }
        ]

        # --- Generate Response ---
        # Note: frames=[image] passes the preprocessed image to the VLM.
        # For multiple images, pass frames=[image1, image2, ...] and add
        # corresponding {"type": "image"} entries in the prompt.
        response = vlm.generate_all(
            prompt=prompt,
            frames=[image],
            temperature=0.1,
            seed=42,
            max_generated_tokens=200,
        )

        # Clean up response
        response = response.split("<|im_end|>")[0]
        print(f"Q: {args.question}")
        print(f"A: {response}")

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        sys.exit(1)

    finally:
        if vlm:
            try:
                vlm.clear_context()
                vlm.release()
            except Exception as e:
                logger.warning(f"Error releasing VLM: {e}")
        if vdevice:
            try:
                vdevice.release()
            except Exception as e:
                logger.warning(f"Error releasing VDevice: {e}")


if __name__ == "__main__":
    main()
```

## Pattern 4: Voice Assistant (Complex App Outline)

For full voice assistants combining STT + LLM + TTS. This is an outline showing the architecture -- refer to `hailo_apps/python/gen_ai_apps/voice_assistant/voice_assistant.py` for the complete implementation.

### Architecture

```
Microphone -> VAD (Voice Activity Detection) -> Whisper STT -> LLM -> TTS -> Speaker
                                                    ^                    |
                                                    |                    v
                                              Keyboard Input     Audio Playback
```

### Key Components

```python
# 1. Shared VDevice for multiple models
from hailo_platform import VDevice
params = VDevice.create_params()
params.group_id = SHARED_VDEVICE_GROUP_ID
vdevice = VDevice(params)

# 2. Speech-to-Text (Whisper)
from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.speech_to_text import SpeechToTextProcessor
s2t = SpeechToTextProcessor(vdevice)
text = s2t.transcribe(audio_data)

# 3. LLM for response generation
from hailo_platform.genai import LLM
llm = LLM(vdevice, str(model_path))

# 4. Text-to-Speech (Piper, CPU-based)
from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.text_to_speech import TextToSpeechProcessor
tts = TextToSpeechProcessor()
tts.queue_text("Hello world", gen_id=0)

# 5. Streaming with TTS callback
from hailo_apps.python.gen_ai_apps.gen_ai_utils.llm_utils import streaming
streaming.generate_and_stream_response(
    llm=llm,
    prompt=formatted_prompt,
    prefix="",
    token_callback=tts_callback,    # Called for each token -- buffer and queue for TTS
    abort_callback=abort_event.is_set,  # Check if user interrupted
)

# 6. Voice Interaction Manager (terminal UI with keyboard controls)
from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.interaction import VoiceInteractionManager
interaction = VoiceInteractionManager(
    title="Your Assistant",
    on_audio_ready=handle_audio,        # Called when recording finishes
    on_processing_start=handle_start,   # Called when processing begins
    on_clear_context=handle_clear,      # Called on 'C' key press
    on_shutdown=handle_shutdown,         # Called on 'Q' key press
    on_abort=handle_abort,              # Called on 'X' key press
    tts=tts,                            # For automatic listening restart after TTS
)
interaction.run()  # Blocks, manages the main loop
```

### Key Patterns

- **Streaming + TTS chunking:** Buffer tokens into sentences, queue each sentence for TTS as it completes. This gives low-latency speech output while the LLM is still generating.
- **Abort/interrupt:** Use `threading.Event` to signal abort. Check it in the token callback and TTS queue.
- **Handshake pattern:** After TTS finishes playing all queued audio, automatically restart the microphone for the next interaction.
- **Context management:** Call `llm.clear_context()` to reset the conversation. The LLM maintains an internal KV cache for multi-turn context.

## Customization Guide

### How to Swap Models

1. `--hef-path <model_name>` for a model registered in `resources_config.yaml`
2. `--hef-path /path/to/model.hef` for a custom local HEF
3. `--list-models` to see available models
4. LLM models: Qwen2.5-1.5B-Instruct (default), others as available
5. VLM models: Qwen2-VL-2B-Instruct (default)
6. STT models: Whisper-Base (used internally by SpeechToTextProcessor)

### How to Add Custom System Prompts

Modify the system message in the prompt list:
```python
prompt = [
    {"role": "system", "content": [{"type": "text", "text": "Your custom persona here."}]},
    {"role": "user", "content": [{"type": "text", "text": user_input}]}
]
```

### How to Add Tool Calling / Function Calling

See `hailo_apps/python/gen_ai_apps/agent_tools_example/` for the full pattern. Key utilities:
- `gen_ai_utils/llm_utils/tool_discovery.py` -- Auto-discover callable Python functions
- `gen_ai_utils/llm_utils/tool_execution.py` -- Execute tool calls parsed from LLM output
- `gen_ai_utils/llm_utils/tool_parsing.py` -- Parse XML-formatted tool calls from LLM text
- `gen_ai_utils/llm_utils/tool_selection.py` -- Match LLM output to available tools

### Generation API Reference

```python
# Single-shot (blocking, returns full text)
response = llm.generate_all(
    prompt=prompt,                   # List of message dicts
    temperature=0.7,                 # 0.0=deterministic, 1.0=creative
    seed=42,                         # For reproducibility (optional)
    max_generated_tokens=256,        # Stop after N tokens
)

# Streaming (yields tokens one at a time)
with llm.generate(
    prompt=prompt,
    temperature=0.7,
    max_generated_tokens=256,
) as stream:
    for token in stream:
        print(token, end="", flush=True)

# VLM generation (with image)
response = vlm.generate_all(
    prompt=prompt,                   # Must include {"type": "image"} in content
    frames=[image_array],            # List of numpy arrays (RGB, uint8)
    temperature=0.1,
    max_generated_tokens=200,
)

# Context management
llm.clear_context()  # Reset KV cache for new conversation
llm.release()        # Free model resources (call when done)
```

### Common Pitfalls

- **Hailo-10H only:** GenAI SDK is not available on Hailo-8 or Hailo-8L. Your app will fail to import on other hardware.
- **Always release resources:** Call `llm.release()` and `vdevice.release()` in a `finally` block. Unreleased resources can lock the device for other processes.
- **VLM image format:** Must be RGB uint8 numpy array at the model's expected resolution (typically 336x336 for Qwen2-VL). OpenCV loads as BGR -- convert with `cv2.cvtColor`.
- **Response cleanup:** Models often append `<|im_end|>` or other special tokens. Clean the response before displaying.
- **Install GenAI deps:** Run `pip install -e ".[gen-ai]"` for voice processing dependencies (piper-tts, sounddevice, etc.).
- **Piper TTS model:** Must be downloaded separately. If not found, TTS gracefully degrades to text-only output.
- **Context window limits:** LLMs have finite context windows. For long conversations, monitor token usage and clear context when approaching limits. See `gen_ai_utils/llm_utils/context_manager.py`.

## Checklist

- [ ] Created `your_app.py` with proper VDevice + model initialization and cleanup
- [ ] Created `__init__.py` in your app directory
- [ ] HEF model is registered in `resources_config.yaml` or you use `--hef-path` directly
- [ ] VDevice uses `SHARED_VDEVICE_GROUP_ID` for compatibility with other apps
- [ ] Resources are released in a `finally` block (both LLM/VLM and VDevice)
- [ ] Response text is cleaned of special tokens (`<|im_end|>`, etc.)
- [ ] Tested on Hailo-10H hardware
- [ ] (For VLM) Image is converted to RGB and resized to model's expected dimensions
- [ ] (For voice apps) Installed gen-ai extras: `pip install -e ".[gen-ai]"`
- [ ] (For voice apps) Piper TTS model is installed or `--no-tts` fallback works
- [ ] (Optional) CLI entry point added to `pyproject.toml`
- [ ] (Optional) Test definition added to `test_definition_config.yaml`
