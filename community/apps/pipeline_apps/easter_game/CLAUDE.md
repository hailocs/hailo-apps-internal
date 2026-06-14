# Easter Game

## What This App Does
Interactive Easter-egg and Afikoman catching game built on Hailo pose estimation. Easter eggs (colorful ovals, 20 pts) and Afikoman matzahs (golden rectangles, 10 pts) spawn one at a time at random spots; players catch them with their hands (wrist keypoints). It tracks per-player scores on a leaderboard, runs a 90-second countdown, then shows final scores and auto-restarts.

## Architecture
- **Type:** Pipeline app (interactive pose game)
- **Pattern:** Pose estimation pipeline + Python `app_callback` game logic that draws a custom-background overlay frame
- **Models:** YOLOv8-Pose (COCO 17-keypoint) — inherited from `GStreamerPoseEstimationApp`; HEF resolved by the parent pose pipeline
- **Hardware:** hailo8, hailo8l, hailo10h
- **Postprocess:** Pose postprocess from the pose_estimation pipeline; gesture/catch logic and rendering are pure Python (OpenCV) in the callback

## Key Files
| File | Purpose |
|------|---------|
| `easter_game.py` | Whole app — `EasterEggsGame` (subclasses `GStreamerPoseEstimationApp`), `EasterGameCallback` (game state), `app_callback` (catch detection + rendering), HUD/leaderboard/game-over drawing helpers |

## How to Run
```bash
source setup_env.sh
python community/apps/pipeline_apps/easter_game/easter_game.py --input usb
# with a custom background image:
python community/apps/pipeline_apps/easter_game/easter_game.py --input usb --background /path/to/background.png
```
Without `--background`, the app resolves the bundled `room.png` resource (run `hailo-download-resources` if missing); otherwise it falls back to a dark frame.

## How to Extend
- **Catch tuning:** Adjust the constants at the top of `easter_game.py` — `CATCH_RADIUS`, `ITEM_TIMEOUT`, `EGG_PROBABILITY`, `EGG_POINTS`/`AFIKOMAN_POINTS`, `GAME_DURATION`.
- **New collectibles:** Add a drawing helper like `draw_easter_egg`/`draw_afikoman` and wire it into `spawn_item()` / the render block in `app_callback`.
- **Background rule:** Rendering uses `background.copy()` per frame (never blends the camera feed); keep that pattern when changing visuals.
