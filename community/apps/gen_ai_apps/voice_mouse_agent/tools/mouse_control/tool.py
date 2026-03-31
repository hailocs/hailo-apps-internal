"""
Mouse control tool using pyautogui.

Provides mouse movement, clicking, scrolling, and dragging actions.
All actions execute on the local machine's display.
"""

from typing import Any

import pyautogui

# Disable pyautogui's built-in pause and failsafe for responsiveness
pyautogui.PAUSE = 0.05
pyautogui.FAILSAFE = True  # Move mouse to corner to abort

name: str = "mouse_control"

display_description: str = (
    "Control the mouse: move, click, scroll, and drag using voice commands."
)

description: str = (
    "Control the mouse cursor on the local machine. "
    "Supports these actions:\n"
    "- move: Move mouse relative to current position. Requires 'direction' (up/down/left/right) and 'pixels' (integer).\n"
    "- move_to: Move mouse to absolute screen position. Requires 'x' and 'y' (integers).\n"
    "- left_click: Perform a left mouse click.\n"
    "- right_click: Perform a right mouse click.\n"
    "- double_click: Perform a double left click.\n"
    "- scroll: Scroll the mouse wheel. Requires 'direction' (up/down) and 'amount' (integer, number of scroll units).\n"
    "- drag: Click and drag in a direction. Requires 'direction' (up/down/left/right) and 'pixels' (integer).\n\n"
    "Choose the 'action' parameter to select which operation to perform."
)

schema: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["move", "move_to", "left_click", "right_click", "double_click", "scroll", "drag"],
            "description": "The mouse action to perform.",
        },
        "direction": {
            "type": "string",
            "enum": ["up", "down", "left", "right"],
            "description": "Direction for move, scroll, or drag actions.",
        },
        "pixels": {
            "type": "integer",
            "description": "Number of pixels to move or drag. Default is 100.",
        },
        "x": {
            "type": "integer",
            "description": "Absolute X coordinate for move_to action.",
        },
        "y": {
            "type": "integer",
            "description": "Absolute Y coordinate for move_to action.",
        },
        "amount": {
            "type": "integer",
            "description": "Number of scroll units for scroll action. Default is 3.",
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

# Direction to (dx, dy) multiplier mapping
_DIRECTION_MAP = {
    "up": (0, -1),
    "down": (0, 1),
    "left": (-1, 0),
    "right": (1, 0),
}


def run(input_data: dict[str, Any]) -> dict[str, Any]:
    """
    Execute a mouse control action.

    Args:
        input_data: Dictionary with 'action' and action-specific parameters.

    Returns:
        Dictionary with 'ok' and 'result' or 'error'.
    """
    action = input_data.get("action", "").strip().lower()

    if not action:
        return {"ok": False, "error": "Missing 'action' parameter."}

    try:
        if action == "move":
            return _handle_move(input_data)
        elif action == "move_to":
            return _handle_move_to(input_data)
        elif action == "left_click":
            return _handle_left_click()
        elif action == "right_click":
            return _handle_right_click()
        elif action == "double_click":
            return _handle_double_click()
        elif action == "scroll":
            return _handle_scroll(input_data)
        elif action == "drag":
            return _handle_drag(input_data)
        else:
            return {"ok": False, "error": f"Unknown action: '{action}'."}
    except pyautogui.FailSafeException:
        return {"ok": False, "error": "Failsafe triggered (mouse moved to corner)."}
    except Exception as e:
        return {"ok": False, "error": f"Mouse action failed: {str(e)}"}


def _handle_move(data: dict[str, Any]) -> dict[str, Any]:
    """Move mouse relative to current position."""
    direction = data.get("direction", "").strip().lower()
    pixels = int(data.get("pixels", 100))

    if direction not in _DIRECTION_MAP:
        return {"ok": False, "error": f"Invalid direction: '{direction}'. Use up/down/left/right."}

    dx_mult, dy_mult = _DIRECTION_MAP[direction]
    dx = dx_mult * pixels
    dy = dy_mult * pixels

    pyautogui.moveRel(dx, dy, duration=0.2)
    pos = pyautogui.position()
    return {"ok": True, "result": f"Moved {direction} {pixels}px. Position: ({pos.x}, {pos.y})"}


def _handle_move_to(data: dict[str, Any]) -> dict[str, Any]:
    """Move mouse to absolute position."""
    x = data.get("x")
    y = data.get("y")

    if x is None or y is None:
        return {"ok": False, "error": "move_to requires both 'x' and 'y' parameters."}

    x = int(x)
    y = int(y)

    screen_w, screen_h = pyautogui.size()
    x = max(0, min(x, screen_w - 1))
    y = max(0, min(y, screen_h - 1))

    pyautogui.moveTo(x, y, duration=0.2)
    return {"ok": True, "result": f"Moved to ({x}, {y})."}


def _handle_left_click() -> dict[str, Any]:
    """Perform left click."""
    pos = pyautogui.position()
    pyautogui.click()
    return {"ok": True, "result": f"Left clicked at ({pos.x}, {pos.y})."}


def _handle_right_click() -> dict[str, Any]:
    """Perform right click."""
    pos = pyautogui.position()
    pyautogui.rightClick()
    return {"ok": True, "result": f"Right clicked at ({pos.x}, {pos.y})."}


def _handle_double_click() -> dict[str, Any]:
    """Perform double click."""
    pos = pyautogui.position()
    pyautogui.doubleClick()
    return {"ok": True, "result": f"Double clicked at ({pos.x}, {pos.y})."}


def _handle_scroll(data: dict[str, Any]) -> dict[str, Any]:
    """Scroll the mouse wheel."""
    direction = data.get("direction", "").strip().lower()
    amount = int(data.get("amount", 3))

    if direction == "up":
        pyautogui.scroll(amount)
    elif direction == "down":
        pyautogui.scroll(-amount)
    else:
        return {"ok": False, "error": f"Invalid scroll direction: '{direction}'. Use up/down."}

    return {"ok": True, "result": f"Scrolled {direction} by {amount} units."}


def _handle_drag(data: dict[str, Any]) -> dict[str, Any]:
    """Click and drag in a direction."""
    direction = data.get("direction", "").strip().lower()
    pixels = int(data.get("pixels", 100))

    if direction not in _DIRECTION_MAP:
        return {"ok": False, "error": f"Invalid direction: '{direction}'. Use up/down/left/right."}

    dx_mult, dy_mult = _DIRECTION_MAP[direction]
    dx = dx_mult * pixels
    dy = dy_mult * pixels

    start_pos = pyautogui.position()
    pyautogui.drag(dx, dy, duration=0.3)
    end_pos = pyautogui.position()
    return {
        "ok": True,
        "result": f"Dragged {direction} {pixels}px from ({start_pos.x}, {start_pos.y}) to ({end_pos.x}, {end_pos.y}).",
    }
