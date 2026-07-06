# Bubble Pop 💖

A pose-estimation mirror game for kids (and parents): **bubble hearts** float
up from the bottom of the screen and **pop when you touch them with your
hands**. Every pop bursts into colorful particles, plays a pop sound, and
scores a point. Instead of the usual skeleton overlay, each wrist leaves a
**glittery sparkle trail** ✨.

And there's **magic**: cast spells with arm gestures to blow up hearts en
masse.

Multi-player out of the box — every detected person's wrists can pop hearts
and cast spells.

## ✨ Spellbook

| Gesture | Spell | Effect |
|---|---|---|
| 🙏 Press both hands together | **SHOCKWAVE!** | A giant expanding ring bursts from your hands and pops every heart it touches |
| 🙌 Raise both hands above your head | **GLITTER RAIN!** | Sparkles rain from the sky for 3 seconds, popping hearts they land on |
| 💫 Flick a hand fast (like a wand) | **MAGIC BOLT!** | A shooting star flies in the flick direction, popping hearts along its path |

Spells flash their name on screen, play a rising shimmer sound, and all
magic pops count toward the score. Spells have short cooldowns so they
can't be spammed by accident.

## How It Works

1. **Pose estimation** runs on the Hailo accelerator (yolov8 pose), giving
   17 COCO keypoints per tracked person.
2. The callback extracts **wrists, nose and shoulders** (confidence ≥ 0.4)
   of every detected person.
3. The **gesture caster** (pure logic, unit-tested) watches per-person wrist
   motion: hands-together / arms-up transitions and fast swipes become spell
   cast events.
4. The **game engine** (pure OpenCV/numpy, unit-tested) spawns heart-shaped
   bubbles from the bottom that drift up with a gentle wobble. A wrist —
   or a spell — popping a heart triggers burst particles + an expanding
   ring + score + pop sound.
5. The display is **mirrored** by default so it behaves like a real mirror.
6. The GStreamer skeleton overlay is bypassed (display goes to a `fakesink`);
   the game is rendered in its own window via the user-frame display.

## Requirements

- Hailo-8, Hailo-8L, or Hailo-10H accelerator
- USB camera (or video file input)
- Python environment with hailo-apps-infra installed
- `paplay` or `aplay` for the sounds (optional — silently disabled if absent)

## Usage

```bash
# Basic usage — USB camera, mirror mode, sound on, hearts flood
./run.sh --input usb

# Calmer mode (fewer hearts, slower spawning)
./run.sh --input usb --max-bubbles 8 --spawn-interval 0.5

# Quiet mode / no mirror flip
./run.sh --input usb --no-sound --no-mirror
```

## CLI Arguments

All standard pipeline arguments are supported (`--input`, `--arch`,
`--show-fps`, `--hef-path`, etc.), plus:

| Argument | Default | Description |
|---|---|---|
| `--max-bubbles` | `40` | Maximum hearts on screen at once |
| `--spawn-interval` | `0.08` | Average seconds between new hearts |
| `--no-mirror` | off | Disable the mirror (horizontal flip) effect |
| `--no-sound` | off | Disable the pop / spell sounds |

## Architecture

```
USB Camera
  --> SOURCE_PIPELINE --> INFERENCE_PIPELINE (yolov8 pose)
  --> TRACKER_PIPELINE (ByteTrack)
  --> USER_CALLBACK_PIPELINE (Python):
      extract wrists/nose/shoulders per tracked person --> mirror flip
      --> GestureCaster.update()  (shockwave / rain / bolt events)
      --> BubbleGame.cast() + BubbleGame.update()  (spawn/pop/magic/glitter)
      --> BubbleGame.draw()  (hearts, spells, particles, HUD) --> set_frame()
  --> DISPLAY_PIPELINE (fakesink — skeleton overlay never shown)

Game window = user-frame display (cv2 window fed by set_frame)
Sounds      = synthesized WAVs (numpy) played via paplay/aplay subprocess
```

## Files

| File | Purpose |
|---|---|
| `bubble_pop.py` | App + GStreamer callback (keypoint extraction, mirror, spell wiring) |
| `bubble_engine.py` | Game engine: hearts, magic effects, particles, glitter, HUD (no Hailo deps) |
| `gestures.py` | Gesture detection: hands-together / arms-up / fast-swipe → cast events |
| `sound.py` | Pop + spell-cast sound synthesis and throttled playback |
| `tests/` | Unit tests for the game engine, gestures, and magic effects |

## Tests

```bash
pytest community/apps/pipeline_apps/bubble_pop/tests/ -v
```

## Tips

- Stand 1.5–3 m from the camera so your whole upper body is visible.
- Pops are detected at the **wrists** — swat with open hands for best effect.
- For **SHOCKWAVE**, press your palms together like a clap and hold for a beat.
- For **MAGIC BOLT**, flick your hand fast in the direction you want to shoot.
- Play together! Every person in the frame can pop hearts and cast spells.
