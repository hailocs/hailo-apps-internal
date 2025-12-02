"""
Servo control tool.

Supports moving servo to absolute angle or by relative angle.
The tool handles angle clamping internally, ensuring angles stay within valid range.
"""

from __future__ import annotations

from typing import Any

# Make imports more robust
try:
    # Try relative import first
    from .hardware_interface import create_servo_controller
    from . import config
except ImportError:
    # Fallback to absolute import if relative fails
    from hardware_interface import create_servo_controller
    import config

name: str = "servo"

# User-facing description (shown in CLI tool list)
display_description: str = (
    "Control servo: move to absolute angle or by relative angle (-90 to 90 degrees)."
)

# LLM instruction description (includes warnings for model)
description: str = (
    "CRITICAL: You MUST use this tool when the user asks to control, move, or do anything with a servo. "
    "ALWAYS call this tool if the user mentions: servo, move servo, set angle, rotate, turn, position, move to angle, move by angle. "
    "NEVER respond about servo control without calling this tool - ALWAYS use this tool for ANY servo-related request. Also if the context is implied from the previous message, call this tool."
    "The function name is 'servo' (use this exact name in tool calls). "
    "The tool supports two modes: 'absolute' (set to specific angle) and 'relative' (move by delta angle). "
    "Angle values are in degrees. Valid angle range is -90 to 90 degrees. "
    "Examples: 'move servo to 45 degrees' → mode='absolute', angle=45. "
    "Examples: 'rotate servo by 30 degrees' → mode='relative', angle=30. "
    "Examples: 'set servo to -45' → mode='absolute', angle=-45. "
    "Examples: 'move servo by -20 degrees' → mode='relative', angle=-20. "
    "Examples: 'turn servo left 15 degrees' → mode='relative', angle=-15. "
    "Examples: 'position servo at center' → mode='absolute', angle=0. "
    "Examples: 'home servo' → mode='absolute', angle=0."
)

# Initialize servo controller (hardware or simulator) only when tool is selected
_servo_controller = None
_initialized = False


def initialize_tool() -> None:
    """
    Initialize servo controller when tool is selected.

    This function is called by chat_agent.py after the tool is selected.
    """
    global _servo_controller, _initialized
    if not _initialized:
        try:
            _servo_controller = create_servo_controller()
            # Set default state: center position (0 degrees)
            _servo_controller.set_angle(0.0)
            _initialized = True

            # Print instructions if simulator mode
            if config.HARDWARE_MODE.lower() == "simulator":
                simulator_url = f"http://127.0.0.1:{config.SERVO_SIMULATOR_PORT}"
                print(f"\n[Servo Simulator] Open your browser and navigate to: {simulator_url}")
                print("[Servo Simulator] The simulator will show the servo position in real-time.\n", flush=True)

        except Exception as e:
            import logging
            import traceback
            logger = logging.getLogger(__name__)
            logger.error("Failed to initialize servo controller: %s", e)
            logger.debug("Traceback: %s", traceback.format_exc())
            print(f"[Servo] Warning: Servo controller initialization failed: {e}", flush=True)
            # Don't raise - allow tool to work without hardware/simulator
            _initialized = True  # Mark as attempted to avoid retrying


def _get_servo_controller() -> Any:
    """Get servo controller instance, initializing if needed (fallback)."""
    if not _initialized:
        initialize_tool()
    return _servo_controller


def cleanup_tool() -> None:
    """Clean up servo controller resources."""
    global _servo_controller
    if _servo_controller is not None and hasattr(_servo_controller, "cleanup"):
        try:
            _servo_controller.cleanup()
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.debug("Error during servo controller cleanup: %s", e)


# Minimal JSON-like schema to assist prompting/validation
schema: dict[str, Any] = {
    "type": "object",
    "properties": {
        "mode": {
            "type": "string",
            "enum": ["absolute", "relative"],
            "description": (
                "Mode of operation: 'absolute' to set servo to specific angle, "
                "'relative' to move servo by delta angle from current position."
            ),
        },
        "angle": {
            "type": "number",
            "description": (
                "Angle value in degrees. "
                "For 'absolute' mode: target angle (-90 to 90 degrees). "
                "For 'relative' mode: delta angle to move (can be positive or negative). "
                "The tool will clamp angles to valid range automatically."
            ),
        },
    },
    "required": ["mode", "angle"],
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

        class ServoInput(BaseModel):
            mode: str = Field(description="Mode: absolute or relative")
            angle: float = Field(description="Angle in degrees")

            @field_validator("mode")
            @classmethod
            def _mode_valid(cls, v: str) -> str:
                valid_modes = {"absolute", "relative"}
                if v not in valid_modes:
                    raise ValueError(f"mode must be one of: {', '.join(sorted(valid_modes))}")
                return v

            @field_validator("angle")
            @classmethod
            def _angle_valid(cls, v: float) -> float:
                # Angle can be any number, but we'll clamp it in the tool
                return float(v)

        data = ServoInput(**payload).model_dump()
        return {"ok": True, "data": data}
    except (ValueError, TypeError, AttributeError):  # pydantic validation error or not installed
        # Best-effort fallback without pydantic
        mode = str(payload.get("mode", "")).strip().lower()
        valid_modes = {"absolute", "relative"}
        if mode not in valid_modes:
            return {
                "ok": False,
                "error": f"Invalid mode. Use one of: {', '.join(sorted(valid_modes))}",
            }

        angle = payload.get("angle")
        if angle is None:
            return {"ok": False, "error": "angle is required"}
        try:
            angle = float(angle)
        except (ValueError, TypeError):
            return {"ok": False, "error": "angle must be a number"}

        return {"ok": True, "data": {"mode": mode, "angle": angle}}


def run(input_dict: dict[str, Any]) -> dict[str, Any]:
    """
    Execute servo control operation.

    Args:
        input_dict: Dictionary with keys:
            - mode: "absolute" or "relative" (required)
            - angle: Angle value in degrees (required)

    Returns:
        Dictionary with 'ok' and 'result' (if successful) or 'error' (if failed).
    """
    validated = _validate_input(input_dict)
    if not validated.get("ok"):
        return validated

    data = validated["data"]
    mode = data["mode"]
    angle = data["angle"]

    # Get servo controller
    try:
        servo = _get_servo_controller()
    except (ImportError, RuntimeError, ValueError) as e:
        return {"ok": False, "error": f"Servo controller unavailable: {e}"}

    # Get current state for angle limits
    state = servo.get_state()
    min_angle = state["min_angle"]
    max_angle = state["max_angle"]

    # Handle absolute mode
    if mode == "absolute":
        # Clamp angle to valid range
        clamped_angle = max(min_angle, min(max_angle, angle))
        servo.set_angle(clamped_angle)
        final_state = servo.get_state()
        current_angle = final_state["angle"]

        # Build message
        if angle != clamped_angle:
            result = f"Servo moved to {current_angle:.1f}° (requested {angle:.1f}° was clamped to valid range)"
        else:
            result = f"Servo moved to {current_angle:.1f}°"

        return {
            "ok": True,
            "result": result,
        }

    # Handle relative mode
    else:  # mode == "relative"
        current_angle = state["angle"]
        target_angle = current_angle + angle
        # Clamp to valid range
        clamped_angle = max(min_angle, min(max_angle, target_angle))
        servo.move_relative(angle)
        final_state = servo.get_state()
        final_angle = final_state["angle"]

        # Build message
        if target_angle != clamped_angle:
            result = f"Servo moved by {angle:.1f}° to {final_angle:.1f}° (requested position {target_angle:.1f}° was clamped to valid range)"
        else:
            result = f"Servo moved by {angle:.1f}° to {final_angle:.1f}°"

        return {
            "ok": True,
            "result": result,
        }

