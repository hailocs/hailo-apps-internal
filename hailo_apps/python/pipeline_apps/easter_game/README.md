# Easter Game

![Easter Game Example](../../../../doc/images/easter_game.gif)

An interactive Easter Egg and Afikoman catching game using Hailo pose estimation.

## How It Works

- A custom background image is displayed
- Easter eggs (colorful ovals, 20 pts) and Afikoman matzahs (golden rectangles, 10 pts) appear one at a time at random spots
- Players catch them with their hands (wrist keypoints)
- Eggs appear more often than Afikoman
- If missed after 3 seconds, the next item spawns automatically
- "+20" / "+10" pop-ups appear on catch
- Leaderboard on the right side with auto-named players
- 90-second countdown timer at the top
- Game over screen shows final scores, then auto-restarts

## Usage

```bash
python3 easter_game.py --input usb

or:

python3 easter_game.py --input usb --background /path/to/background.png
```

## Controls

- Move your hands to catch eggs and Afikoman
- Leaderboard and scores are displayed on screen
- Game ends after 90 seconds, shows final scores, and restarts automatically

## This app was autonomously generated using the HL App Builder custom agent with the following prompt:

Build Easter game:

Easter eggs (colorful ovals, 20 pts) and Afikoman matzahs (golden rectangles, 10 pts) appear one at a time at random spots. 

Players catch them with their hands. 

Missed after 3 seconds - next one spawns. 

Eggs appear more often than Afikoman.

Background: /home/michaelf/room.png. 

Leaderboard on the right - auto-name new players. 

Show "+20"/"+10" pop-ups on catch.

90-second countdown timer at top. 

Game over - show final scores, then auto-restart.
