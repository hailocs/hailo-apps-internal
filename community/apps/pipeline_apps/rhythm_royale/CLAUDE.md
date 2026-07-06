# Rhythm Royale

## What This App Does
A real-time multi-player dance-off. Pose estimation extracts each dancer's motion while an FFT-based audio analyzer detects the music's beat frequency and phase; each dancer is scored on how well their motion aligns (tempo + phase) with the beat, and the highest-scoring "ROCKSTAR" is crowned on screen.

## Architecture
- **Type:** Pipeline app (pose game + DSP)
- **Pattern:** Pose estimation pipeline + parallel audio DSP; callback scores motion-to-beat alignment per tracked dancer
- **Models:** YOLOv8 pose (HEF resolved per architecture via the pose pipeline helper)
- **Hardware:** hailo8, hailo8l, hailo10h
- **Postprocess:** C++ pose postprocess `.so` (`libyolov8_pose_postprocess.so`) + Python scoring

## Key Files
| File | Purpose |
|------|---------|
| `rhythm_royale.py` | Entry point + per-frame callback: pose extraction and scoring |
| `audio_source.py` | Audio capture (mic/line-in or MP3) into a 44.1 kHz ring buffer |
| `beat_extractor.py` | Hilbert + band-pass + FFT (0.5–4 Hz) to extract beat frequency/phase |
| `motion_analyzer.py` | Centroid-trajectory FFT, per-keypoint harmonic scoring |
| `overlay.py` | OpenCV drawing: skeleton, score tags, crown, beat pulse, phase clock |
| `player_ranker.py` | Maintains top-K dancers by bbox stability (avoids flicker) |
| `spectrum_scheduler.py` | Spectrum/scheduling helper (see README) |

## How to Run
```bash
source setup_env.sh
./community/apps/pipeline_apps/rhythm_royale/run.sh --input usb --use-frame
```
Optional: `--audio-device "Loopback"` or `--audio-file path/to/song.mp3`.

## How to Extend
- Widen `SIGMA_F` in `motion_analyzer.py` to tolerate double/half-tempo dancers.
- Tune `KP_WEIGHTS` in `motion_analyzer.py` to re-weight which keypoints dominate scoring.
