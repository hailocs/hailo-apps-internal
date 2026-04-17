# Voice Mouse Controller

Voice-controlled mouse agent for Hailo-10H. Speak natural language commands into your microphone and the agent will move, click, scroll, and drag the mouse cursor.

## Architecture

1. **Whisper STT** (on Hailo-10H) captures voice and transcribes to text
2. **LLM** (on Hailo-10H) interprets the text and generates tool calls
3. **pyautogui** executes mouse actions on the local display
4. Terminal prints what was heard and what action was taken
5. Loops back to listening

## Requirements

- Hailo-10H accelerator
- Microphone (USB or built-in)
- X11 display server (for pyautogui)
- Python packages: `pyautogui`

```bash
pip install pyautogui
```

## Usage

```bash
# Basic usage
./run.sh

# With VAD for better speech detection
./run.sh --vad

# Debug mode (shows raw LLM output)
./run.sh --debug

# Or run directly
python3 -m hailo_apps.python.gen_ai_apps.voice_mouse_agent.voice_mouse_agent
```

## Voice Commands

| Command | Action |
|---------|--------|
| "move left 200 pixels" | Move cursor left 200px |
| "move up" | Move cursor up 100px (default) |
| "click" | Left click |
| "right click" | Right click |
| "double click" | Double click |
| "scroll down" | Scroll down 3 units |
| "scroll up 5" | Scroll up 5 units |
| "drag right 300 pixels" | Click and drag right 300px |
| "move to position 500 300" | Move to absolute (500, 300) |

## Safety

- Press **Ctrl+C** to quit
- pyautogui failsafe: move mouse to any screen corner to abort
- No TTS output (silent operation, terminal feedback only)

## Tool: mouse_control

Single tool with an `action` parameter that selects the operation:

- `move` - Relative movement (direction + pixels)
- `move_to` - Absolute positioning (x, y)
- `left_click` - Left click at current position
- `right_click` - Right click at current position
- `double_click` - Double click at current position
- `scroll` - Scroll wheel (direction + amount)
- `drag` - Click and drag (direction + pixels)
