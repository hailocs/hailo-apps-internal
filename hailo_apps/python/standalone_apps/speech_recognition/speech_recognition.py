"""
Speech Recognition for Hailo-8/8L/10H.

Simple CLI app: record from microphone or load an audio file, transcribe with Whisper
running on any Hailo accelerator via the low-level InferModel API.

Models are managed by the repo's central resource system (resources_config.yaml)
and auto-downloaded on first use via resolve_hef_paths().

Usage:
    # Record from microphone (press Enter to start/stop):
    python -m hailo_apps.python.standalone_apps.speech_recognition.speech_recognition

    # Transcribe an audio file:
    python -m hailo_apps.python.standalone_apps.speech_recognition.speech_recognition \
        --audio recording.wav

    # List available models:
    python -m hailo_apps.python.standalone_apps.speech_recognition.speech_recognition \
        --list-models
"""

import argparse
import os
import sys
import time
import queue
from pathlib import Path

import numpy as np


def check_dependencies():
    """Exit with instructions if required packages are missing."""
    missing = []
    for dep in ["torch", "transformers", "sounddevice", "scipy"]:
        try:
            __import__(dep)
        except ImportError:
            missing.append(dep)
    if missing:
        print(f"\nMissing dependencies: {', '.join(missing)}")
        print("\nRun the following command from the 'hailo-apps' repository root directory (where pyproject.toml is located):")
        print('  pip install -e ".[speech-rec]"')
        sys.exit(1)


def _setup_imports():
    """Handle imports with fallback for dev-mode."""
    try:
        from hailo_apps.python.core.common.toolbox import resolve_arch
        from hailo_apps.python.core.common.hailo_logger import get_logger
        from hailo_apps.python.core.common.core import resolve_hef_paths
        from hailo_apps.python.core.common.defines import (
            WHISPER_H8_APP, RESOURCES_ROOT_PATH_DEFAULT,
            RESOURCES_NPY_DIR_NAME,
        )
        return resolve_arch, get_logger, resolve_hef_paths, WHISPER_H8_APP, \
            RESOURCES_ROOT_PATH_DEFAULT, RESOURCES_NPY_DIR_NAME
    except ImportError:
        repo_root = None
        for p in Path(__file__).resolve().parents:
            if (p / "hailo_apps" / "config" / "config_manager.py").exists():
                repo_root = p
                break
        if repo_root:
            sys.path.insert(0, str(repo_root))
        from hailo_apps.python.core.common.toolbox import resolve_arch
        from hailo_apps.python.core.common.hailo_logger import get_logger
        from hailo_apps.python.core.common.core import resolve_hef_paths
        from hailo_apps.python.core.common.defines import (
            WHISPER_H8_APP, RESOURCES_ROOT_PATH_DEFAULT,
            RESOURCES_NPY_DIR_NAME,
        )
        return resolve_arch, get_logger, resolve_hef_paths, WHISPER_H8_APP, \
            RESOURCES_ROOT_PATH_DEFAULT, RESOURCES_NPY_DIR_NAME


# --- Audio recording ---

SAMPLE_RATE = 16000
CHANNELS = 1


def record_audio(duration: int = 10) -> np.ndarray:
    """
    Record audio from microphone. Press Enter to stop early.

    Args:
        duration: Max recording time in seconds.

    Returns:
        Audio waveform as float32 numpy array.
    """
    import sounddevice as sd

    audio_q = queue.Queue()

    def callback(indata, frames, time_info, status):
        if status:
            print(f"  ⚠ {status}")
        audio_q.put(indata.copy())

    print(f"🎤 Recording (up to {duration}s) — press Enter to stop early...")

    stream = sd.InputStream(
        samplerate=SAMPLE_RATE, channels=CHANNELS,
        dtype="float32", callback=callback,
    )
    stream.start()

    # Monitor for Enter key or timeout
    start = time.time()
    try:
        # Check for Enter key press (non-blocking)
        if os.name == "nt":
            import msvcrt

            while time.time() - start < duration:
                if msvcrt.kbhit():
                    ch = msvcrt.getwch()
                    if ch in ("\r", "\n"):
                        print("  Stopped early.")
                        break
                time.sleep(0.1)
        else:
            import select

            while time.time() - start < duration:
                try:
                    if select.select([sys.stdin], [], [], 0.5)[0]:
                        sys.stdin.readline()
                        print("  Stopped early.")
                        break
                except (OSError, ValueError):
                    # Skip input detection and continue timing loop
                    time.sleep(0.5)
    finally:
        stream.stop()
        stream.close()

    # Collect all recorded frames
    frames = []
    while not audio_q.empty():
        frames.append(audio_q.get())

    if not frames:
        return np.array([], dtype=np.float32)

    audio = np.concatenate(frames, axis=0)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    elapsed = time.time() - start
    print(f"  ✓ Recorded {elapsed:.1f}s")
    return audio


def save_wav(audio: np.ndarray, path: str):
    """Save audio to WAV file."""
    import scipy.io.wavfile as wav
    wav.write(path, SAMPLE_RATE, (audio * 32767).astype(np.int16))


# --- Variant-to-model-name mapping ---
# Maps (variant, arch) to (encoder_name, decoder_name) as registered in resources_config.yaml
VARIANT_MODELS = {
    "base": {
        "hailo8": (
            "base-whisper-encoder-5s",
            "base-whisper-decoder-fixed-sequence-matmul-split",
        ),
        "hailo8l": (
            "base-whisper-encoder-5s_h8l",
            "base-whisper-decoder-fixed-sequence-matmul-split_h8l",
        ),
        "hailo10h": (
            "base-whisper-encoder-10s",
            "base-whisper-decoder-10s-out-seq-64",
        ),
    },
    "tiny": {
        "hailo8": (
            "tiny-whisper-encoder-10s_15dB",
            "tiny-whisper-decoder-fixed-sequence-matmul-split",
        ),
        "hailo8l": (
            "tiny-whisper-encoder-10s_15dB_h8l",
            "tiny-whisper-decoder-fixed-sequence-matmul-split_h8l",
        ),
        "hailo10h": (
            "tiny-whisper-encoder-10s",
            "tiny-whisper-decoder-fixed-sequence",
        ),
    },
    "tiny.en": {
        "hailo10h": (
            "tiny_en-whisper-encoder-10s",
            "tiny_en-whisper-decoder-fixed-sequence",
        ),
    },
}


def _ensure_npy_assets(variant, npy_dir, app_name, arch, resources_root):
    """Check that decoder npy assets exist; auto-download if missing."""
    needed = [
        f"token_embedding_weight_{variant}.npy",
        f"onnx_add_input_{variant}.npy",
    ]
    missing = [f for f in needed if not (Path(npy_dir) / f).exists()]
    if not missing:
        return

    print(f"\n⚠️  Decoder tokenization assets not found for variant '{variant}'.")
    print("   Downloading automatically...\n")

    try:
        from hailo_apps.installation.download_resources import (
            ResourceDownloader, load_config, DEFAULT_RESOURCES_CONFIG_PATH,
        )
        config = load_config(Path(DEFAULT_RESOURCES_CONFIG_PATH))
        downloader = ResourceDownloader(
            config=config,
            hailo_arch=arch,
            resource_root=Path(resources_root),
        )
        downloader.collect_npy_by_tag(app_name)
        downloader.execute(parallel=False)
    except Exception as e:
        print(f"   Download failed: {e}")

    still_missing = [f for f in needed if not (Path(npy_dir) / f).exists()]
    if still_missing:
        print(f"\n❌ Decoder assets still missing: {still_missing}")
        print(f"   Expected in: {npy_dir}")
        print("   Try running the full resource download:")
        print(f"   python -m hailo_apps.installation.download_resources --group {app_name}\n")
        sys.exit(1)


# --- Main ---

def get_args():
    parser = argparse.ArgumentParser(
        description="Speech Recognition (Hailo-8/8L/10H)",
    )
    parser.add_argument(
        "--audio", type=str, default=None,
        help="Path to audio file. If omitted, records from microphone.",
    )
    parser.add_argument(
        "--arch", type=str, default=None,
        choices=["hailo8", "hailo8l", "hailo10h"],
        help="Target architecture (auto-detected if omitted)",
    )
    parser.add_argument(
        "--variant", type=str, default="base",
        choices=["base", "tiny", "tiny.en"],
        help="Whisper model variant (default: base)",
    )
    parser.add_argument(
        "--duration", type=int, default=10,
        help="Max recording duration in seconds (default: 10)",
    )
    parser.add_argument(
        "--list-models", action="store_true",
        help="List available models and exit",
    )
    return parser.parse_args()


def main():
    (resolve_arch, get_logger, resolve_hef_paths, WHISPER_H8_APP,
     RESOURCES_ROOT, NPY_DIR) = _setup_imports()
    logger = get_logger(__name__)

    args = get_args()
    arch = resolve_arch(args.arch)
    variant = args.variant

    # Handle --list-models
    if args.list_models:
        from hailo_apps.python.core.common.core import handle_list_models_flag
        handle_list_models_flag(args, WHISPER_H8_APP)
        return

    # Check dependencies
    check_dependencies()

    # Resolve encoder + decoder HEF model names for this variant/arch
    try:
        encoder_name, decoder_name = VARIANT_MODELS[variant][arch]
    except KeyError:
        available = list(VARIANT_MODELS.get(variant, {}).keys())
        logger.error(
            f"No models for variant='{variant}' arch='{arch}'. "
            f"Available archs: {available}"
        )
        sys.exit(1)

    # Use the central resolve_hef_paths to find/download HEFs
    resolved = resolve_hef_paths(
        hef_paths=[encoder_name, decoder_name],
        app_name=WHISPER_H8_APP,
        arch=arch,
    )
    encoder_path = str(resolved[0].path)
    decoder_path = str(resolved[1].path)

    print(f"Architecture: {arch}")
    print(f"Variant: Whisper {variant}")
    print(f"Encoder: {encoder_path}")
    print(f"Decoder: {decoder_path}")

    # Resolve decoder npy assets from central resources/npy/ directory
    npy_dir = Path(RESOURCES_ROOT) / NPY_DIR

    # Auto-download npy assets if missing
    _ensure_npy_assets(variant, npy_dir, WHISPER_H8_APP, arch, RESOURCES_ROOT)

    # Initialize pipeline
    try:
        from .whisper_pipeline import WhisperPipeline
        from .audio_utils import (
            load_audio, preprocess_audio, improve_audio, SAMPLE_RATE as SR,
        )
        from .postprocessing import clean_transcription
    except ImportError:
        from whisper_pipeline import WhisperPipeline
        from audio_utils import (
            load_audio, preprocess_audio, improve_audio, SAMPLE_RATE as SR,
        )
        from postprocessing import clean_transcription

    print("\nInitializing Whisper pipeline...")
    # H8/H8L decoders need Add+Unsqueeze+Transpose on host;
    # H10H decoders include the Add in the HEF.
    add_embed = arch in ("hailo8", "hailo8l")
    pipeline = WhisperPipeline(
        encoder_path, decoder_path, variant=variant, npy_dir=str(npy_dir),
        add_embed=add_embed,
    )
    chunk_length = pipeline.get_chunk_length()
    print(f"✓ Ready (chunk length: {chunk_length}s)\n")

    try:
        if args.audio:
            # --- File mode: transcribe once ---
            _transcribe_file(args.audio, pipeline, chunk_length)
        else:
            # --- Interactive mic recording loop ---
            print("=" * 50)
            print("  Whisper on Hailo — Live Transcription")
            print("  Press Enter to record, 'q' to quit")
            print("=" * 50)

            while True:
                user = input("\nPress Enter to record (or 'q' to quit): ")
                if user.strip().lower() == 'q':
                    break

                audio = record_audio(duration=args.duration)
                if len(audio) == 0:
                    print("⚠ No audio recorded.")
                    continue

                # Save for debugging
                save_wav(audio, "last_recording.wav")

                _transcribe_audio(audio, pipeline, chunk_length)

    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        pipeline.stop()
        print("Done.")


def _transcribe_file(audio_path: str, pipeline, chunk_length: int):
    """Load file, preprocess, and transcribe."""
    try:
        from .audio_utils import load_audio, preprocess_audio, improve_audio
        from .postprocessing import clean_transcription
    except ImportError:
        from audio_utils import load_audio, preprocess_audio, improve_audio
        from postprocessing import clean_transcription

    if not os.path.exists(audio_path):
        print(f"File not found: {audio_path}")
        return

    print(f"Loading: {audio_path}")
    audio = load_audio(audio_path)
    duration = len(audio) / SAMPLE_RATE
    print(f"✓ Loaded ({duration:.1f}s)")

    _transcribe_audio(audio, pipeline, chunk_length)


def _transcribe_audio(audio: np.ndarray, pipeline, chunk_length: int):
    """Preprocess and transcribe raw audio array."""
    try:
        from .audio_utils import preprocess_audio, improve_audio
        from .postprocessing import clean_transcription
    except ImportError:
        from audio_utils import preprocess_audio, improve_audio
        from postprocessing import clean_transcription

    peak_before = np.max(np.abs(audio))
    audio, start_time = improve_audio(audio)
    if start_time is None:
        print("⚠ No speech detected.")
        return

    offset = max(start_time - 0.2, 0)
    mels = preprocess_audio(audio, chunk_length=chunk_length, chunk_offset=offset)
    print(f"Transcribing ({len(mels)} chunk(s), "
          f"gain {peak_before:.2f}→{np.max(np.abs(audio)):.2f})...")

    t0 = time.time()
    results = []
    for mel in mels:
        pipeline.send_data(mel)
        time.sleep(0.1)
        text = pipeline.get_transcription()
        results.append(text)

    elapsed = time.time() - t0
    full_text = clean_transcription(" ".join(results))

    print("-" * 50)
    print(full_text.strip())
    print("-" * 50)
    print(f"({elapsed:.1f}s)")


if __name__ == "__main__":
    main()
