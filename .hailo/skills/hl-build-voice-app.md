# Skill: Build Voice Application

Build voice apps for **all Hailo accelerators**: Whisper STT on Hailo-8/8L/10H + optional Piper TTS on CPU.

## When This Skill Is Loaded

- User wants **speech input** or **speech output** in a Hailo app
- User mentions: voice, speech, Whisper, TTS, microphone, STT, speak, listen
- User wants to add voice to an existing LLM or VLM app
- User wants speech recognition on Hailo-8 or Hailo-8L

## Hardware Compatibility

| Feature | Hailo-8/8L | Hailo-10H |
|---|---|---|
| STT (Whisper) | ✓ via `InferModel` (encoder+decoder HEFs) | ✓ via `Speech2Text` (genai API) |
| LLM on device | ✘ | ✓ via `hailo_platform.genai.LLM` |
| VLM on device | ✘ | ✓ via `Backend` (VLM chat) |
| TTS (Piper) | ✓ CPU | ✓ CPU |
| Full voice assistant | STT + CPU LLM + TTS | STT + on-device LLM + TTS |

## Reference Implementations

Study these:
- `hailo_apps/python/gen_ai_apps/voice_assistant/` — Full voice + LLM assistant (Hailo-10H)
- `hailo_apps/python/gen_ai_apps/simple_whisper_chat/` — Simple STT example (Hailo-10H)
- `hailo_apps/python/standalone_apps/speech_recognition/` — STT for **all Hailo devices** (8/8L/10H) using InferModel API:
  - `speech_recognition.py` — Main app: mic recording, audio preprocessing, transcription loop
  - `whisper_pipeline.py` — `WhisperPipeline` class: encoder+decoder inference via `InferModel`
  - `audio_utils.py` — Audio recording, mel spectrogram, file I/O
  - `postprocessing.py` — Repetition penalty and token decoding
- `hailo_apps/python/gen_ai_apps/gen_ai_utils/voice_processing/` — Voice utilities (Hailo-10H):
  - `speech_to_text.py` — `SpeechToTextProcessor` (Whisper via genai API)
  - `text_to_speech.py` — `TextToSpeechProcessor` (Piper on CPU)
  - `audio_recorder.py` — `AudioRecorder` (microphone capture)
  - `vad.py` — Voice Activity Detection
  - `interaction.py` — `VoiceInteractionManager` (high-level orchestrator)

## Build Process

### Step 1: Create App Directory

Create the app directory:

```
hailo_apps/python/<type>/<app_name>/
├── app.yaml              # App manifest (type: gen_ai)
├── run.sh                # Launch wrapper
├── __init__.py
├── <app_name>.py         # Main app
└── README.md             # Usage documentation (REQUIRED — never skip)
```

Create `app.yaml` with `type: gen_ai` and `run.sh` wrapper.
Do NOT register in `defines.py` or `resources_config.yaml`.

### Step 2: Build Main App (Hailo-10H: Voice + LLM)

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
    SHARED_VDEVICE_GROUP_ID,
    HAILO10H_ARCH,
)

logger = get_logger(__name__)

from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.speech_to_text import SpeechToTextProcessor
from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.text_to_speech import TextToSpeechProcessor
from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.interaction import VoiceInteractionManager
from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.vad import add_vad_args

APP_NAME = "my_voice_app"

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

### Step 3: Validate (Hailo-10H)

```bash
python3 .hailo/scripts/validate_app.py hailo_apps/python/gen_ai_apps/my_voice_app --smoke-test
```

### Step 2b: Build Main App (Hailo-8/8L: Speech Recognition)

For Hailo-8/8L, use the `InferModel` API with separate encoder + decoder HEFs:

```python
import signal
import sys
import time

import numpy as np

from hailo_apps.python.core.common.toolbox import resolve_arch
from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.common.core import resolve_hef_paths
from hailo_apps.python.core.common.parser import get_standalone_parser
from hailo_apps.python.core.common.defines import (
    WHISPER_H8_APP, RESOURCES_ROOT_PATH_DEFAULT, RESOURCES_NPY_DIR_NAME,
)

logger = get_logger(__name__)

APP_NAME = "my_speech_app"


def main():
    parser = get_standalone_parser()
    parser.add_argument("--audio", type=str, help="Audio file to transcribe (skip mic)")
    parser.add_argument("--variant", default="base", choices=["base", "tiny", "tiny.en"],
                        help="Whisper model variant")
    parser.add_argument("--duration", type=int, default=10, help="Max recording seconds")
    args = parser.parse_args()

    arch = resolve_arch(args.arch)  # Auto-detect or --arch flag

    # Resolve encoder + decoder HEFs (plural — Whisper uses two separate models)
    hef_paths = resolve_hef_paths(None, WHISPER_H8_APP, arch=arch)
    encoder_path = str(hef_paths["encoder"])
    decoder_path = str(hef_paths["decoder"])

    # Decoder assets directory
    npy_dir = str(Path(RESOURCES_ROOT_PATH_DEFAULT) / RESOURCES_NPY_DIR_NAME)

    # WhisperPipeline — uses InferModel API, works on ALL Hailo devices
    from .whisper_pipeline import WhisperPipeline
    pipeline = WhisperPipeline(
        encoder_path=encoder_path,
        decoder_path=decoder_path,
        variant=args.variant,
        npy_dir=npy_dir,
        add_embed=(arch != "hailo10h"),  # H8/8L need host-side Add operator
    )

    if args.audio:
        # Single file transcription
        mel = preprocess_audio_file(args.audio, pipeline.get_chunk_length())
        pipeline.send_data(mel)
        text = pipeline.get_transcription()
        print(f"Transcription: {text}")
    else:
        # Interactive mic loop
        logger.info("Ready. Press Enter to start recording, Enter to stop. 'q' to quit.")
        while True:
            cmd = input("Press Enter to record (q to quit): ").strip()
            if cmd.lower() == "q":
                break
            audio = record_from_mic(duration=args.duration)
            mel = audio_to_mel(audio, pipeline.get_chunk_length())
            pipeline.send_data(mel)
            text = pipeline.get_transcription()
            print(f"Transcription: {text}")

    pipeline.stop()
    logger.info("Done")


if __name__ == "__main__":
    main()
```

**Key differences from H10 pattern**:
- Uses `resolve_hef_paths()` (plural) — returns dict with `encoder` and `decoder` keys
- Uses `WhisperPipeline` with `InferModel` API — NOT `SpeechToTextProcessor`
- `add_embed` flag: `True` for H8/8L (host-side Add operator), `False` for H10
- No LLM/VLM on device — inference is CPU or external service
- Dependencies: `pip install -e ".[speech-rec]"` (torch, transformers, sounddevice, scipy)

### Step 3b: Validate (Hailo-8/8L)

```bash
python3 .hailo/scripts/validate_app.py hailo_apps/python/standalone_apps/my_speech_app --smoke-test
```

## Critical Conventions

1. **STT on Hailo, TTS on CPU**: Never reverse this — Whisper needs the accelerator, Piper is CPU-only
2. **Two STT APIs**: `SpeechToTextProcessor` (genai) for H10, `WhisperPipeline` (InferModel) for H8/8L/10H
3. **Architecture detection**: Use `detect_hailo_arch()` or `--arch` flag — never hardcode
4. **ALSA noise**: Wrap audio init with `redirect_stderr(StringIO())`
5. **Abort event**: `threading.Event()` for interrupting generation and speech
6. **Init order**: VDevice → STT → LLM (H10 only) → TTS → VoiceInteractionManager
7. **Cleanup order**: Reverse of init, in `finally` block
8. **VAD args**: Always use `add_vad_args(parser)` for `--vad`, `--vad-aggressiveness`, `--vad-energy-threshold`
9. **--no-tts**: Always support text-only mode as fallback
10. **H8/8L HEF resolution**: Use `resolve_hef_paths()` (plural) — Whisper needs encoder + decoder HEFs
11. **H10 HEF resolution**: Use `resolve_hef_path()` (singular) — single HEF per model
12. **Dependencies**: H10 voice requires `[gen-ai]` extras; H8/8L STT requires `[speech-rec]` extras

## Adding Voice to an Existing App

To add voice to any existing LLM/VLM app:

1. Import voice utilities
2. Add `--voice` and `--no-tts` CLI flags + `add_vad_args(parser)`
3. Init STT + TTS alongside existing model
4. Replace `input()` with `vim.listen()` when `--voice` is set
5. Add `vim.speak(response)` after generating output
6. Add `abort_event` for interruption support

