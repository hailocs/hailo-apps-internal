---
name: hl-build-voice-app
description: Build a complete voice-enabled app with Whisper STT on Hailo + Piper TTS on CPU.
---

# Skill: Build Voice Assistant Application

Build a complete voice-enabled app with Whisper STT on Hailo + Piper TTS on CPU.

## When This Skill Is Loaded

- User wants **speech input** or **speech output** in a Hailo app
- User mentions: voice, speech, Whisper, TTS, microphone, STT, speak, listen
- User wants to add voice to an existing LLM or VLM app

## Reference Implementations

Study these:
- `hailo_apps/python/gen_ai_apps/voice_assistant/` — Full voice + LLM assistant
- `hailo_apps/python/gen_ai_apps/simple_whisper_chat/` — Simple STT example
- `hailo_apps/python/gen_ai_apps/gen_ai_utils/voice_processing/` — Voice utilities:
  - `speech_to_text.py` — `SpeechToTextProcessor` (Whisper on Hailo)
  - `text_to_speech.py` — `TextToSpeechProcessor` (Piper on CPU)
  - `audio_recorder.py` — `AudioRecorder` (microphone capture)
  - `vad.py` — Voice Activity Detection
  - `interaction.py` — `VoiceInteractionManager` (high-level orchestrator)

## Build Process

### Step 1: Create App Directory

Create the app under `community/apps/` (staging area for agent-built apps):

```
community/apps/<app_name>/
├── app.yaml              # App manifest (type: gen_ai)
├── run.sh                # Launch wrapper
├── __init__.py
├── <app_name>.py         # Main app
└── README.md
```

Create `app.yaml` with `type: gen_ai` and `run.sh` wrapper.
Do NOT register in `defines.py` or `resources_config.yaml`.

### Step 2: Create Directory Structure

Same as Step 1 above — all files go in `community/apps/<app_name>/`.

### Step 3: Build Main App

```python
import signal
import threading
from contextlib import redirect_stderr
from io import StringIO

from hailo_platform import VDevice
from hailo_platform.genai import LLM

from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.common.core import resolve_hef_path
from hailo_apps.python.core.common.parser import get_standalone_parser
from hailo_apps.python.core.common.defines import (
    MY_VOICE_APP,
    SHARED_VDEVICE_GROUP_ID,
    HAILO10H_ARCH,
)
from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.speech_to_text import SpeechToTextProcessor
from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.text_to_speech import TextToSpeechProcessor
from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.interaction import VoiceInteractionManager
from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.vad import add_vad_args

logger = get_logger(__name__)

APP_NAME = MY_VOICE_APP
SYSTEM_PROMPT = "You are a helpful voice assistant. Keep responses concise and natural."


def main():
    parser = get_standalone_parser()
    parser.add_argument("--no-tts", action="store_true", help="Disable TTS (text only)")
    parser.add_argument("--system-prompt", type=str, default=SYSTEM_PROMPT)
    add_vad_args(parser)
    args = parser.parse_args()

    abort_event = threading.Event()
    signal.signal(signal.SIGINT, lambda s, f: abort_event.set())

    # VDevice
    params = VDevice.create_params()
    params.group_id = SHARED_VDEVICE_GROUP_ID
    vdevice = VDevice(params)

    # STT (Whisper on Hailo)
    whisper_hef = resolve_hef_path(None, "whisper", arch=HAILO10H_ARCH)
    with redirect_stderr(StringIO()):  # Suppress ALSA noise
        stt = SpeechToTextProcessor(vdevice, str(whisper_hef))

    # LLM (on Hailo)
    llm_hef = resolve_hef_path(args.hef_path, APP_NAME, arch=HAILO10H_ARCH)
    llm = LLM(vdevice, str(llm_hef))

    # TTS (Piper on CPU)
    tts = None if args.no_tts else TextToSpeechProcessor()

    # Voice interaction manager
    vim = VoiceInteractionManager(stt, tts, abort_event)

    logger.info("Voice assistant ready. Speak into your microphone.")
    print("Voice assistant ready. Press Ctrl+C to quit.\n")

    try:
        while not abort_event.is_set():
            # Listen for speech
            user_text = vim.listen()
            if not user_text or abort_event.is_set():
                continue

            logger.info("User said: %s", user_text)
            print(f"You: {user_text}")

            # Generate response
            prompt = [
                {"role": "system", "content": [{"type": "text", "text": args.system_prompt}]},
                {"role": "user", "content": [{"type": "text", "text": user_text}]},
            ]
            response = llm.generate_all(
                prompt=prompt, temperature=0.1, max_generated_tokens=150
            )
            llm.clear_context()

            print(f"Assistant: {response}\n")

            # Speak response
            if tts and not abort_event.is_set():
                vim.speak(response)
    finally:
        llm.release()
        vdevice.release()
        logger.info("Cleanup complete")


if __name__ == "__main__":
    main()
```

### Step 4: Validate

```bash
# No relative imports
grep -rn "^from \.\|^import \." hailo_apps/python/gen_ai_apps/my_voice_app/*.py

# CLI works
python -m hailo_apps.python.gen_ai_apps.my_voice_app.my_voice_app --help

# Audio system check
python -m hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.audio_troubleshoot
```

## Critical Conventions

1. **STT on Hailo, TTS on CPU**: Never reverse this — Whisper needs the accelerator, Piper is CPU-only
2. **ALSA noise**: Wrap audio init with `redirect_stderr(StringIO())`
3. **Abort event**: `threading.Event()` for interrupting generation and speech
4. **Init order**: VDevice → STT → LLM → TTS → VoiceInteractionManager
5. **Cleanup order**: Reverse of init, in `finally` block
6. **VAD args**: Always use `add_vad_args(parser)` for `--vad`, `--vad-aggressiveness`, `--vad-energy-threshold`
7. **--no-tts**: Always support text-only mode as fallback
8. **Dependencies**: Requires `[gen-ai]` extras: PyAudio, piper-tts, sounddevice, webrtcvad-wheels

## Adding Voice to an Existing App

To add voice to any existing LLM/VLM app:

1. Import voice utilities
2. Add `--voice` and `--no-tts` CLI flags + `add_vad_args(parser)`
3. Init STT + TTS alongside existing model
4. Replace `input()` with `vim.listen()` when `--voice` is set
5. Add `vim.speak(response)` after generating output
6. Add `abort_event` for interruption support


## Community Findings

<!-- Auto-curated from community/contributions/ — do not edit above this section -->
<!-- New findings are appended here automatically by curate_contributions.py -->

