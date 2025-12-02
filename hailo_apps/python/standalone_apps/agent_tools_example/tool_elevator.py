"""
Elevator control tool for the Wonkavator (Great Glass Elevator).

Navigate between floors 0-5 in Willy Wonka's factory using natural language
descriptions, room names, keywords, or floor numbers.
"""

from __future__ import annotations

from typing import Any

# Make imports more robust
try:
    # Try relative import first
    from .elevator_interface import create_elevator_controller
    from . import config
except ImportError:
    # Fallback to absolute import if relative fails
    from elevator_interface import create_elevator_controller
    import config

name: str = "elevator"

# User-facing description (shown in CLI tool list)
display_description: str = (
    "Control the Wonkavator elevator: navigate between floors 0-5 in Willy Wonka's factory."
)

# Floor data (single source of truth)
FLOORS = {
    0: {
        "name": "Staff & Utilities (Basement)",
        "description": "The infrastructural and unseen level containing the boiler room, Oompa Loompa staff quarters, and other utilities necessary for maintenance and operation.",
        "keywords": ["maintenance", "boiler room", "staff quarters", "utilities", "basement", "underground", "oompa loompas", "oompa loompa", "lowest floor"]
    },
    1: {
        "name": "The Chocolate Room",
        "description": "The vast, edible garden floor. Features the Chocolate River and Waterfall. The starting point of the tour, famous for the elimination of Augustus Gloop, who fell into the river and was sucked up the pipe toward the Fudge Room.",
        "keywords": ["chocolate river", "waterfall", "edible grass", "augustus gloop", "fudge room", "garden", "simple sweets", "first floor", "ground floor", "chocolate room"]
    },
    2: {
        "name": "The Inventing Room",
        "description": "A laboratory filled with machines and bubbling pots where experimental sweets are created. This floor features the Everlasting Gobstopper and the disastrous Three-Course Dinner Chewing Gum. Violet Beauregarde was eliminated here by swelling up into a blueberry.",
        "keywords": ["inventing", "everlasting gobstopper", "gobstopper", "three-course gum", "violet beauregarde", "violet", "blueberry", "blue berry", "swelling", "chewing gum", "new candy", "experimental", "innovation", "inventing room", "laboratory", "lab", "second floor"]
    },
    3: {
        "name": "The Fizzy Lifting Drinks Room",
        "description": "The room housing the Fizzy Lifting Drinks, famous for the scene where Charlie and Grandpa Joe risk being chopped up by the ceiling fan after defying gravity and floating up. Ideal for requests about non-standard beverages or floating.",
        "keywords": ["floating", "lifting drinks", "fizzy lifting drinks", "burping", "ceiling fan", "gravity", "soda", "beverages", "charlie", "grandpa joe", "float", "fly"]
    },
    4: {
        "name": "The Nut Room",
        "description": "Dedicated to quality control where hundreds of trained Squirrels shell walnuts to find 'good' and 'bad' nuts. Veruca Salt was eliminated here, judged a 'bad nut' by the squirrels and sent down the Rubbish Chute.",
        "keywords": ["squirrels", "squirrel", "veruca salt", "bad egg", "rubbish chute", "nuts", "quality control", "i want it now", "nut room", "walnuts"]
    },
    5: {
        "name": "The Television-Chocolate Room",
        "description": "A sterile, white room containing the powerful Wonkavision camera/teleporter. It develops a way to send chocolate bars through television waves. Mike Teavee was eliminated here after shrinking himself down to a tiny size.",
        "keywords": ["tv", "television", "wonkavision", "teleporter", "shrinking", "mike teavee", "media", "broadcasting", "transmission", "top floor", "highest floor", "television room", "tv room"]
    }
}


def _build_floor_directory() -> str:
    """Build compact floor directory from FLOORS data including keywords."""
    lines = ["Willy Wonka's Factory Floors:"]
    for floor_num, floor_data in FLOORS.items():
        keywords_str = ", ".join(floor_data['keywords'])
        lines.append(f"Floor {floor_num}: {floor_data['name']} | Keywords: {keywords_str}")
    return "\n".join(lines)


# LLM instruction description (dynamically includes floor directory)
description: str = (
    "CRITICAL: You MUST use this tool when the user asks to navigate, move, or go to any floor or room in Willy Wonka's factory. "
    "ALWAYS call this tool for elevator/floor requests. The function name is 'elevator'. "
    "\n\n"
    f"{_build_floor_directory()}"
    "\n\n"
    "YOUR TASK: Interpret the user's request and call this tool with the integer floor number (0-5). "
    "Match room names, character names, keywords, or location descriptions to the correct floor. "
    "IMPORTANT MAPPINGS:\n"
    "- 'blueberry', 'blue berry', 'Violet' → Floor 2 (Inventing Room - where Violet turned into a blueberry)\n"
    "- 'inventing', 'laboratory', 'lab' → Floor 2 (Inventing Room)\n"
    "- 'chocolate river', 'Augustus' → Floor 1 (Chocolate Room)\n"
    "- 'squirrels', 'Veruca' → Floor 4 (Nut Room)\n"
    "- 'TV', 'television', 'Mike Teavee' → Floor 5 (Television-Chocolate Room)\n"
    "- 'fizzy lifting', 'floating' → Floor 3 (Fizzy Lifting Drinks Room)\n"
    "- 'first floor', 'ground floor' → Floor 1 (Chocolate Room - the starting point)\n"
    "- 'basement', 'lowest floor' → Floor 0 (Staff & Utilities)\n"
    "Examples: 'Chocolate Room' → floor=1, 'squirrels' → floor=4, 'top floor' → floor=5, 'blueberry' → floor=2."
)


# Initialize elevator controller (simulator) only when tool is selected
_elevator_controller = None
_initialized = False


def initialize_tool() -> None:
    """
    Initialize elevator controller when tool is selected.

    This function is called by chat_agent.py after the tool is selected.
    """
    global _elevator_controller, _initialized
    if not _initialized:
        try:
            _elevator_controller = create_elevator_controller()
            # Set default state: Floor 1 (Chocolate Room - starting point)
            _elevator_controller.move_to_floor(1)
            _initialized = True

            # Print instructions for simulator
            simulator_url = f"http://127.0.0.1:{config.ELEVATOR_SIMULATOR_PORT}"
            print(f"\n[Elevator Simulator] Open your browser and navigate to: {simulator_url}")
            print("[Elevator Simulator] The simulator will show the elevator position in real-time.\n", flush=True)

        except Exception as e:
            import logging
            import traceback
            logger = logging.getLogger(__name__)
            logger.error("Failed to initialize elevator controller: %s", e)
            logger.debug("Traceback: %s", traceback.format_exc())
            print(f"[Elevator] Warning: Elevator controller initialization failed: {e}", flush=True)
            # Don't raise - allow tool to work without simulator
            _initialized = True  # Mark as attempted to avoid retrying


def _get_elevator_controller() -> Any:
    """Get elevator controller instance, initializing if needed (fallback)."""
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
            import logging
            logger = logging.getLogger(__name__)
            logger.debug("Error during elevator controller cleanup: %s", e)


# Minimal JSON-like schema to assist prompting/validation
schema: dict[str, Any] = {
    "type": "object",
    "properties": {
        "floor": {
            "type": "integer",
            "description": "Integer floor number (0-5). Interpret user's natural language request to determine which floor.",
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
        input_dict: Dictionary with keys:
            - floor: Integer floor number (0-5) (required)

    Returns:
        Dictionary with 'ok' and 'result' (if successful) or 'error' (if failed).
    """
    # Get floor parameter
    floor_param = input_dict.get("floor")
    if floor_param is None:
        return {"ok": False, "error": "Missing required 'floor' parameter"}

    # Validate floor is an integer
    try:
        target_floor = int(floor_param)
    except (ValueError, TypeError):
        return {"ok": False, "error": f"Invalid floor '{floor_param}'. Floor must be an integer (0-5)."}

    # Validate floor range (0-5)
    if target_floor < 0 or target_floor > 5:
        return {"ok": False, "error": f"Invalid floor {target_floor}. Floor must be between 0-5."}

    # Check if floor exists in FLOORS data
    if target_floor not in FLOORS:
        return {"ok": False, "error": f"Floor {target_floor} not found in factory directory."}

    # Get elevator controller
    try:
        elevator = _get_elevator_controller()
    except (ImportError, RuntimeError, ValueError) as e:
        return {"ok": False, "error": f"Elevator controller unavailable: {e}"}

    # Check current floor
    current_state = elevator.get_state()
    current_floor = current_state["current_floor"]

    # Get floor information
    floor_info = FLOORS[target_floor]

    # If already on the floor, return message
    if current_floor == target_floor:
        return {
            "ok": True,
            "result": f"You are already on Floor {target_floor}: {floor_info['name']}."
        }

    # Move to target floor
    elevator.move_to_floor(target_floor)

    # Build result message
    result = f"Moved to Floor {target_floor}: {floor_info['name']}."

    return {
        "ok": True,
        "result": result,
    }

