# Speech Recognition (Whisper)

## What This App Does
Whisper speech-to-text that runs on all Hailo accelerators (Hailo-8/8L/10H). Record from the microphone and get transcription, or transcribe an audio file. Unlike `simple_whisper_chat` (H10-only, uses `genai.Speech2Text`), this app uses the low-level HailoRT `InferModel` API with separate encoder/decoder HEFs so it works on every device.

## Architecture
- **Type:** Standalone app (audio in, text out; no GStreamer)
- **Pattern:** Audio capture/resample → Whisper encoder HEF → decoder HEF (autoregressive) via HailoRT `InferModel`, then token decode + text postprocess
- **Models:** Whisper `base` (default), `tiny`, `tiny.en` (H10 only) — separate encoder + decoder HEFs, auto-downloaded via the central resource system (`resources_config.yaml`)
- **Hardware:** hailo8, hailo8l, hailo10h
- **Postprocess:** Token decoding + text cleanup in `postprocessing.py`

## Key Files
| File | Purpose |
|------|---------|
| `speech_recognition.py` | Entry point — argparse CLI, interactive record/transcribe loop, `main()` |
| `whisper_pipeline.py` | Whisper encoder/decoder orchestration over HailoRT `InferModel` |
| `audio_utils.py` | Microphone capture, file loading, resampling / mel-spectrogram prep |
| `postprocessing.py` | Decoded-token → text postprocessing |
| `assets/` | Bundled decoder assets / tokenizer support files |

## How to Run
```bash
source setup_env.sh
# live microphone (Enter to start/stop recording, 'q' to quit):
python -m hailo_apps.python.standalone_apps.speech_recognition.speech_recognition
# transcribe a file:
python -m hailo_apps.python.standalone_apps.speech_recognition.speech_recognition --audio /path/to/audio.wav
```
Options: `--audio PATH`, `--arch {hailo8,hailo8l,hailo10h}` (auto-detected), `--variant {base,tiny,tiny.en}`, `--duration N` (max record secs, default 10), `--list-models`. Needs `pip install -e ".[speech-rec]"` plus `ffmpeg` and `libportaudio2`.

## How to Extend
- **Swap variant:** Use `--variant` to switch Whisper size; HEFs are resolved/downloaded automatically per arch.
- **Custom audio source:** Replace the capture/resample helpers in `audio_utils.py` to feed audio from a different source while keeping the encoder/decoder path unchanged.
