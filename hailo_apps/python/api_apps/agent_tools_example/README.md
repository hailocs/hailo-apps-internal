# Hailo LLM Tools - Interactive Chat Agent

Interactive CLI chat agent that uses Hailo LLM models with function calling capabilities. The agent automatically discovers tools and allows the LLM to call them during conversations.

## Overview

The tools application provides an interactive CLI chat agent that uses Hailo LLM models with function calling capabilities. The system automatically discovers tools from modules named `tool_*.py` and allows the LLM to call them during conversations.

### Architecture

The system follows a simple tool discovery and execution pattern:

1. **Tool Discovery**: Tools are automatically discovered from modules following the naming pattern `tool_*.py`
2. **Tool Call Flow**: User input → LLM (with tools) → Tool execution (if needed) → Final response
3. **Context Management**: Uses token-based context management (clears at 80% capacity) for optimal performance

## Quick Start

### Basic Usage

```bash
python -m hailo_apps.hailo_app_python.tools.chat_agent
```

### With Debug Logging

To enable debug logging, edit `config.py` and set:
```python
DEFAULT_LOG_LEVEL = "DEBUG"
```

### With Custom Model

```bash
HAILO_HEF_PATH=/path/to/model.hef python -m hailo_apps.hailo_app_python.tools.chat_agent
```

## Interactive Commands

Once in the chat, you can use these commands:

| Command    | Description                |
| ---------- | -------------------------- |
| `/exit`    | Exit the chat              |
| `/clear`   | Clear conversation context |
| `/context` | Show context token usage   |

## Available Tools

The system automatically discovers tools from modules named `tool_*.py`. Current tools include:

### Math Tool
Perform basic arithmetic operations: addition, subtraction, multiplication, and division. The LLM must use this tool for all calculations - it never performs math directly.

### Weather Tool
Get current weather and rain forecasts for any location worldwide using the Open-Meteo API (no API key required).

**Features:**
- Current weather conditions
- Multi-day forecasts (up to 16 days)
- Hourly forecasts (up to 7 days)
- Precipitation data
- Timezone-aware responses

**Usage:** The tool uses a `future_days` parameter (0=today, 1=tomorrow, etc.) instead of absolute dates, making it easier for the LLM to use.

### Shell Tool (Read-Only)
Run safe read-only Linux commands within the repository. Only whitelisted commands are allowed (e.g., `ls`, `cat`, `grep`, `head`, `tail`).

### RGB LED Tool
Control RGB LED: turn on/off, change color by name, adjust intensity (0-100%).

**Hardware Support:**
- **Real Hardware**: Uses `rpi-ws281x` library for Raspberry Pi GPIO control
- **Simulator**: Flask-based web interface showing LED state in real-time
- **Configuration**: Set `HARDWARE_MODE` in `config.py` to "real" or "simulator"

**Features:**
- Color control by name (e.g., "red", "blue", "green")
- Intensity adjustment (0-100%)
- On/off control

### Servo Tool
Control servo: move to absolute angle or by relative angle (-90 to 90 degrees).

**Hardware Support:**
- **Real Hardware**: Uses `gpiozero` library for Raspberry Pi GPIO control
- **Simulator**: Flask-based web interface with visual servo arm display
- **Configuration**: Set `HARDWARE_MODE` in `config.py` to "real" or "simulator"

**Features:**
- Absolute positioning (-90° to 90°)
- Relative movement
- Automatic angle clamping

### Hardware Configuration

Edit `config.py` to customize hardware settings:

```python
HARDWARE_MODE = "simulator"  # "real" or "simulator"
NEOPIXEL_PIN = 18  # GPIO pin for NeoPixel data line
SERVO_PIN = 17  # GPIO pin for servo control signal
FLASK_PORT = 5000  # Port for LED simulator web server
SERVO_SIMULATOR_PORT = 5001  # Port for servo simulator web server
```

## Example Session

```
Available tools:
  1. math: Perform basic arithmetic operations: addition, subtraction, multiplication, and division.
  2. shell_readonly: Run whitelisted read-only shell commands (ls, cat, grep, etc.) inside the repository.
  3. weather: Get current weather and rain forecasts (supports future days) using the Open-Meteo API.

Select a tool by number (or 'q' to quit): 1

Selected tool: math
Loading model...

Chat started. Type '/exit' to quit. Use '/clear' to reset context. Type '/context' to show stats.
Tool in use: math

You: what is 5 times 3?
Assistant: 15.0

You: calculate 314 divided by 3
Assistant: 104.66666666666667

You: /exit
Bye.
```

## Tips for Using Tools

To encourage the LLM to use a specific tool, it's helpful to mention the tool explicitly in your request. For example:

- ✅ **Better**: "Turn on the lights using the LED tool"
- ✅ **Better**: "Use the LED tool to set the color to red"
- ❌ **Less reliable**: "Turn on the lights" (LLM might not realize it should use the tool)

The LLM is more likely to call a tool when you:
1. Mention the tool name explicitly (e.g., "LED tool", "math tool", "weather tool")
2. Use action words that match the tool's purpose (e.g., "calculate", "get weather", "turn on")
3. Provide clear parameters (e.g., "set LED to red at 50% brightness")

## Creating New Tools

Tools are automatically discovered - just create a new file following the pattern:

### Step 1: Copy Template

```bash
cp tool_TEMPLATE.py tool_mytool.py
```

### Step 2: Implement Tool Interface

Each tool must expose:

1. **`name: str`** - Unique tool identifier
2. **`description: str`** - Clear instructions for the LLM on when/how to use (this is critical!)
3. **`schema: dict`** - JSON schema following OpenAI function calling format
4. **`TOOLS_SCHEMA: list[dict]`** - List containing function definition
5. **`run(input: dict) -> dict`** - Tool execution function

### Tool Description Best Practices

The `description` field is where tool-specific instructions belong. Be explicit and clear:

✅ **Good Example:**
```python
description: str = (
    "CRITICAL: You MUST use this tool for ALL arithmetic operations. "
    "NEVER calculate math directly - ALWAYS call this tool. "
    "The function name is 'math' (use this exact name in tool calls). "
    "Supported operations: add (+), sub (-), mul (*), div (/). "
    "The 'op' parameter specifies which operation: 'add', 'sub', 'mul', or 'div'."
)
```

### Schema Best Practices

- Follow OpenAI function calling format
- **DO NOT use**: `default`, `minimum`, `maximum`, `minItems`, `maxItems`, `additionalProperties`
- Include clear parameter descriptions
- Specify required vs optional parameters using `required` array
- Use appropriate types (`string`, `number`, `array`, `object`)

### Tool Return Format

The `run()` function must return a dictionary with:

```python
{
    "ok": bool,      # Success status
    "result": Any,    # Success result (if ok=True)
    "error": str     # Error message (if ok=False)
}
```

### Step 3: Test

The tool will be automatically discovered when you run the agent. No code changes needed in the agent!

## Troubleshooting

### Tools Not Being Called

1. **Check tool description**: Ensure it clearly instructs when to use the tool with explicit language like "CRITICAL:", "MUST", or "ALWAYS"
2. **Enable debug logging**: Set `DEFAULT_LOG_LEVEL = "DEBUG"` in `config.py` to see full LLM responses
3. **Verify tool schema**: Ensure parameters are clearly described
4. **Check function name**: Ensure description explicitly states the function name

### Common Issues

- **Model doesn't call tools**: Tool descriptions may be unclear or too vague. Use explicit imperative language.
- **Parsing errors**: Ensure JSON format is correct (double quotes, no single quotes)
- **Tool execution fails**: Check tool's `run()` function error handling
- **Wrong function name**: Model may use operation names instead of tool name - add explicit function name in description

### Context Management

The agent uses token-based context management (clears at 80% capacity) instead of message counting. This provides:
- Accurate tracking based on actual token usage
- Maximized context utilization
- Automatic adaptation to different model capacities

Use `/context` command to view current token usage.

## References
- **[AGENTS.md](./AGENTS.md)** - Detailed developer documentation and architecture guide
- **Qwen 2.5 Coder Tool Calling** - Colab notebook with hands-on walkthrough ([link](https://colab.research.google.com/github/unslothai/notebooks/blob/main/nb/Qwen2.5_Coder_(1.5B)-Tool_Calling.ipynb))
- **OpenAI Function Calling Guide** - Official reference on defining functions ([link](https://platform.openai.com/docs/guides/function-calling?api-mode=chat#defining-functions))
