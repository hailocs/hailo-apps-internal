"""
Tools registry.

Each tool is a single .py file in this package exporting:
  - A function (e.g. ``get_weather``)
  - A ``TOOL_PROMPT`` string (LLM system prompt for parameter extraction)
  - A ``TOOL_DESCRIPTIONS`` list (natural-language sentences for tool selection)

Usage:
    from tools import TOOLS, TOOL_PROMPTS, TOOL_DESCRIPTIONS, run_tool
"""

import logging
from typing import Dict, Callable, List

from tools import weather, none, led, system_check, travel, explain_tools, data_storage

logger = logging.getLogger("v2a_demo")

# Single registry: tool_name -> (module, function_name)
# To add a new tool, add one entry here.
_REGISTRY = {
    "none":            (none,          "none"),
    "explain_tools":   (explain_tools, "explain_tools"),
    "get_weather":     (weather,       "get_weather"),
    "control_led":     (led,           "control_led"),
    "system_check":    (system_check,  "system_check"),
    "get_travel_time": (travel,        "get_travel_time"),
    "data_storage":    (data_storage,  "data_storage"),
}

TOOLS: Dict[str, Callable] = {name: getattr(mod, func) for name, (mod, func) in _REGISTRY.items()}
TOOL_PROMPTS: Dict[str, str] = {name: mod.TOOL_PROMPT for name, (mod, _) in _REGISTRY.items()}
TOOL_DESCRIPTIONS: Dict[str, List[str]] = {name: mod.TOOL_DESCRIPTIONS for name, (mod, _) in _REGISTRY.items()}
NO_PARAM_TOOLS = {"none", "explain_tools", "system_check"}


def run_tool(tool_name: str, params: dict) -> str:
    """Execute a tool by name with the given parameters."""
    if tool_name not in TOOLS:
        logger.warning(f"Unknown tool: {tool_name}")
        return f"Unknown tool: {tool_name}"
    logger.info(f"Executing tool: `{tool_name}` with params: {params}")
    try:
        return TOOLS[tool_name](**params)
    except TypeError as e:
        logger.error(f"Tool '{tool_name}' parameter error: {e}")
        return f"I had trouble understanding the parameters for {tool_name}."
    except Exception as e:
        logger.error(f"Tool '{tool_name}' execution error: {e}")
        return f"Something went wrong while running {tool_name}."
