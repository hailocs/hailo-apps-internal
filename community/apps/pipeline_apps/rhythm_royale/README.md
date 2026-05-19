# Rhythm Royale

Real-time multi-player dance-off scored against the music's beat.

The app watches one or more dancers via a single camera, listens to a music
stream (microphone or line-in by default; MP3 file for dev/testing), and
assigns each dancer a 0–100 score based on how well their motion is
synchronized to the beat — both in **tempo** (motion frequency vs. beat
frequency) and **phase** (are you on the down-beat or off?). The
highest-scoring dancer is crowned **ROCKSTAR** on screen.

## How it works

Two parallel signal-processing chains converge at a per-track score.

### Music chain — `beat_extractor.py`

1. Audio is captured by `AudioSource` (mic, line-in, or MP3 file) into a ring
   buffer at 44.1 kHz.
2. Hilbert-transform amplitude envelope of the last 4 s of audio.
3. Decimate envelope to 100 Hz.
4. Butterworth band-pass to **0.5–4 Hz** (30–240 BPM range).
5. Hann-windowed FFT. Peak search restricted to **0.75–3.8 Hz** to avoid
   filter-edge artifacts.
6. Confidence = peak / median of off-peak bins; reject below 2.0.
   Reports `(f_beat, phase, confidence)`.

### Motion chain — `motion_analyzer.py`

1. Per track, store the **weighted centroid** of dance-relevant keypoints
   (wrists, hips, ankles, nose; torso-normalized) each frame.
2. Resample the 4-second centroid trajectory to 100 Hz for both x and y axes.
3. Detrend, band-pass to **0.5–4 Hz**, FFT both channels.
4. Pick the channel (x or y) with the stronger in-band peak as the dominant
   axis. (A signed scalar is required — a velocity *magnitude* signal
   full-wave-rectifies and reports twice the bob frequency.)
5. Compute:
   - `freq_match = exp(-((f_motion - f_beat) / 0.4)²)`
   - `phase_match = ½(1 + cos(Δφ))` at the beat frequency
   - `energy_gate = clip(rms_band / 0.05, 0, 1)`
6. `raw_score = freq_match × phase_match × energy_gate`, smoothed with
   `ALPHA=0.15` exponential moving average.

The track with the highest smoothed score (floor: 0.15) is crowned.

## Run

```bash
source setup_env.sh

# Real-time with mic / line-in (default)
./community/apps/pipeline_apps/rhythm_royale/run.sh --input usb --use-frame

# Specify an input device (e.g. line-in or PulseAudio loopback)
./community/apps/pipeline_apps/rhythm_royale/run.sh \
    --input usb --use-frame --audio-device "Loopback"

# Dev / reproducible testing with an MP3 file (also plays it back)
./community/apps/pipeline_apps/rhythm_royale/run.sh \
    --input usb --use-frame --audio-file path/to/song.mp3
```

### CLI

| Flag | Default | Purpose |
|---|---|---|
| `--audio-file` | _none_ | Path to MP3/WAV/FLAC. Playback + analysis. Dev/testing. |
| `--audio-device` | system default | sounddevice input device for live capture. |
| `--audio-rate` | `44100` | Mic capture sample rate. |
| `--no-playback` | off | Suppress playback when using `--audio-file`. |
| All `get_pipeline_parser()` flags (`--input`, `--use-frame`, `--arch`, ...) | | Inherited from the standard pipeline parser. |

## Listing input devices

```bash
python3 -c "import sounddevice as sd; print(sd.query_devices())"
```

Pick the device name (or substring) and pass it via `--audio-device`.

## Tuning

DSP constants live at the top of each module — keep them constant unless
you have a specific reason:

| Constant | File | Effect |
|---|---|---|
| `BEAT_LO_HZ`, `BEAT_HI_HZ` | beat_extractor.py | Filter passband (Hz). |
| `PEAK_LO_HZ`, `PEAK_HI_HZ` | beat_extractor.py | Peak-search range (skip filter edges). |
| `MIN_CONF` | beat_extractor.py | Min peak/floor ratio to report a beat. |
| `MIN_INPUT_RMS` | beat_extractor.py | Absolute silence floor. |
| `WIN_AUDIO_S`, `WIN_MOTION_S` | both | Analysis window — longer = stabler, slower to react. |
| `SIGMA_F` | motion_analyzer.py | Tolerance for tempo mismatch (Gaussian σ in Hz). |
| `RMS_GATE` | motion_analyzer.py | How energetic counts as "really dancing". |
| `ALPHA` | motion_analyzer.py | Score smoothing time constant. |
| `KP_WEIGHTS` | motion_analyzer.py | Per-keypoint weight for the centroid. |

## Tests

Unit tests cover the DSP and audio plumbing — they do **not** require a
Hailo accelerator and run on any laptop.

```bash
python3 -m pytest community/apps/pipeline_apps/rhythm_royale/tests/ -v
```

| Test | What it asserts |
|---|---|
| `test_audio_source.py` | MP3 file → ring buffer at correct rate; empty buffer returns None. |
| `test_beat_extractor.py` | MP3 click-style tracks at 60/120/180 BPM are detected at 1/2/3 Hz; silence yields None. |
| `test_motion_analyzer.py` | Synthetic dancer in sync scores high; out-of-phase scores lower; still person scores ~zero. |

The full **live** smoke test (camera + Hailo + audio + overlay) must run on
the Hailo board.

## Limitations

- Half-tempo / double-tempo dancers can be slightly penalized; widen
  `SIGMA_F` if you want to be more forgiving.
- Live mic input also picks up the dancers' footsteps and clapping, biasing
  the envelope. Prefer line-in from the speaker output, a USB loopback, or
  PulseAudio's monitor source for fair scoring.
- Latency from mic to analysis is ~0.5 s; on long delays, the phase term
  can drift. Use `--audio-file` for tight sync during demos.
- Designed for full-body framing (head + hips + ankles visible). Heads-only
  framing reduces the motion signal.

## Files

```
rhythm_royale/
├── app.yaml                 # community-app manifest
├── run.sh                   # launch wrapper (sets PYTHONPATH)
├── rhythm_royale.py         # GStreamer subclass + per-frame callback
├── audio_source.py          # mic/file capture into a ring buffer
├── beat_extractor.py        # envelope → bandpass → FFT → BeatState
├── motion_analyzer.py       # per-track centroid signal → TrackScore
├── overlay.py               # skeleton, score tag, crown, beat pulse
└── tests/                   # pytest, no Hailo required
```

Plan and rationale: `docs/superpowers/plans/2026-05-19-rhythm-royale.md`.
