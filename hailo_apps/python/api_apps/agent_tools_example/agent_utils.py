"""
Utility functions for the chat agent.

Contains tool discovery, system prompt generation, text processing, context management,
and message formatting utilities.
"""

from __future__ import annotations

import importlib
import json
import logging
import pkgutil
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from hailo_platform.genai import LLM

logger = logging.getLogger(__name__)

# Import config for context threshold
try:
    from . import config
except ImportError:
    # When run directly, use absolute import
    import config

CONTEXT_THRESHOLD = getattr(config, "CONTEXT_THRESHOLD", 0.80)


# ============================================================================
# Tool Discovery
# ============================================================================


def discover_tool_modules() -> list[ModuleType]:
    """
    Discover tool modules from files named 'tool_*.py' in the tools directory.

    Returns:
        List of imported tool modules
    """
    modules: list[ModuleType] = []
    current_dir = Path(__file__).parent

    # Ensure current directory is in sys.path (works from any directory)
    if str(current_dir) not in sys.path:
        sys.path.insert(0, str(current_dir))

    # Build module name: use package prefix if available, otherwise just module name
    package_prefix = f"{__package__}." if __package__ else ""

    for module_info in pkgutil.iter_modules([str(current_dir)]):
        if not module_info.name.startswith("tool_"):
            continue
        try:
            module_name = f"{package_prefix}{module_info.name}"
            modules.append(importlib.import_module(module_name))
        except Exception:
            continue
    return modules


def collect_tools(modules: list[ModuleType]) -> list[dict[str, Any]]:
    """
    Collect tool metadata and schemas from tool modules.

    Args:
        modules: List of tool modules to process

    Returns:
        List of dictionaries with keys:
            - name: Tool name (string)
            - display_description: User-facing description for CLI (string)
            - llm_description: Description for LLM/tool schema (string)
            - tool_def: Full tool definition dict following the TOOL_SCHEMA format
            - runner: Callable that executes the tool (usually module.run)
            - module: The originating module (for debugging/logging)
    """
    tools: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for m in modules:
        run_fn = getattr(m, "run", None)
        # Skip template tool to avoid confusing the model
        module_name = getattr(m, "name", None)
        if module_name == "template_tool":
            continue

        tool_schemas = getattr(m, "TOOLS_SCHEMA", None)
        display_description = getattr(m, "display_description", None)
        llm_description_attr = getattr(m, "description", None)

        if tool_schemas and isinstance(tool_schemas, list):
            for entry in tool_schemas:
                if not isinstance(entry, dict):
                    continue
                if entry.get("type") != "function":
                    continue
                function_def = entry.get("function", {})
                name = function_def.get("name")
                description = function_def.get("description", llm_description_attr or "")
                if not name or not callable(run_fn):
                    continue
                if name in seen_names:
                    continue
                seen_names.add(name)
                display_desc = display_description if display_description else description or name
                tools.append(
                    {
                        "name": str(name),
                        "display_description": str(display_desc),
                        "llm_description": str(description),
                        "tool_def": entry,
                        "runner": run_fn,
                        "module": m,
                    }
                )
            continue

        # Legacy fallback: build schema on the fly if TOOLS_SCHEMA not provided
        name = getattr(m, "name", None)
        llm_description = llm_description_attr
        schema = getattr(m, "schema", None)
        if name and llm_description and callable(run_fn):
            if name in seen_names:
                continue
            seen_names.add(name)
            display_desc = display_description if display_description else llm_description
            parameters = schema if isinstance(schema, dict) else {"type": "object", "properties": {}}
            tool_def = {
                "type": "function",
                "function": {
                    "name": str(name),
                    "description": str(llm_description),
                    "parameters": parameters,
                },
            }
            tools.append(
                {
                    "name": str(name),
                    "display_description": str(display_desc),
                    "llm_description": str(llm_description),
                    "tool_def": tool_def,
                    "runner": run_fn,
                    "module": m,
                }
            )
    tools.sort(key=lambda t: t["name"])
    return tools


# ============================================================================
# System Prompt Generation
# ============================================================================


def create_system_prompt(tools: list[dict[str, Any]]) -> str:
    """
    Create system prompt with tool definitions.

    Uses a simple, general prompt that focuses on HOW to call tools, not WHICH tools to use.
    Tool-specific instructions are provided in each tool's description field.

    Args:
        tools: List of tool metadata dictionaries containing a ready-to-use tool definition

    Returns:
        System prompt string for the LLM
    """
    # Each tool already supplies a full function definition via TOOLS_SCHEMA
    tool_defs = [t["tool_def"] for t in tools]
    tools_json = json.dumps(tool_defs, separators=(",", ":"))

    # Extract tool names for explicit listing
    tool_names = [t["name"] for t in tools]
    tool_names_list = ", ".join(f'"{name}"' for name in tool_names)

    return f"""You are Qwen, created by Alibaba Cloud. You are a helpful assistant.

# Available Tools
You are provided with function signatures within <tools></tools> XML tags:
<tools>
{tools_json}
</tools>

CRITICAL RULES - READ CAREFULLY:
1. ONLY these tools exist and can be called: {tool_names_list}
2. NEVER invent, create, or call tools with different names - if a tool name is not in the list above, it does NOT exist
3. For greetings ("hi", "hello", etc.), small talk, or casual conversation: respond directly WITHOUT calling any tool
4. If the user's request doesn't match any available tool's purpose, respond naturally WITHOUT calling a tool

# When to Call a Tool
Call a tool ONLY when:
- The user's request clearly requires a specific action from one of these tools: {tool_names_list}
- You have all required parameters for that specific tool
- The request matches the exact purpose of one of the available tools

# When NOT to Call a Tool (IMPORTANT)
DO NOT call a tool for:
- Greetings: "hi", "hello", "good morning", "hey", etc. → Just respond with text, NO tool call
- Small talk: casual conversation, questions about you, etc. → Just respond with text, NO tool call
- Questions unrelated to available tools → Just respond with text, NO tool call
- Requests that don't match any tool's purpose → Just respond with text, NO tool call

# Tool Call Format
If you decide a tool call is needed:
1. Use ONLY double quotes (") in JSON, NEVER single quotes (')
2. Ensure arguments are a JSON object, NOT a JSON string
3. Wrap the JSON in <tool_call></tool_call> XML tags
4. Use EXACTLY one of these tool names: {tool_names_list}

Example:
<tool_call>
{{"name": "{tool_names[0]}", "arguments": {{"param1": "value1"}}}}
</tool_call>

# Responding to Tool Results
When you receive a <tool_response>, respond directly to the user with a concise, natural message based on the ACTUAL tool result data:
- DO NOT thank the tool or acknowledge the tool call
- DO NOT repeat technical details like "tool call was successful"
- DO read the tool result JSON carefully and respond based on what it actually contains
- DO use the specific data from the tool result (e.g., "result", "message", "state" fields)
- DO NOT invent or assume what the tool result contains - use only what is actually in the JSON

Example: If the tool returns {{"ok": true, "result": 2}}, respond based on that result: "The result is 2."
Example: If the tool returns {{"ok": true, "message": "Operation completed"}}, respond based on that message.

Remember: If unsure whether to call a tool, respond normally without calling a tool.

"""


# ============================================================================
# Text Processing
# ============================================================================


class StreamingTextFilter:
    """
    Filter streaming tokens on-the-fly to remove XML tags and special tokens.

    Maintains state to handle partial tags that arrive across token boundaries.
    """

    def __init__(self, debug_mode: bool = False):
        self.buffer = ""
        self.inside_text_tag = False
        self.inside_tool_call_tag = False
        self.debug_mode = debug_mode

    def process_token(self, token: str) -> str:
        """
        Process a single token and return cleaned text ready for display.

        Args:
            token: Raw token from LLM

        Returns:
            Cleaned text to print (may be empty if token should be suppressed)
        """
        # In debug mode, don't filter anything - show raw output
        if self.debug_mode:
            return token

        self.buffer += token

        # Remove <|im_end|> tokens immediately
        if "<|im_end|>" in self.buffer:
            self.buffer = self.buffer.replace("<|im_end|>", "")

        output = ""

        # Process buffer until no more complete tags are found
        changed = True
        while changed:
            changed = False

            # Check for <text> tag start
            text_start = self.buffer.find("<text>")
            if text_start != -1 and not self.inside_text_tag:
                # Extract anything before <text> tag (should be empty, but just in case)
                if text_start > 0:
                    output += self.buffer[:text_start]
                self.buffer = self.buffer[text_start + 6:]  # Remove "<text>"
                self.inside_text_tag = True
                changed = True
                continue

            # Check for </text> tag end
            text_end = self.buffer.find("</text>")
            if text_end != -1 and self.inside_text_tag:
                # Extract text content before </text>
                output += self.buffer[:text_end]
                self.buffer = self.buffer[text_end + 7:]  # Remove "</text>"
                self.inside_text_tag = False
                changed = True
                continue

            # Check for <tool_call> tag start
            tool_call_start = self.buffer.find("<tool_call>")
            if tool_call_start != -1 and not self.inside_tool_call_tag:
                # If we're inside <text>, output content before <tool_call>
                if self.inside_text_tag and tool_call_start > 0:
                    output += self.buffer[:tool_call_start]
                self.buffer = self.buffer[tool_call_start + 10:]  # Remove "<tool_call>"
                self.inside_tool_call_tag = True
                changed = True
                continue

            # Check for </tool_call> tag end
            tool_call_end = self.buffer.find("</tool_call>")
            if tool_call_end != -1 and self.inside_tool_call_tag:
                # Suppress everything inside <tool_call>
                self.buffer = self.buffer[tool_call_end + 12:]  # Remove "</tool_call>"
                self.inside_tool_call_tag = False
                changed = True
                continue

        # If we're inside <text> tag and not inside <tool_call>, output remaining buffer
        if self.inside_text_tag and not self.inside_tool_call_tag and self.buffer:
            output += self.buffer
            self.buffer = ""

        return output

    def get_remaining(self) -> str:
        """Get any remaining buffered content after streaming completes."""
        # In debug mode, return empty (everything was printed already)
        if self.debug_mode:
            return ""
        # Clean up any remaining partial tags or buffer content
        if self.inside_text_tag and not self.inside_tool_call_tag:
            # If we're still inside text tag, return the buffer (might have partial closing tag)
            remaining = self.buffer
            # Remove any partial closing tags like "</text" or "text>"
            remaining = remaining.replace("</text", "").replace("text>", "")
            return remaining
        # Also clean up any partial tags that might remain in buffer
        cleaned = self.buffer.replace("</text", "").replace("text>", "").replace("<text", "")
        return cleaned


def clean_response(response: str) -> str:
    """
    Clean LLM response by removing special tokens and extracting text from XML tags.

    Removes:
    - <|im_end|> tokens
    - <text>...</text> wrapper tags (extracts content)
    - <tool_call>...</tool_call> tags (tool calls are parsed separately)

    Args:
        response: Raw response string from LLM

    Returns:
        Cleaned response text ready for display
    """
    # Remove special tokens
    cleaned = response.replace("<|im_end|>", "")

    # Extract text from <text>...</text> tags
    text_match = re.search(r"<text>(.*?)</text>", cleaned, re.DOTALL)
    if text_match:
        cleaned = text_match.group(1).strip()

    # Remove <tool_call>...</tool_call> tags if present (we parse these separately)
    cleaned = re.sub(r"<tool_call>.*?</tool_call>", "", cleaned, flags=re.DOTALL)

    # Clean up any remaining whitespace
    return cleaned.strip()


def parse_function_call(response: str) -> dict[str, Any] | None:
    """
    Parse function call from LLM response.

    Supports multiple formats:
    1. XML-wrapped: <tool_call>{...}</tool_call>
    2. JSON fenced block: ```json {...} ```
    3. Raw inline JSON: {"name": "...", "arguments": {...}}

    Args:
        response: Raw response string from LLM

    Returns:
        Parsed function call dict with 'name' and 'arguments' keys, or None if not found
    """
    # 1) XML-wrapped function call
    if "<tool_call>" in response and "</tool_call>" in response:
        try:
            start = response.find("<tool_call>") + len("<tool_call>")
            end = response.find("</tool_call>")
            json_str = response[start:end].strip().replace("'", '"')
            call = json.loads(json_str)
            if isinstance(call.get("arguments"), str):
                try:
                    call["arguments"] = json.loads(call["arguments"])  # nested JSON fix
                except Exception:
                    pass
            return call
        except Exception:
            return None

    # 2) JSON fenced block ```json ... ```
    m = re.search(r"```json\s*(\{.*?})\s*```", response, re.DOTALL)
    if m:
        try:
            json_str = m.group(1).strip().replace("'", '"')
            call = json.loads(json_str)
            if isinstance(call.get("arguments"), str):
                try:
                    call["arguments"] = json.loads(call["arguments"])  # nested JSON fix
                except Exception:
                    pass
            return call
        except Exception:
            return None

    # 3) Raw inline JSON fallback
    m = re.search(r'\{"name"\s*:\s*"([^"]+)"\s*,\s*"arguments"\s*:\s*(\{[^}]+\})', response)
    if m:
        try:
            json_str = response[m.start():m.end()].replace("'", '"')
            call = json.loads(json_str)
            if isinstance(call.get("arguments"), str):
                try:
                    call["arguments"] = json.loads(call["arguments"])  # nested JSON fix
                except Exception:
                    pass
            return call
        except Exception:
            return None

    return None


# ============================================================================
# Context Management
# ============================================================================


def check_and_trim_context(llm: LLM) -> bool:
    """
    Check if context needs trimming and clear/reset if needed.

    Uses actual token usage from the LLM API to determine when to clear context.
    Returns True if context was cleared.

    Args:
        llm: The LLM instance to check

    Returns:
        True if context was cleared, False otherwise
    """
    try:
        max_capacity = llm.max_context_capacity()
        current_usage = llm.get_context_usage_size()

        # Clear when we reach threshold (default 80%) to leave room for next response
        threshold = int(max_capacity * CONTEXT_THRESHOLD)

        if current_usage < threshold:
            return False

        logger.info(
            f"Context at {current_usage}/{max_capacity} tokens ({current_usage*100//max_capacity}%); clearing..."
        )
        llm.clear_context()
        logger.info("Context cleared successfully.")
        return True

    except Exception as e:
        logger.warning(f"Failed to check/clear context: {e}")
        return False


def print_context_usage(llm: LLM, show_always: bool = False) -> None:
    """
    Display context usage statistics.

    Args:
        llm: The LLM instance
        show_always: If True, print to user. If False, only log at DEBUG level.
    """
    try:
        max_capacity = llm.max_context_capacity()
        current_usage = llm.get_context_usage_size()
        percentage = (current_usage * 100) // max_capacity if max_capacity > 0 else 0

        # Create visual progress bar
        bar_length = 30
        filled = (current_usage * bar_length) // max_capacity if max_capacity > 0 else 0
        bar = "█" * filled + "░" * (bar_length - filled)

        usage_str = f"Context: [{bar}] {current_usage}/{max_capacity} tokens ({percentage}%)"

        if show_always:
            print(f"[Info] {usage_str}")
        else:
            logger.debug(usage_str)

    except Exception as e:
        logger.debug(f"Could not get context usage: {e}")


# ============================================================================
# Message Formatting
# ============================================================================


def messages_system(system_text: str) -> dict[str, Any]:
    """
    Create a system message in the format expected by Hailo LLM.

    Args:
        system_text: System prompt text

    Returns:
        Formatted message dictionary
    """
    return {"role": "system", "content": [{"type": "text", "text": system_text}]}


def messages_user(text: str) -> dict[str, Any]:
    """
    Create a user message in the format expected by Hailo LLM.

    Args:
        text: User message text

    Returns:
        Formatted message dictionary
    """
    return {"role": "user", "content": [{"type": "text", "text": text}]}


def messages_assistant(text: str) -> dict[str, Any]:
    """
    Create an assistant message in the format expected by Hailo LLM.

    Args:
        text: Assistant message text

    Returns:
        Formatted message dictionary
    """
    return {"role": "assistant", "content": [{"type": "text", "text": text}]}

