# Agents Architecture & Developer Guide

This document provides comprehensive technical documentation for the Hailo LLM function calling system architecture and implementation details.

---

## Overview

The tools application provides an interactive CLI chat agent (`chat_agent.py`) that uses Hailo LLM models with function calling capabilities. The system automatically discovers tools from modules named `tool_*.py` and allows the LLM to call them during conversations.

### Key Components

- **`chat_agent.py`** - Main interactive CLI agent (text-based entry point)
- **`voice_chat_agent.py`** - Voice-enabled interactive agent (combines voice I/O with tool calling)
- **`tool_*.py`** - Individual tool modules (discovered automatically)

---

## Architecture

### Tool Discovery

Tools are automatically discovered from modules in the `tools/` directory that follow the naming pattern `tool_*.py`. Each tool must expose:

- `name: str` - Unique tool identifier
- `description: str` - Tool description (includes usage instructions)
- `schema: dict` - JSON schema defining tool parameters
- `run(input: dict) -> dict` - Tool execution function

### Tool Call Flow

```
User Input
    ↓
LLM (with system prompt + tools)
    ↓
Parse Response → Tool Call?
    ├─ No → Display response directly
    └─ Yes → Execute tool
                ↓
        Tool Result → LLM (generate final response)
                ↓
        Display final response
```

### System Prompt Design

The system prompt is intentionally **simple and general**:

- **General instructions only**: How to format tool calls (XML tags, JSON format)
- **No tool-specific guidance**: Tool-specific instructions live in each tool's `description` field

This separation ensures:
- Tool-specific usage instructions are maintained with the tool code
- System prompt remains clean and focused
- Easier to add/remove tools without modifying the agent

#### System Prompt Best Practices

**Avoid Emojis in System Prompts:**

For technical applications like this Hailo LLM system, system prompts should be clear, direct, and unambiguous. Emojis should be avoided for the following reasons:

- **Potential for Misinterpretation**: LLMs may misinterpret emojis or they may not add semantic value that clear text cannot convey
- **Reduced Clarity**: System prompts should be concise and professional. Emojis can clutter instructions and make them less straightforward for the model to parse
- **Token Efficiency**: Emojis consume tokens unnecessarily. For high-efficiency applications, every token should add value

**Recommended Approach:**

1. **Use clear, imperative language**: State instructions explicitly (e.g., "ALWAYS respond in JSON format", "DO NOT provide explanations unless asked")
2. **Use standard formatting**: Use text formatting like bolding (`**text**`), new lines, and clear section headers to organize instructions
3. **Define constraints explicitly**: State what the model must and must not do without relying on visual cues

**Exception**: Emojis might be acceptable only in very niche cases where the entire purpose is to define a specific casual/playful persona, which is not applicable for technical tools.

### Qwen 2.5 Coder Tool Invocation Format

The implementation follows Qwen 2.5 Coder's tool calling format:

- **Tool definitions**: Wrapped in `<tools></tools>` XML tags
- **Tool calls**: Wrapped in `<tool_call></tool_call>` XML tags
- **Tool responses**: Wrapped in `<tool_response></tool_response>` XML tags
- **Schema format**: OpenAI function calling format (no `default`, `minimum`, `additionalProperties`)

---

## Tool Format

### Tool Module Structure

Every tool follows this interface:

```python
# tool_mytool.py
from typing import Any

name: str = "mytool"
description: str = (
    "CRITICAL: Tool-specific usage instructions go here. "
    "What this tool does and when to use it. "
    "This is where you tell the LLM how and when to call this tool."
)

schema: dict[str, Any] = {
    "type": "object",
    "properties": {
        "param1": {
            "type": "string",
            "description": "Parameter description"
        }
    },
    "required": ["param1"]
}

TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": schema,
        },
    }
]

def run(input: dict[str, Any]) -> dict[str, Any]:
    """
    Execute the tool logic.

    Args:
        input: Tool input parameters

    Returns:
        Dictionary with:
        - ok: bool - Success status
        - result: Any - Success result (if ok=True)
        - error: str - Error message (if ok=False)
    """
    # Tool logic here
    return {"ok": True, "result": "..."}
```

### Tool Description Best Practices

The `description` field is where tool-specific instructions belong:

✅ **Good** (from `tool_math.py`):
```python
description: str = (
    "CRITICAL: You MUST use this tool for ALL arithmetic operations. "
    "NEVER calculate math directly - ALWAYS call this tool. "
    "The function name is 'math' (use this exact name in tool calls). "
    "Supported operations: add (+), sub (-), mul (*), div (/). "
    "The 'op' parameter specifies which operation: 'add', 'sub', 'mul', or 'div'."
)
```

**Note**: Avoid emojis in tool descriptions as well for consistency and clarity. Use clear text like "CRITICAL:", "IMPORTANT:", or "MUST" to emphasize important instructions.

❌ **Bad**: Leaving tool-specific instructions in the system prompt

### Schema Best Practices

- Follow OpenAI function calling format
- **DO NOT use**: `default`, `minimum`, `maximum`, `minItems`, `maxItems`, `additionalProperties`
- Include clear parameter descriptions
- Specify required vs optional parameters using `required` array
- Use appropriate types (`string`, `number`, `array`, `object`)
- Add examples in descriptions when helpful

---

## Creating New Tools

### Step 1: Copy Template

```bash
cp tool_TEMPLATE.py tool_mytool.py
```

### Step 2: Implement Tool Interface

1. Set `name` - unique tool identifier
2. Set `description` - clear instructions for the LLM on when/how to use
3. Define `schema` - JSON schema following OpenAI format
4. Create `TOOLS_SCHEMA` - list containing function definition
5. Implement `run()` function

### Step 3: Test

The tool will be automatically discovered when you run `chat_agent.py`. No code changes needed in the agent!

---

## Usage

### Running the Chat Agent (Text-Based)

```bash
# Basic usage
python -m hailo_apps.python.standalone_apps.agent_tools_example.chat_agent

# With debug logging (edit config.py: DEFAULT_LOG_LEVEL = "DEBUG")
python -m hailo_apps.python.standalone_apps.agent_tools_example.chat_agent

# With custom model
HAILO_HEF_PATH=/path/to/model.hef python -m hailo_apps.python.standalone_apps.agent_tools_example.chat_agent
```

### Running the Voice Chat Agent

**Prerequisites**: The voice chat agent requires Piper TTS model installation. See [Voice Processing Module Documentation](../../core/gen_ai_utils/voice_processing/README.md) for installation instructions.

```bash
# Basic usage
python -m hailo_apps.python.standalone_apps.agent_tools_example.voice_chat_agent

# With debug logging
python -m hailo_apps.python.standalone_apps.agent_tools_example.voice_chat_agent --debug

# Without TTS (voice input only)
python -m hailo_apps.python.standalone_apps.agent_tools_example.voice_chat_agent --no-tts

# With custom model
HAILO_HEF_PATH=/path/to/model.hef python -m hailo_apps.python.standalone_apps.agent_tools_example.voice_chat_agent
```

**Voice Controls:**

| Key     | Action                     |
| ------- | -------------------------- |
| `SPACE` | Start/stop recording       |
| `Q`     | Quit the application       |
| `C`     | Clear conversation context |

The voice chat agent:
- Uses Hailo's Whisper model for speech-to-text
- Processes queries through the LLM with tool calling
- Synthesizes responses using Piper TTS
- Supports all the same tools as the text-based agent

### Interactive Commands (Text Agent)

| Command    | Description                |
| ---------- | -------------------------- |
| `/exit`    | Exit the chat              |
| `/clear`   | Clear conversation context |
| `/context` | Show context token usage   |

---

## Troubleshooting

### Tools Not Being Called

1. **Check tool description**: Ensure it clearly instructs when to use the tool
2. **Check system prompt**: Should be simple and general
3. **Enable debug logging**: Set `DEFAULT_LOG_LEVEL = "DEBUG"` in `config.py` to see full LLM responses
4. **Verify tool schema**: Ensure parameters are clearly described
5. **Check function name**: Ensure description explicitly states the function name

### Common Issues

- **Model doesn't call tools**: Tool descriptions may be unclear or system prompt too verbose
- **Parsing errors**: Ensure JSON format is correct (double quotes, no single quotes)
- **Tool execution fails**: Check tool's `run()` function error handling
- **Wrong function name**: Model may use operation names instead of tool name - add explicit function name in description

---

## Debugging & Best Practices

### Debugging Tool Calls

When a tool isn't working as expected, follow this process:

1.  **Enable Debug Logging**:
    Set `DEFAULT_LOG_LEVEL = "DEBUG"` in `config.py` or use `--debug` flag.
    This reveals:
    - The raw system prompt being sent
    - The raw LLM response (including XML tags)
    - Exact tool arguments parsed
    - Execution tracebacks

2.  **Inspect the Raw Response**:
    Look for `<tool_call>` tags in the logs.
    - **Missing tags?** The model didn't decide to call the tool. Fix: Strengthen the tool `description`.
    - **Malformed tags?** The model tried but failed syntax. Fix: Check system prompt format instructions.
    - **Wrong arguments?** The model called it but with bad data. Fix: Improve parameter descriptions in `schema`.

3.  **Test in Isolation**:
    Create a small script to import your tool module and call `run()` directly with test inputs to verify logic independent of the LLM.

### Common Patterns

#### 1. The "Router" Pattern
For tools with multiple sub-functions (like `math`), use a single tool with an `operation` parameter rather than many small tools.
- **Why**: Reduces context usage and simplifies tool selection for the LLM.
- **Example**: `math` tool with `op="add"` vs `add_tool`, `sub_tool`.

#### 2. The "Hardware State" Pattern
Hardware tools (LED, Servo) should be stateless in the `run()` function but maintain state in a controller singleton.
- **Why**: LLM calls are stateless; the hardware controller persists the physical state.
- **Example**: `_led_controller` global in `tool_rgb_led.py`.

#### 3. The "Fuzzy Match" Pattern
Don't force the LLM to be perfect with string enums if possible. Handle case-insensitivity and common variations in your tool code.
- **Why**: LLMs are probabilistic. `color="Red"` and `color="red"` should both work.
- **Example**: `tool_rgb_led.py` normalizes color names to lowercase.

### Troubleshooting Checklist

- [ ] **Name Check**: Does `tool_*.py` filename match the pattern?
- [ ] **Schema Check**: Is `TOOLS_SCHEMA` defined and valid JSON schema?
- [ ] **Description Check**: Does `description` start with "CRITICAL:" or strong imperative?
- [ ] **Type Hints**: Are input parameters typed correctly in `schema` (e.g., `number` vs `string`)?
- [ ] **Return Value**: Does `run()` return a dictionary with `ok` and `result`/`error`?
- [ ] **Imports**: Does the tool import its dependencies safely (inside functions or try/except)?

### Performance Tips

1.  **Context Caching**: The agent caches the system prompt context. If you change a tool description, delete the `.cache` files to force a refresh.
2.  **Lazy Imports**: Import heavy libraries (like pandas or numpy) inside the `run()` function or in a `try/except` block to keep startup fast.
3.  **Short Outputs**: Keep tool return values concise. Long outputs fill up the context window quickly. If a tool returns huge data, summarize it before returning.

---

## Implementation Details

### Context Management

The agent uses **token-based context management** instead of message counting:

```python
def _check_and_trim_context(llm: LLM) -> bool:
    """Check if context needs trimming using actual token usage."""
    max_capacity = llm.max_context_capacity()
    current_usage = llm.get_context_usage_size()
    threshold = int(max_capacity * 0.80)  # Clear at 80%

    if current_usage < threshold:
        return False

    llm.clear_context()
    return True
```

**Benefits**:
- Accurate tracking based on actual token usage
- Maximizes context utilization (80% threshold)
- Adapts to different model capacities automatically

### Streaming Text Filter

The agent includes a `StreamingTextFilter` class that filters XML tags and special tokens on-the-fly during streaming:

- Removes `<|im_end|>` tokens
- Extracts text from `<text>...</text>` tags
- Suppresses `<tool_call>...</tool_call>` content (parsed separately)
- Maintains state to handle partial tags across token boundaries

### Tool Response Format

Tool results are wrapped in `<tool_response>` XML tags for Qwen 2.5 Coder:

```python
tool_result_text = json.dumps(result, ensure_ascii=False)
tool_response_message = f"<tool_response>{tool_result_text}</tool_response>"
```

The LLM maintains context internally, so only the tool response needs to be sent as a new message.

---

## Reference

- **`tool_TEMPLATE.py`** - Template for creating new tools
- **Colab Notebook: Qwen2.5 Coder Tool Calling** – Hands-on walkthrough of tool invocation patterns ([link](https://colab.research.google.com/github/unslothai/notebooks/blob/main/nb/Qwen2.5_Coder_(1.5B)-Tool_Calling.ipynb))
- **OpenAI Function Calling Guide** – Official reference on defining functions for tool calls ([link](https://platform.openai.com/docs/guides/function-calling?api-mode=chat#defining-functions))

---

## Design Principles

1. **Separation of Concerns**: Tool-specific instructions in tool files, general instructions in agent
2. **Automatic Discovery**: Tools are auto-discovered, no manual registration needed
3. **Simple Prompts**: Keep system prompts simple and focused
4. **Consistent Interface**: All tools follow the same interface pattern
5. **Token-Based Context**: Use actual token counts instead of message counting
6. **Qwen 2.5 Coder Compatibility**: Follow Qwen's tool calling format exactly

---

## Weather Tool Details

### Open-Meteo API

The weather tool uses the free Open-Meteo API (no API key required):
- **Base URL**: `https://api.open-meteo.com/v1/forecast`
- **Geocoding**: `https://geocoding-api.open-meteo.com/v1/search`
- **Supports**: Current weather, daily forecasts (up to 16 days), hourly forecasts (up to 7 days)

### Future Days Parameter

The tool uses a `future_days` parameter (integer, 0=today, 1=tomorrow, etc.) instead of absolute dates. This simplifies LLM usage:
- LLM calculates relative days from "today"
- Tool handles date calculations internally
- Default: 0 (current weather)

### API Features

- Multi-day forecasts supported
- Precipitation data available
- Timezone-aware responses
- No API key required

---

## Hardware Tool Details

### RGB LED Tool

The RGB LED tool supports both real hardware (Adafruit NeoPixel) and browser-based simulation:

- **Real Hardware**: Uses `rpi-ws281x` library for Raspberry Pi GPIO control
- **Simulator**: Flask-based web interface showing LED state in real-time
- **Configuration**: Set `HARDWARE_MODE` in `config.py` to "real" or "simulator"
- **Features**: Color control by name, intensity adjustment (0-100%), on/off control

### Servo Tool

The servo tool supports both real hardware (hardware PWM) and browser-based simulation:

- **Real Hardware**: Uses `rpi-hardware-pwm` library for hardware PWM control on Raspberry Pi
- **Simulator**: Flask-based web interface with visual servo arm display
- **Configuration**: Set `HARDWARE_MODE` in `config.py` to "real" or "simulator"
- **Features**: Absolute positioning (-90° to 90°), relative movement, angle clamping

### Hardware Configuration

Edit `config.py` to customize hardware settings:

```python
HARDWARE_MODE = "simulator"  # "real" or "simulator"
NEOPIXEL_PIN = 18  # GPIO pin for NeoPixel data line
SERVO_PIN = 17  # GPIO pin for servo control signal
FLASK_PORT = 5000  # Port for LED simulator web server
SERVO_SIMULATOR_PORT = 5001  # Port for servo simulator web server
```

---

## Testing

All tools are tested and verified:
- ✅ Math tool: All operations (add, sub, mul, div)
- ✅ Weather tool: Current weather and forecasts
- ✅ RGB LED tool: Color control, intensity, on/off (simulator and hardware)
- ✅ Servo tool: Absolute and relative positioning (simulator and hardware)
