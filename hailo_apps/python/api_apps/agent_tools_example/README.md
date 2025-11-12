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
python -m hailo_apps.hailo_app_python.tools.chat_agent
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
- **Real Hardware**: Uses `rpi5-ws2812` library for Raspberry Pi 5 SPI control
- **Simulator**: Flask-based web interface showing LED state in real-time
- **Configuration**: Set `HARDWARE_MODE` in `config.py` to "real" or "simulator"

**Installation for Real Hardware:**
To use the RGB LED tool with real hardware on a Raspberry Pi 5:

1. **Enable SPI** (required): The LED control uses the Serial Peripheral Interface (SPI) port. Enable SPI via:
   ```bash
   sudo raspi-config
   ```
   Navigate to `Interfacing Options` > `SPI` and select `Yes` to enable. Then reboot:
   ```bash
   sudo reboot
   ```

2. **Wiring**: Connect the LED strip's data input (DIN) to the Raspberry Pi's MOSI pin:
   - **GPIO 10** (pin 19 on the header) - This is the SPI MOSI pin
   - Ensure a common ground between the Raspberry Pi and the LED strip
   - Power the LED strip according to its specifications

3. **Install the library**:
   ```bash
   pip install rpi5-ws2812
   ```

**Troubleshooting:**
- **Hardware mode failures**: If `HARDWARE_MODE='real'` is set and hardware initialization fails, the application will exit with an error. Make sure:
  - SPI is enabled via `sudo raspi-config` (Interfacing Options > SPI > Enable) and the system has been rebooted
  - Required libraries are installed (`rpi5-ws2812` for LED, `rpi-hardware-pwm` for servo)
  - The LED strip data line is connected to GPIO 10 (SPI MOSI pin)
  - SPI device is accessible (check with `ls /dev/spidev*`)
- **SPI not enabled**: If you see initialization errors, verify SPI is enabled:
  ```bash
  ls /dev/spidev*
  ```
  You should see `/dev/spidev0.0` (and possibly `/dev/spidev0.1`). If not, enable SPI via `sudo raspi-config` and reboot.
- **Permission errors**: If you see permission errors accessing SPI, you may need to add your user to the `spi` group:
  ```bash
  sudo usermod -a -G spi $USER
  ```
  Then log out and log back in (or reboot).

**Features:**
- Color control by name (e.g., "red", "blue", "green")
- Intensity adjustment (0-100%)
- On/off control

### Servo Tool
Control servo: move to absolute angle or by relative angle (-90 to 90 degrees).

**Hardware Support:**
- **Real Hardware**: Uses `rpi-hardware-pwm` library for hardware PWM control on Raspberry Pi
- **Simulator**: Flask-based web interface with visual servo arm display
- **Configuration**: Set `HARDWARE_MODE` in `config.py` to "real" or "simulator"

**Installation for Real Hardware:**
To use the servo tool with real hardware on a Raspberry Pi:

1. **Enable Hardware PWM**:
   Edit `/boot/firmware/config.txt` (or `/boot/config.txt` on older Raspberry Pi OS versions):
   ```bash
   sudo nano /boot/firmware/config.txt
   ```

   **Disable onboard audio** (if present): The Raspberry Pi's analog audio uses the same PWM channels as hardware PWM, so you need to disable it. Look for this line and comment it out:
   ```
   # dtparam=audio=on
   ```

   **Add the PWM overlay**: Add the following line at the **bottom** of the config file:
   ```
   dtoverlay=pwm-2chan
   ```
   This enables:
   - **PWM Channel 0** → GPIO 18 (default)
   - **PWM Channel 1** → GPIO 19 (default)

   To use GPIO 12 and GPIO 13 instead, use:
   ```
   dtoverlay=pwm-2chan,pin=12,func=4,pin2=13,func2=4
   ```

   **Important**: Place the `dtoverlay` line at the bottom of the config file to ensure proper loading.

   Save the file and reboot:
   ```bash
   sudo reboot
   ```

   After rebooting, verify PWM is enabled:
   ```bash
   ls /sys/class/pwm/
   ```
   You should see `pwmchip0` and `pwmchip1` listed. This confirms hardware PWM is enabled.

   **Verify PWM pin configuration**: Test that GPIO 18 is configured for PWM:
   ```bash
   pinctrl get 18
   ```
   Expected successful output (indicating PWM function is active):
   ```
   18: a3 pd | lo // PIN12/GPIO18 = PWM0_CHAN2
   ```
   If the overlay loaded correctly, the output should show a function other than `input` or `output` (like `PWM0_CHAN2` in the example above).

2. **Install the library**:
   ```bash
   pip install rpi-hardware-pwm
   ```

3. **Wiring**: Connect the servo motor to the Raspberry Pi:
   - **Control Signal (Orange/Yellow wire)**: Connect to **GPIO 18** (pin 12 on the header) for PWM channel 0, or **GPIO 19** (pin 35) for PWM channel 1
   - **Power (Red wire)**: Connect to **5V** (pin 2 or 4) - **IMPORTANT**: Use external power supply for servos
   - **Ground (Brown/Black wire)**: Connect to **GND** (pin 6, 9, 14, 20, 25, 30, 34, or 39)

   **⚠️ Power Warning**: Standard servos can draw significant current (often 1-2A or more). Do NOT power the servo directly from the Raspberry Pi's 5V pin without an external power supply, as this can damage the Pi or cause instability. Use one of these approaches:
   - **Recommended**: Use a separate 5V power supply for the servo, with common ground shared between the Pi and servo power supply
   - **Alternative**: Use a servo driver board (like PCA9685) that provides external power management
   - **For small servos only**: If using a very small, low-current servo (< 500mA), you may power from Pi's 5V, but monitor for stability issues

4. **Servo Specifications**:
   - Works with standard PWM servos (e.g., SG90, MG90S, etc.)
   - Default angle range: -90° to +90° (configurable in `config.py`)
   - Control signal: 50Hz hardware PWM (standard servo frequency)
   - Uses hardware PWM for precise, jitter-free control

**Troubleshooting:**
- **Hardware mode failures**: If `HARDWARE_MODE='real'` is set and hardware initialization fails, the application will exit with an error. Make sure:
  - Hardware PWM is enabled in `/boot/firmware/config.txt` (see step 1)
  - The system has been rebooted after enabling PWM
  - Required library is installed (`rpi-hardware-pwm`)
  - The servo control signal is connected to the correct GPIO pin (GPIO 18 for channel 0, GPIO 19 for channel 1)
  - The servo is properly powered (external power supply recommended)
- **Servo not moving**: Check:
  - Wiring connections (signal, power, ground)
  - Power supply voltage (should be 5V for most servos)
  - Power supply current capacity (servos need adequate current)
  - Verify PWM is enabled: `ls /sys/class/pwm/` should show `pwmchip0` and `pwmchip1`
  - Verify servo works with a simple test script
- **Jittery or unstable movement**: This often indicates:
  - Insufficient power supply current
  - Poor ground connection
  - Electrical noise - try adding a capacitor (100-1000µF) across servo power and ground
  - Servo may be damaged or incompatible
  - Hardware PWM should eliminate jitter - if jitter persists, check power supply and wiring

**Features:**
- Absolute positioning (-90° to 90°)
- Relative movement
- Automatic angle clamping

### Hardware Configuration

Edit `config.py` to customize hardware settings:

```python
HARDWARE_MODE = "simulator"  # "real" or "simulator"
# SPI configuration for NeoPixel (Raspberry Pi 5)
NEOPIXEL_SPI_BUS = 0  # SPI bus number (0 = /dev/spidev0.x)
NEOPIXEL_SPI_DEVICE = 0  # SPI device number (0 = /dev/spidev0.0)
NEOPIXEL_COUNT = 1  # Number of LEDs in strip
# Servo configuration
SERVO_PWM_CHANNEL = 0  # Hardware PWM channel (0 or 1). Channel 0 = GPIO 18, Channel 1 = GPIO 19
SERVO_MIN_ANGLE = -90.0  # Minimum servo angle in degrees
SERVO_MAX_ANGLE = 90.0  # Maximum servo angle in degrees
FLASK_PORT = 5000  # Port for LED simulator web server
SERVO_SIMULATOR_PORT = 5001  # Port for servo simulator web server
```

**Notes**:
- **SPI**: Uses the MOSI pin (GPIO 10) automatically - no pin configuration needed. The SPI bus and device numbers correspond to `/dev/spidev0.0` by default.
- **Servo**: Default GPIO pin is 17 (physical pin 11). Ensure the servo is properly powered with an external power supply for reliable operation.

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
