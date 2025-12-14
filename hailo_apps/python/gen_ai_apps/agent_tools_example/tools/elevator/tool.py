"""
Elevator control tool for the Wonkavator (Great Glass Elevator).

Navigate between floors in Willy Wonka's factory using natural language.
Floor configuration is loaded from config.yaml.
"""

from __future__ import annotations

import logging
from typing import Any

# Import from local interface module
from .interface import (
    create_elevator_controller,
    FLOORS,
)
from hailo_apps.python.gen_ai_apps.agent_tools_example import config

logger = logging.getLogger(__name__)

name: str = "elevator"


def _get_display_description() -> str:
    """Build display description dynamically based on available floors."""
    if not FLOORS:
        return "Control the Wonkavator elevator: navigate between floors in Willy Wonka's factory."
    floor_nums = sorted(FLOORS.keys())
    min_floor = min(floor_nums)
    max_floor = max(floor_nums)
    return f"Control the Wonkavator elevator: navigate between floors {min_floor}-{max_floor} in Willy Wonka's factory."


# User-facing description
display_description: str = _get_display_description()


def _build_floor_directory() -> str:
    """Build floor directory from FLOORS data with all keywords."""
    lines = ["FLOOR DIRECTORY - Complete floor information:"]
    for floor_num in sorted(FLOORS.keys()):
        floor_data = FLOORS[floor_num]
        keywords_str = ", ".join(floor_data["keywords"])
        lines.append(f"\nFloor {floor_num}: {floor_data['name']}")
        lines.append(f"  Keywords: {keywords_str}")
    return "\n".join(lines)


# LLM instruction description
def _get_description() -> str:
    """Build tool description dynamically with floor directory."""
    floor_range = f"{min(FLOORS.keys()) if FLOORS else 0}-{max(FLOORS.keys()) if FLOORS else 5}"

    return (
        "CRITICAL: You MUST use this tool when the user asks to navigate, move, or go to any floor or room in Willy Wonka's factory. "
        "ALWAYS call this tool for elevator/floor requests. The function name is 'elevator'.\n\n"
        f"{_build_floor_directory()}\n\n"
        "YOUR TASK: Interpret the user's request and call this tool with the integer floor number. "
        "Match room names, character names, keywords, or location descriptions to the correct floor. "
        "Use the floor directory above to find the correct floor number.\n\n"
        f"DEFAULT OPTION: If the user requests a floor number outside the available range ({floor_range}), "
        "or if you cannot determine which floor the user wants (ambiguous request), set 'default' to true. "
        "Use this when you cannot confidently map the user's request to a valid floor number. "
        "The tool will automatically generate an appropriate error message."
    )


description: str = _get_description()

# Initialize elevator controller only when tool is selected
_elevator_controller = None
_initialized = False


def initialize_tool() -> None:
    """Initialize elevator controller when tool is selected."""
    global _elevator_controller, _initialized
    if not _initialized:
        try:
            _elevator_controller = create_elevator_controller()
            _elevator_controller.move_to_floor(1)  # Start at Floor 1 (Chocolate Room)
            _initialized = True

            simulator_url = f"http://127.0.0.1:{config.ELEVATOR_SIMULATOR_PORT}"
            print(f"\n[Elevator Simulator] Open your browser: {simulator_url}\n", flush=True)

        except Exception as e:
            logger.error("Failed to initialize elevator controller: %s", e)
            print(f"[Elevator] Warning: Elevator controller initialization failed: {e}", flush=True)
            _initialized = True


def _get_elevator_controller() -> Any:
    """Get elevator controller instance, initializing if needed."""
    if not _initialized:
        initialize_tool()
    return _elevator_controller


def cleanup_tool() -> None:
    """Clean up elevator controller resources."""
    global _elevator_controller
    if _elevator_controller is not None and hasattr(_elevator_controller, "cleanup"):
        try:
            _elevator_controller.cleanup()
        except Exception as e:
            logger.debug("Error during elevator controller cleanup: %s", e)


def _get_schema() -> dict[str, Any]:
    """Build schema dynamically based on available floors."""
    floor_nums = sorted(FLOORS.keys())
    min_floor = min(floor_nums) if floor_nums else 0
    max_floor = max(floor_nums) if floor_nums else 5
    floor_range_str = f"{min_floor}-{max_floor}"

    return {
        "type": "object",
        "properties": {
            "floor": {
                "type": "integer",
                "description": f"Floor number ({floor_range_str}). Interpret user's request to determine floor. Required unless 'default' is used.",
            },
            "default": {
                "type": "boolean",
                "description": (
                    f"Set to true when the user requests an invalid floor number or when you cannot determine "
                    f"which floor the user wants. The tool will automatically generate an appropriate error message "
                    f"with available floors ({floor_range_str})."
                ),
            },
        },
        "required": [],
    }


schema: dict[str, Any] = _get_schema()

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


def run(input_dict: dict[str, Any]) -> dict[str, Any]:
    """
    Execute elevator navigation operation.

    Args:
        input_dict: Dictionary with floor number or default message.

    Returns:
        Dictionary with 'ok' and 'result' or 'error'.
    """
    # Check for default option first (user error - agent correctly used default)
    if input_dict.get("default") is True:
        return {
            "ok": True,  # Agent used tool correctly (default option)
            "error": f"I couldn't translate your question to the available floors.",
        }

    floor_param = input_dict.get("floor")
    if floor_param is None:
        return {"ok": False, "error": "Either 'floor' or 'default' must be provided"}

    try:
        target_floor = int(floor_param)
    except (ValueError, TypeError):
        floor_range = f"{min(FLOORS.keys()) if FLOORS else 0}-{max(FLOORS.keys()) if FLOORS else 5}"
        return {"ok": False, "error": f"Invalid floor '{floor_param}'. Must be integer {floor_range}."}

    if not FLOORS or target_floor not in FLOORS:
        floor_range = f"{min(FLOORS.keys()) if FLOORS else 0}-{max(FLOORS.keys()) if FLOORS else 5}"
        return {"ok": False, "error": f"Invalid floor {target_floor}. Must be {floor_range}."}


    try:
        elevator = _get_elevator_controller()
    except Exception as e:
        return {"ok": False, "error": f"Elevator controller unavailable: {e}"}

    current_state = elevator.get_state()
    current_floor = current_state["current_floor"]
    floor_info = FLOORS[target_floor]

    if current_floor == target_floor:
        return {"ok": True, "result": f"You are already on Floor {target_floor}: {floor_info['name']}."}

    elevator.move_to_floor(target_floor)
    return {"ok": True, "result": f"Moved to Floor {target_floor}: {floor_info['name']}."}

