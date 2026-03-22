"""Audio utilities for Whisper preprocessing — mel spectrogram, loading, padding."""

import os
from functools import lru_cache
from subprocess import CalledProcessError, run
from typing import Optional, Union

import numpy as np
import torch
import torch.nn.functional as F

# Hard-coded Whisper audio hyperparameters
SAMPLE_RATE = 16000
N_FFT = 400
HOP_LENGTH = 160
CHUNK_LENGTH = 30
N_SAMPLES = CHUNK_LENGTH * SAMPLE_RATE  # 480000 samples in a 30-second chunk


def load_audio(file: str, sr: int = SAMPLE_RATE) -> np.ndarray:
    """Load audio file as mono float32 waveform via ffmpeg."""
    cmd = [
        "ffmpeg", "-nostdin", "-threads", "0",
        "-i", file,
        "-f", "s16le", "-ac", "1", "-acodec", "pcm_s16le", "-ar", str(sr),
        "-"
    ]
    try:
        out = run(cmd, capture_output=True, check=True).stdout
    except CalledProcessError as e:
        raise RuntimeError(f"Failed to load audio: {e.stderr.decode()}") from e
    return np.frombuffer(out, np.int16).flatten().astype(np.float32) / 32768.0


def pad_or_trim(array, length: int = N_SAMPLES, *, axis: int = -1):
    """Pad or trim audio array to match expected encoder input length."""
    if torch.is_tensor(array):
        if array.shape[axis] > length:
            array = array.index_select(dim=axis, index=torch.arange(length, device=array.device))
        if array.shape[axis] < length:
            pad_widths = [(0, 0)] * array.ndim
            pad_widths[axis] = (0, length - array.shape[axis])
            array = F.pad(array, [pad for sizes in pad_widths[::-1] for pad in sizes])
    else:
        if array.shape[axis] > length:
            array = array.take(indices=range(length), axis=axis)
        if array.shape[axis] < length:
            pad_widths = [(0, 0)] * array.ndim
            pad_widths[axis] = (0, length - array.shape[axis])
            array = np.pad(array, pad_widths)
    return array


@lru_cache(maxsize=None)
def mel_filters(device, n_mels: int) -> torch.Tensor:
    """Load mel filterbank matrix from bundled .npz asset."""
    assert n_mels in {80, 128}, f"Unsupported n_mels: {n_mels}"
    filters_path = os.path.join(os.path.dirname(__file__), "assets", "mel_filters.npz")
    with np.load(filters_path, allow_pickle=False) as f:
        return torch.from_numpy(f[f"mel_{n_mels}"]).to(device)


def log_mel_spectrogram(
    audio: Union[str, np.ndarray, torch.Tensor],
    n_mels: int = 80,
    padding: int = 0,
    device: Optional[Union[str, torch.device]] = None,
) -> torch.Tensor:
    """Compute log-Mel spectrogram of audio waveform."""
    if not torch.is_tensor(audio):
        if isinstance(audio, str):
            audio = load_audio(audio)
        audio = torch.from_numpy(audio)
    if device is not None:
        audio = audio.to(device)
    if padding > 0:
        audio = F.pad(audio, (0, padding))
    window = torch.hann_window(N_FFT).to(audio.device)
    stft = torch.stft(audio, N_FFT, HOP_LENGTH, window=window, return_complex=True)
    magnitudes = stft[..., :-1].abs() ** 2
    filters = mel_filters(audio.device, n_mels)
    mel_spec = filters @ magnitudes
    log_spec = torch.clamp(mel_spec, min=1e-10).log10()
    log_spec = torch.maximum(log_spec, log_spec.max() - 8.0)
    log_spec = (log_spec + 4.0) / 4.0
    return log_spec


def preprocess_audio(audio: np.ndarray, chunk_length: int = 10,
                     chunk_offset: float = 0, max_duration: int = 60) -> list:
    """Convert audio waveform to mel spectrogram chunks for the encoder."""
    max_samples = max_duration * SAMPLE_RATE
    offset = int(chunk_offset * SAMPLE_RATE)
    segment_samples = chunk_length * SAMPLE_RATE

    audio = audio[offset:max_samples]
    mel_spectrograms = []

    for start in range(0, len(audio), segment_samples):
        if start >= len(audio):
            break
        chunk = audio[start:start + segment_samples]
        chunk = pad_or_trim(chunk, int(chunk_length * SAMPLE_RATE))
        mel = log_mel_spectrogram(chunk).to("cpu")
        mel = np.expand_dims(mel, axis=0)
        mel = np.expand_dims(mel, axis=2)
        mel = np.transpose(mel, [0, 2, 3, 1])  # NHWC
        mel_spectrograms.append(mel)

    return mel_spectrograms


def detect_speech_start(audio: np.ndarray, threshold: float = 0.2,
                        frame_duration: float = 0.2) -> Optional[float]:
    """Simple energy-based VAD — returns time (seconds) of first speech, or None."""
    if len(audio.shape) == 2:
        audio = np.mean(audio, axis=1)
    frame_size = int(frame_duration * SAMPLE_RATE)
    frames = [audio[i:i + frame_size] for i in range(0, len(audio), frame_size)]
    energy = [np.sum(np.abs(f) ** 2) / len(f) for f in frames]
    max_energy = max(energy) if energy else 0
    if max_energy > 0:
        energy = [e / max_energy for e in energy]
    for i, e in enumerate(energy):
        if e > threshold:
            return round(i * frame_duration, 1)
    return None


def improve_audio(audio: np.ndarray, target_peak: float = 0.9) -> tuple:
    """Normalize audio to *target_peak* amplitude and detect speech start.

    Whisper was trained on properly-leveled audio so feeding in quiet
    recordings (e.g. max 0.2) causes the encoder to treat the signal as
    silence and the decoder produces garbage like "-".

    The fix: always peak-normalize so the loudest sample hits *target_peak*.
    """
    peak = np.max(np.abs(audio))
    if peak > 1e-6:  # avoid divide-by-zero on true silence
        audio = audio * (target_peak / peak)
    start_time = detect_speech_start(audio)
    return audio, start_time
