"""
RGB LED control tool.

Supports turning LED on/off, changing color by name, and adjusting intensity.
The tool handles color name to RGB conversion internally, leaving natural language
understanding to the LLM.
"""

from __future__ import annotations

from typing import Any

# Make imports more robust
try:
    # Try relative import first
    from .hardware_interface import create_led_controller
    from . import config
except ImportError:
    # Fallback to absolute import if relative fails
    from hardware_interface import create_led_controller
    import config

name: str = "rgb_led"

# User-facing description (shown in CLI tool list)
display_description: str = (
    "Control RGB LED: turn on/off, change color by name, and adjust intensity (0-100%)."
)

# LLM instruction description (includes warnings for model)
description: str = (
    "CRITICAL: You MUST use this tool when the user asks to control, change, or do anything with an LED or lights. "
    "ALWAYS call this tool if the user mentions: LED, light, lights, turn on, turn off, change color, set color, brightness, intensity, dim, brighten, make it red/blue/green/etc. "
    "NEVER respond about LED control without calling this tool - ALWAYS use this tool for ANY LED or light-related request. Also if the context is implied from the previous message, call this tool."
    "The function name is 'rgb_led' (use this exact name in tool calls). "
    "The tool accepts color names (e.g., 'red', 'blue', 'green', 'yellow', 'purple', 'cyan', 'white', 'orange', 'pink') - "
    "DO NOT use RGB values or hex codes. "
    "Intensity must be a percentage (0-100). "
    "Examples: 'turn on red LED at 50%' → action='on', color='red', intensity=50. "
    "Examples: 'turn off LED' → action='off'. "
    "Examples: 'set LED to blue' → action='on', color='blue'. "
    "Examples: 'make LED brighter at 80%' → action='on', intensity=80. "
    "Examples: 'change the lights to green' → action='on', color='green'. "
    "Examples: 'dim the LED to 30%' → action='on', intensity=30."
)

# Color name to RGB mapping (common colors)
COLOR_MAP: dict[str, tuple[int, int, int]] = {
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "yellow": (255, 255, 0),
    "purple": (128, 0, 128),
    "cyan": (0, 255, 255),
    "white": (255, 255, 255),
    "orange": (255, 165, 0),
    "pink": (255, 192, 203),
    "magenta": (255, 0, 255),
    "lime": (0, 255, 0),
    "teal": (0, 128, 128),
    "navy": (0, 0, 128),
    "maroon": (128, 0, 0),
    "olive": (128, 128, 0),
    "aqua": (0, 255, 255),
    "black": (0, 0, 0),
}

# Initialize LED controller (hardware or simulator) only when tool is selected
_led_controller = None
_initialized = False


def initialize_tool() -> None:
    """
    Initialize LED controller when tool is selected.

    This function is called by chat_agent.py after the tool is selected.
    """
    global _led_controller, _initialized
    if not _initialized:
        try:
            _led_controller = create_led_controller()
            # Set default state: on with white color
            _led_controller.set_color(255, 255, 255, color_name="white")
            _led_controller.set_intensity(100.0)
            _led_controller.on()
            _initialized = True

            # Print instructions if simulator mode
            if config.HARDWARE_MODE.lower() == "simulator":
                simulator_url = f"http://127.0.0.1:{config.FLASK_PORT}"
                print(f"\n[LED Simulator] Open your browser and navigate to: {simulator_url}")
                print("[LED Simulator] The simulator will show the LED state in real-time.\n", flush=True)

        except Exception as e:
            import logging
            import traceback
            logger = logging.getLogger(__name__)
            logger.error("Failed to initialize LED controller: %s", e)
            logger.debug("Traceback: %s", traceback.format_exc())
            print(f"[LED] Warning: LED controller initialization failed: {e}", flush=True)
            # Don't raise - allow tool to work without hardware/simulator
            _initialized = True  # Mark as attempted to avoid retrying


def _get_led_controller() -> Any:
    """Get LED controller instance, initializing if needed (fallback)."""
    if not _initialized:
        initialize_tool()
    return _led_controller


def cleanup_tool() -> None:
    """Clean up LED controller resources."""
    global _led_controller
    if _led_controller is not None and hasattr(_led_controller, "cleanup"):
        try:
            _led_controller.cleanup()
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.debug("Error during LED controller cleanup: %s", e)


# Minimal JSON-like schema to assist prompting/validation
schema: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["on", "off"],
            "description": (
                "Action to perform: 'on' to turn LED on, 'off' to turn LED off. "
                "When 'on' is used, color and intensity parameters are applied if provided."
            ),
        },
        "color": {
            "type": "string",
            "description": (
                "Color name (case-insensitive). Examples: 'red', 'blue', 'green', 'yellow', 'purple', "
                "'cyan', 'white', 'orange', 'pink', 'magenta', 'lime', 'teal', 'navy'. "
                "DO NOT use RGB values or hex codes - only color names."
            ),
        },
        "intensity": {
            "type": "number",
            "description": (
                "Brightness intensity as percentage (0-100). "
                "Examples: 0 (off), 50 (half brightness), 100 (full brightness)."
            ),
        },
    },
    "required": ["action"],
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


def _color_name_to_rgb(color_name: str) -> tuple[int, int, int] | None:
    """
    Convert color name to RGB values.

    Args:
        color_name: Color name (case-insensitive)

    Returns:
        RGB tuple (r, g, b) with values 0-255, or None if color not recognized
    """
    color_lower = color_name.strip().lower()
    return COLOR_MAP.get(color_lower)


def _validate_input(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Validate input parameters.

    Args:
        payload: Input dictionary

    Returns:
        Dictionary with 'ok' and 'data' (if successful) or 'error' (if failed)
    """
    try:
        from pydantic import BaseModel, Field, field_validator

        class RGBLEDInput(BaseModel):
            action: str = Field(description="Action: on or off")
            color: str | None = Field(default=None, description="Color name")
            intensity: float | None = Field(default=None, description="Intensity percentage (0-100)")

            @field_validator("action")
            @classmethod
            def _action_valid(cls, v: str) -> str:
                valid_actions = {"on", "off"}
                if v not in valid_actions:
                    raise ValueError(f"action must be one of: {', '.join(sorted(valid_actions))}")
                return v

            @field_validator("color")
            @classmethod
            def _color_valid(cls, v: str | None) -> str | None:
                if v is None:
                    return None
                color_lower = v.strip().lower()
                if color_lower not in COLOR_MAP:
                    valid_colors = ", ".join(sorted(COLOR_MAP.keys()))
                    raise ValueError(f"Unknown color '{v}'. Valid colors: {valid_colors}")
                return color_lower

            @field_validator("intensity")
            @classmethod
            def _intensity_valid(cls, v: float | None) -> float | None:
                if v is None:
                    return None
                if v < 0 or v > 100:
                    raise ValueError("intensity must be between 0 and 100")
                return float(v)

        data = RGBLEDInput(**payload).model_dump()
        return {"ok": True, "data": data}
    except (ValueError, TypeError, AttributeError):  # pydantic validation error or not installed
        # Best-effort fallback without pydantic
        action = str(payload.get("action", "")).strip().lower()
        valid_actions = {"on", "off"}
        if action not in valid_actions:
            return {
                "ok": False,
                "error": f"Invalid action. Use one of: {', '.join(sorted(valid_actions))}",
            }

        color = payload.get("color")
        if color is not None:
            color_str = str(color).strip()
            color_rgb = _color_name_to_rgb(color_str)
            if color_rgb is None:
                valid_colors = ", ".join(sorted(COLOR_MAP.keys()))
                return {
                    "ok": False,
                    "error": f"Unknown color '{color_str}'. Valid colors: {valid_colors}",
                }
            color = color_str.lower()

        intensity = payload.get("intensity")
        if intensity is not None:
            try:
                intensity = float(intensity)
                if intensity < 0 or intensity > 100:
                    return {"ok": False, "error": "intensity must be between 0 and 100"}
                intensity = float(intensity)
            except (ValueError, TypeError):
                return {"ok": False, "error": "intensity must be a number between 0 and 100"}

        return {"ok": True, "data": {"action": action, "color": color, "intensity": intensity}}


def run(input_dict: dict[str, Any]) -> dict[str, Any]:
    """
    Execute RGB LED control operation.

    Args:
        input_dict: Dictionary with keys:
            - action: "on" or "off" (required)
            - color: Optional color name string (e.g., "red", "blue", "green")
            - intensity: Optional intensity percentage (0-100)

    Returns:
        Dictionary with 'ok' and 'result' (if successful) or 'error' (if failed).
    """
    validated = _validate_input(input_dict)
    if not validated.get("ok"):
        return validated

    data = validated["data"]
    action = data["action"]
    color = data.get("color")
    intensity = data.get("intensity")

    # Get LED controller
    try:
        led = _get_led_controller()
    except (ImportError, RuntimeError, ValueError) as e:
        return {"ok": False, "error": f"LED controller unavailable: {e}"}

    # Handle "off" action
    if action == "off":
        led.off()
        return {
            "ok": True,
            "result": "LED turned off",
        }

    # Handle "on" action
    # Update color if provided
    if color is not None:
        color_rgb = _color_name_to_rgb(color)
        if color_rgb is None:
            return {"ok": False, "error": f"Unknown color: {color}"}
        led.set_color(color_rgb[0], color_rgb[1], color_rgb[2], color_name=color)

    # Update intensity if provided
    if intensity is not None:
        led.set_intensity(float(intensity))

    # Turn LED on
    led.on()

    # Get current state
    state = led.get_state()
    color_name = state["color"]
    intensity_val = state["intensity"]

    # Build user-friendly response message
    if color is not None and intensity is not None:
        result = f"LED is now on, showing {color} at {intensity_val:.0f}% brightness"
    elif color is not None:
        result = f"LED is now on, showing {color}"
    elif intensity is not None:
        result = f"LED is now on at {intensity_val:.0f}% brightness"
    else:
        result = "LED turned on"

    return {
        "ok": True,
        "result": result,
    }

