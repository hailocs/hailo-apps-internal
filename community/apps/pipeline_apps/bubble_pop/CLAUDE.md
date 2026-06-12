# Bubble Pop

## What This App Does
Pose-based interactive mirror game where heart-shaped bubbles float up the screen and pop when touched by a player's wrists. Arm gestures cast "magic spells" (shockwave, glitter rain, magic bolt) that pop hearts. Multi-player: every detected person's wrists can interact.

## Architecture
- **Type:** Pipeline app (interactive pose game)
- **Pattern:** Pose estimation + gesture recognition + game engine (source → inference → tracker → callback → custom OpenCV frame render → display)
- **Models:** YOLOv8 pose (17 COCO keypoints)
- **Hardware:** hailo8, hailo8l, hailo10h
- **Postprocess:** Pure Python callback (gesture detection + game physics); display via user-frame rendering

## Key Files
| File | Purpose |
|------|---------|
| `bubble_pop.py` | Entry point + GStreamer callback: keypoint extraction, gesture casting, spell wiring |
| `bubble_engine.py` | Game engine: heart spawning, pop detection, particle effects, score, HUD |
| `gestures.py` | Gesture recognition (hands-together, arms-up, fast-swipe → spell-cast events) |
| `sound.py` | Pop/spell sound synthesis and throttled playback |

## How to Run
```bash
source setup_env.sh
./community/apps/pipeline_apps/bubble_pop/run.sh --input usb
# or: python -m community.apps.pipeline_apps.bubble_pop.bubble_pop --input usb
```
Optional: `--max-bubbles`, `--spawn-interval`, `--no-sound`, `--no-mirror`.

## How to Extend
- Add new spells by defining a gesture in `gestures.py` and wiring its effect in `bubble_engine.py`.
- Add level progression (rising spawn rate, new bubble types) or persist high scores to a file.
