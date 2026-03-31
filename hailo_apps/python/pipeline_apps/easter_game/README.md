# Easter Game

An interactive Easter egg and afikoman catching game using Hailo pose estimation.

## How It Works

- A custom background image is displayed
- Easter eggs (colorful ovals, 20 pts) and afikoman matzahs (golden rectangles, 10 pts) appear one at a time at random spots
- Players catch them with their hands (wrist keypoints)
- Eggs appear more often than afikoman
- If missed after 3 seconds, the next item spawns automatically
- "+20" / "+10" pop-ups appear on catch
- Leaderboard on the right side with auto-named players
- 90-second countdown timer at the top
- Game over screen shows final scores, then auto-restarts

## Usage

```bash
python3 easter_eggs_game.py --input usb --background /path/to/background.png
```

## Controls

- Move your hands to catch eggs and afikoman
- Leaderboard and scores are displayed on screen
- Game ends after 90 seconds, shows final scores, and restarts automatically
