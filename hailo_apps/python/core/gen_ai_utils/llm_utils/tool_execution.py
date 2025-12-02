"""
Tool execution module.

Handles tool initialization and execution.
"""

import json
import logging
import traceback
from typing import Any, Dict

# Setup logger
logger = logging.getLogger(__name__)


def initialize_tool_if_needed(tool: Dict[str, Any]) -> None:
    """
    Initialize tool if it has an initialize_tool function.

    Args:
        tool: Tool dictionary containing a 'module' key.
    """
    tool_module = tool.get("module")
    if tool_module and hasattr(tool_module, "initialize_tool"):
        try:
            tool_module.initialize_tool()
        except Exception as e:
            logger.warning("Tool initialization failed: %s", e)
            # Reason: Logging traceback helps debug initialization issues which might be hardware related
            logger.debug("Initialization traceback: %s", traceback.format_exc())


def execute_tool_call(
    tool_call: Dict[str, Any], tools_lookup: Dict[str, Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Execute a tool call and return the result.

    Args:
        tool_call: Parsed tool call dictionary with 'name' and 'arguments' keys.
        tools_lookup: Dictionary mapping tool names to tool metadata.

    Returns:
        Tool execution result dictionary with 'ok' key and either 'result' or 'error'.
    """
    if not isinstance(tool_call, dict):
        return {"ok": False, "error": "Invalid tool call format: expected dictionary"}

    tool_name = str(tool_call.get("name", "")).strip()
    if not tool_name:
         return {"ok": False, "error": "Tool call missing 'name' field"}

    args = tool_call.get("arguments", {})
    if not isinstance(args, dict):
        return {"ok": False, "error": f"Invalid arguments format for tool '{tool_name}': expected dictionary, got {type(args).__name__}"}

    logger.info("TOOL CALL: %s", tool_name)
    logger.debug("Tool call details - name: %s", tool_name)
    logger.debug("Tool call arguments:\n%s", json.dumps(args, indent=2, ensure_ascii=False))

    selected = tools_lookup.get(tool_name)
    if not selected:
        # Reason: Provide available tools to help user correct the request
        available = ", ".join(sorted(tools_lookup.keys()))
        error_msg = f"Unknown tool '{tool_name}'. Available: {available}"
        logger.error(error_msg)
        return {"ok": False, "error": error_msg}

    runner = selected.get("runner")
    if not callable(runner):
        error_msg = f"Tool '{tool_name}' is missing an executable runner."
        logger.error(error_msg)
        return {"ok": False, "error": error_msg}

    try:
        result = runner(args)  # type: ignore[misc]

        # Validate result format
        if not isinstance(result, dict):
            # Reason: Ensure tool follows contract even if implementation is buggy
            error_msg = f"Tool '{tool_name}' returned invalid format: expected dict, got {type(result).__name__}"
            logger.error(error_msg)
            return {"ok": False, "error": error_msg}

        logger.debug("TOOL EXECUTION RESULT:\n%s", json.dumps(result, indent=2, ensure_ascii=False))
        return result
    except Exception as exc:
        # Reason: Capture full traceback in debug mode for developers
        logger.error("Tool execution raised exception: %s", exc)
        logger.debug("Tool execution traceback: %s", traceback.format_exc())

        error_msg = f"Tool '{tool_name}' execution failed: {str(exc)}"
        result = {"ok": False, "error": error_msg}
        return result


def print_tool_result(result: Dict[str, Any]) -> None:
    """
    Print tool execution result to the user.

    Args:
        result: Tool execution result dictionary with 'ok' key.
    """
    if not isinstance(result, dict):
        print(f"\n[Tool Error] Invalid result format: {result}\n")
        return

    if result.get("ok"):
        logger.info("Tool execution: SUCCESS")
        tool_result_text = result.get("result", "")
        if tool_result_text:
            print(f"\n[Tool] {tool_result_text}\n")
    else:
        error_msg = result.get("error", "Unknown error")
        logger.info("Tool execution: FAILED - %s", error_msg)
        print(f"\n[Tool Error] {error_msg}\n")

