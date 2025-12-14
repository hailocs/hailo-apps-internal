"""
Elevator control tool for the Wonkavator (Great Glass Elevator).

Navigate between floors 0-5 in Willy Wonka's factory using natural language.
"""

from __future__ import annotations

import logging
from typing import Any

# Import from parent package
from hailo_apps.python.gen_ai_apps.agent_tools_example.elevator_interface import (
    create_elevator_controller,
    FLOORS,
)
from hailo_apps.python.gen_ai_apps.agent_tools_example import config

logger = logging.getLogger(__name__)

name: str = "elevator"

# User-facing description
display_description: str = (
    "Control the Wonkavator elevator: navigate between floors 0-5 in Willy Wonka's factory."
)


def _build_floor_directory() -> str:
    """Build compact floor directory from FLOORS data."""
    lines = ["Willy Wonka's Factory Floors:"]
    for floor_num, floor_data in FLOORS.items():
        keywords_str = ", ".join(floor_data["keywords"][:5])  # First 5 keywords
        lines.append(f"Floor {floor_num}: {floor_data['name']} | Keywords: {keywords_str}")
    return "\n".join(lines)


# LLM instruction description
description: str = (
    "CRITICAL: You MUST use this tool when the user asks to navigate, move, or go to any floor or room in Willy Wonka's factory. "
    "ALWAYS call this tool for elevator/floor requests. The function name is 'elevator'. "
    "\n\n"
    f"{_build_floor_directory()}"
    "\n\n"
    "YOUR TASK: Interpret the user's request and call this tool with the integer floor number (0-5). "
    "Match room names, character names, keywords, or location descriptions to the correct floor. "
    "Examples: 'Chocolate Room' → floor=1, 'squirrels' → floor=4, 'top floor' → floor=5, 'blueberry' → floor=2."
)

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


schema: dict[str, Any] = {
    "type": "object",
    "properties": {
        "floor": {
            "type": "integer",
            "description": "Floor number (0-5). Interpret user's request to determine floor.",
        },
    },
    "required": ["floor"],
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


def run(input_dict: dict[str, Any]) -> dict[str, Any]:
    """
    Execute elevator navigation operation.

    Args:
        input_dict: Dictionary with floor number.

    Returns:
        Dictionary with 'ok' and 'result' or 'error'.
    """
    floor_param = input_dict.get("floor")
    if floor_param is None:
        return {"ok": False, "error": "Missing required 'floor' parameter"}

    try:
        target_floor = int(floor_param)
    except (ValueError, TypeError):
        return {"ok": False, "error": f"Invalid floor '{floor_param}'. Must be integer 0-5."}

    if target_floor < 0 or target_floor > 5:
        return {"ok": False, "error": f"Invalid floor {target_floor}. Must be 0-5."}

    if target_floor not in FLOORS:
        return {"ok": False, "error": f"Floor {target_floor} not found."}

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

