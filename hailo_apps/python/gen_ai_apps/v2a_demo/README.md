# Hailo Voice-to-Action Demo

A voice-controlled AI assistant powered by a Hailo-10H AI accelerator. Speak a command, and the system will identify the right tool, extract parameters, execute it, and speak the results back — all using on-device AI inference.

## Available Tools

| Tool | Description | Example Command |
|------|-------------|-----------------|
| `get_weather` | Weather forecast for a city | "Hey Hailo, what's the weather in London?" |
| `control_led` | Control the board LED (Raspberry Pi only) | "Hey Hailo, blink the LED 5 times" |
| `get_travel_time` | Travel time between locations | "Hey Hailo, how long to drive from London to Manchester?" |
| `data_storage` | Store/retrieve personal info | "Hey Hailo, remember John's phone is 123-456" |
| `system_check` | CPU, RAM, disk, temperature report | "Hey Hailo, run a system check" |
| `explain_tools` | List available capabilities | "Hey Hailo, what can you do?" |

## Prerequisites

- A host with a Hailo-10H AI accelerator
- Microphone and speaker connected
- Python 3.10+
- HailoRT Python package (`hailo-platform`) installed per [Hailo's documentation](https://hailo.ai/developer-zone/)

## Quick Start

```bash
cd v2a_demo
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Set up API keys
# Free API key from https://openweathermap.org/api (required for weather tool)
export OPENWEATHER_API_KEY="your_key_here"

# Run the demo
python main.py
```

### CLI Options

```bash
python main.py                                             # Standard mode
python main.py --audio-device 2                            # Select microphone device
python main.py --wake-word-model resources/hey_hailo.onnx  # Use a different wake word
```

## Adding a New Tool

Adding a tool requires one new file and one line in the registry.

**Step 1.** Create `tools/your_tool.py`:

```python
"""Description of your tool."""

TOOL_PROMPT = (
    "Extract parameters from the user's request as a JSON object.\n"
    "Parameters:\n"
    '- "param1" (required): Description.\n'
    "\n"
    "Examples:\n"
    '"Do something with X" -> {"param1": "X"}\n'
    "\n"
    "Output ONLY the JSON object, nothing else."
)

# Natural language descriptions of what this tool does.
# The tool selector compares the user's speech against these to decide
# which tool to invoke. Write 7-10 diverse phrasings of the same intent.
TOOL_DESCRIPTIONS = [
    "Do something with a given input",
    "Perform an action on X",
    "Can you do something for me?",
    "I want to do something with X",
    "Handle requests to do something",
    "Process a user's request to do X",
    "Execute an action based on user input",
]

def your_tool(param1: str) -> str:
    """Execute the tool. Parameter names must match the JSON keys in TOOL_PROMPT.
    Returns a string that will be spoken back to the user."""
    return f"Done with {param1}."
```

**Step 2.** Register in `tools/__init__.py` — add the import and one line to `_REGISTRY`:

```python
from tools import ..., your_tool

_REGISTRY = {
    ...
    "your_tool": (your_tool, "your_tool"),
}
```

For tools that take no parameters (like `system_check`), set `TOOL_PROMPT` to output `{}` and add the tool name to `NO_PARAM_TOOLS` in `tools/__init__.py`.


## Pipeline Architecture

```
Microphone
    |
    v
[Wake Word Detection]     OpenWakeWord (ONNX, CPU)
    |
    v
[Stage 1 — STT]           Whisper-Base (HEF, Hailo)
    |  text
    v
[Stage 2 — Tool Selection] all-MiniLM-L6-v2 (HEF, Hailo)
    |  tool name
    v
[Stage 3 — LLM]           Qwen2.5-Coder-1.5B-Instruct (HEF, Hailo)
    |  JSON params
    v
[Stage 4 — Tool Execution] Python function call
    |  response text
    v
[Stage 5 — TTS]           Piper TTS (ONNX, CPU)
    |
    v
Speaker
```
