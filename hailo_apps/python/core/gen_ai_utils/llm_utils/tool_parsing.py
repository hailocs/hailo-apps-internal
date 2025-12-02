"""
Text processing utilities for tool parsing.

Handles parsing and validation of tool calls from LLM responses.
"""

import json
import logging
import re
import traceback
from typing import Any, Dict, Optional

# Setup logger
logger = logging.getLogger(__name__)


def parse_function_call(response: str) -> Optional[Dict[str, Any]]:
    """
    Parse function call from LLM response.

    ONLY supports XML-wrapped format:
    <tool_call>
    {"name": "...", "arguments": {...}}
    </tool_call>

    Args:
        response: Raw response string from LLM

    Returns:
        Parsed function call dict with 'name' and 'arguments' keys, or None if not found
    """
    def validate_and_fix_call(call: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Validate that call has required fields and fix nested JSON."""
        if not isinstance(call, dict):
            logger.debug(f"Invalid call format: expected dict, got {type(call)}")
            return None

        # Must have 'name' field
        if "name" not in call or not call.get("name"):
            logger.debug("Tool call missing 'name' field")
            return None

        # Must have 'arguments' field
        if "arguments" not in call:
            logger.debug("Tool call missing 'arguments' field")
            return None

        # Fix nested JSON in arguments
        # Reason: Some models stringify the arguments object
        if isinstance(call.get("arguments"), str):
            try:
                # Try to parse stringified JSON arguments
                # Replace single quotes with double quotes if needed
                args_str = call["arguments"]
                if "'" in args_str and '"' not in args_str:
                    args_str = args_str.replace("'", '"')
                call["arguments"] = json.loads(args_str)
            except Exception as e:
                logger.debug(f"Failed to parse nested arguments JSON: {e}")
                pass

        # Ensure arguments is a dict
        if not isinstance(call.get("arguments"), dict):
            logger.debug(f"Tool arguments invalid format: expected dict, got {type(call.get('arguments'))}")
            return None

        return call

    # Check for XML tag
    if "<tool_call>" not in response:
        return None

    try:
        # Extract content between tags
        start = response.find("<tool_call>") + len("<tool_call>")

        # Find closing tag, or use brace matching if missing
        end = response.find("</tool_call>", start)

        if end == -1:
            # No closing tag, use robust brace matching
            # Reason: Streaming response might be truncated or model forgot closing tag
            json_str = response[start:].strip()

            # Find the complete JSON object by matching braces
            brace_count = 0
            json_end = -1
            in_string = False
            escape = False

            for i, char in enumerate(json_str):
                if escape:
                    escape = False
                    continue

                if char == '\\':
                    escape = True
                    continue

                if char == '"':
                    in_string = not in_string
                    continue

                if not in_string:
                    if char == '{':
                        brace_count += 1
                    elif char == '}':
                        brace_count -= 1
                        if brace_count == 0:
                            json_end = i + 1
                            break

            if json_end > 0:
                json_str = json_str[:json_end]
            else:
                logger.debug("Could not find complete JSON object in partial response")
                return None
        else:
            json_str = response[start:end].strip()

        # Clean up JSON string
        # 1. Handle single quotes (common error)
        # Only replace if it looks like property names or string values
        # Simple heuristic: if no double quotes, assume single quotes usage
        if "'" in json_str and '"' not in json_str:
            json_str = json_str.replace("'", '"')

        # 2. Handle trailing commas (invalid JSON but common)
        json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)

        try:
            call = json.loads(json_str)
            return validate_and_fix_call(call)
        except json.JSONDecodeError as e:
            logger.debug(f"JSON decode failed: {e}. Content: {json_str}")
            # Last resort: try partial fix for unquoted keys?
            # (Maybe too risky for general tool calling)
            return None

    except Exception as e:
        logger.error(f"Error parsing tool call: {e}")
        logger.debug(traceback.format_exc())
        return None

