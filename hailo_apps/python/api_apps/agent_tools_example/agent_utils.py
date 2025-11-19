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
import threading
from pathlib import Path
from types import ModuleType
from typing import Any, cast

from hailo_platform.genai import LLM

# Import config for context threshold and logger setup
try:
    from . import config
except ImportError:
    # When run directly, use absolute import
    import config

# Use the same logger setup as config to ensure consistent formatting
logger = config.LOGGER if hasattr(config, "LOGGER") else logging.getLogger(__name__)

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
<tools>
{tools_json}
</tools>

Available tools: {tool_names_list}

# CRITICAL: Your Role vs Tool Role
- YOU are the ASSISTANT - you CALL tools, you do NOT respond as tools
- YOU output <tool_call> tags to REQUEST tool execution
- The SYSTEM executes the tool and sends you <tool_response> tags
- YOU then respond to the user based on the tool result
- NEVER output <tool_response> tags yourself - that's what the system sends TO you
- ONLY output <tool_call> tags when you want to use a tool

# Tool Usage Rules
- DEFAULT: If a tool can handle the request, CALL IT using <tool_call>
- ONLY these tools exist: {tool_names_list}. NEVER invent or call tools with different names
- When unsure, CALL THE TOOL (better to use it than skip it)
- Skip tools ONLY for: greetings, small talk, meta questions about capabilities, or clearly conversational requests with no tool match

# How to Call a Tool
When you need to use a tool, output ONLY this format:
<tool_call>
{{"name": "<function-name>", "arguments": <args-json-object>}}
</tool_call>

Rules:
- Use double quotes (") in JSON, not single quotes
- Arguments must be a JSON object, not a string
- Wrap JSON in <tool_call></tool_call> tags
- Use only these tool names: {tool_names_list}
- After calling, wait for the system to send you <tool_response>

# Tool Results
- The system will present tool results directly to the user
- Tool results are already formatted and ready for display
- Your role is to use tools when appropriate, the system handles showing results

# Decision Process - Think Before Responding
BEFORE each response, think about whether to use a tool:
1. Analyze the user's request carefully
2. Check if any available tool ({tool_names_list}) can handle it
3. Determine if tool execution is needed or you can answer directly
4. If no tool needed: respond directly with text

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
        elif not self.inside_text_tag and not self.inside_tool_call_tag:
            # If not inside any tag, the text is still valid for streaming.
            # To avoid printing partial tags, we find the last complete chunk of text.
            # A simple heuristic: find the start of the next potential tag.
            next_tag_start = self.buffer.find('<')
            if next_tag_start != -1:
                # Output text up to the potential start of a tag
                output += self.buffer[:next_tag_start]
                self.buffer = self.buffer[next_tag_start:]
            else:
                # No partial tag found, output the whole buffer
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

    ONLY supports XML-wrapped format:
    <tool_call>
    {"name": "...", "arguments": {...}}
    </tool_call>

    Args:
        response: Raw response string from LLM

    Returns:
        Parsed function call dict with 'name' and 'arguments' keys, or None if not found
    """
    def validate_and_fix_call(call: dict[str, Any]) -> dict[str, Any] | None:
        """Validate that call has required fields and fix nested JSON."""
        if not isinstance(call, dict):
            return None
        # Must have 'name' field
        if "name" not in call or not call.get("name"):
            return None
        # Must have 'arguments' field
        if "arguments" not in call:
            return None
        # Fix nested JSON in arguments
        if isinstance(call.get("arguments"), str):
            try:
                call["arguments"] = json.loads(call["arguments"])  # nested JSON fix
            except Exception:
                pass
        # Ensure arguments is a dict
        if not isinstance(call.get("arguments"), dict):
            return None
        return call

    # ONLY support XML-wrapped function call
    if "<tool_call>" in response:
        try:
            start = response.find("<tool_call>") + len("<tool_call>")
            # Find closing tag, or use brace matching if missing
            end = response.find("</tool_call>", start)
            if end == -1:
                # No closing tag, use brace matching
                json_str = response[start:].strip()
                # Find the complete JSON object by matching braces
                brace_count = 0
                json_end = -1
                for i, char in enumerate(json_str):
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
                    return None
            else:
                json_str = response[start:end].strip()

            json_str = json_str.replace("'", '"')
            call = json.loads(json_str)
            return validate_and_fix_call(call)
        except Exception:
            return None

    return None


# ============================================================================
# Streaming Generation
# ============================================================================


def generate_and_stream_response(
    llm: LLM,
    prompt: list[dict[str, Any]],
    prefix: str = "Assistant: ",
    debug_mode: bool = False,
) -> str:
    """
    Generate response from LLM and stream it to stdout with filtering.

    Handles streaming tokens, filtering XML tags, and cleaning up remaining content.

    Args:
        llm: The LLM instance to use for generation
        prompt: List of message dictionaries to send to the LLM
        prefix: Prefix to print before streaming (default: "Assistant: ")
        debug_mode: If True, don't filter tokens (show raw output)

    Returns:
        Raw response string (before filtering, for tool call parsing)
    """
    print(prefix, end="", flush=True)
    response_parts: list[str] = []
    token_filter = StreamingTextFilter(debug_mode=debug_mode)

    for token in llm.generate(
        prompt=prompt,
        temperature=config.TEMPERATURE,
        seed=config.SEED,
        max_generated_tokens=config.MAX_GENERATED_TOKENS,
    ):
        response_parts.append(token)
        # Filter and print clean tokens on the fly
        cleaned_chunk = token_filter.process_token(token)
        if cleaned_chunk:
            print(cleaned_chunk, end="", flush=True)

    # Print any remaining content after streaming
    remaining = token_filter.get_remaining()
    if remaining:
        # Final cleanup: remove any remaining XML tags and partial tags
        if not debug_mode:
            # Remove complete tags and partial tags (handles cases like </text>, </text, text>, etc.)
            remaining = re.sub(r"</?text>?", "", remaining)  # </text>, </text, <text>, text>
            remaining = re.sub(r"</?tool_call>?", "", remaining)  # </tool_call>, <tool_call>, etc.
            remaining = re.sub(r"<\|im_end\|>", "", remaining)  # Special tokens
        print(remaining, end="", flush=True)
    print()  # New line after streaming completes

    raw_response = "".join(response_parts)
    return raw_response


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


# ============================================================================
# Tool Selection
# ============================================================================


def select_tool_interactive(tools: list[dict[str, Any]], result: dict[str, Any]) -> None:
    """
    Handle user tool selection in a background thread.

    Args:
        tools: List of available tools.
        result: Shared dictionary to store selection result with keys:
            - selected_tool: The selected tool dict or None
            - should_exit: Boolean flag to indicate user wants to quit
            - lock: Threading lock for thread-safe access
    """
    print("\nAvailable tools:")
    for idx, tool_info in enumerate(tools, start=1):
        print(f"  {idx}. {tool_info['name']}: {tool_info['display_description']}")

    while True:
        choice = input("\nSelect a tool by number (or 'q' to quit): ").strip()
        if choice.lower() in {"q", "quit", "exit"}:
            print("Bye.")
            with result["lock"]:
                result["should_exit"] = True
            return
        try:
            tool_idx = int(choice) - 1
            if 0 <= tool_idx < len(tools):
                with result["lock"]:
                    result["selected_tool"] = tools[tool_idx]
                return
            print(f"Invalid selection. Please choose 1-{len(tools)}.")
        except ValueError:
            print("Invalid input. Please enter a number or 'q' to quit.")


def start_tool_selection_thread(
    all_tools: list[dict[str, Any]],
) -> tuple[threading.Thread, dict[str, Any]]:
    """
    Start tool selection in a background thread.

    Args:
        all_tools: List of available tools to choose from.

    Returns:
        Tuple of (thread, result_dict) where result_dict contains:
            - selected_tool: The selected tool dict or None
            - should_exit: Boolean flag to indicate user wants to quit
            - lock: Threading lock for thread-safe access
    """
    # Shared result structure for tool selection
    tool_result: dict[str, Any] = {
        "selected_tool": None,
        "should_exit": False,
        "lock": threading.Lock(),
    }

    # Start tool selection in background thread
    tool_thread = threading.Thread(
        target=select_tool_interactive, args=(all_tools, tool_result), daemon=False
    )
    tool_thread.start()

    return tool_thread, tool_result


def get_tool_selection_result(
    tool_thread: threading.Thread, tool_result: dict[str, Any]
) -> dict[str, Any] | None:
    """
    Wait for tool selection thread to complete and return the selected tool.

    Args:
        tool_thread: The tool selection thread.
        tool_result: Shared result dictionary from start_tool_selection_thread.

    Returns:
        Selected tool dictionary, or None if user chose to exit or no tool was selected.
    """
    # Wait for tool selection to complete
    tool_thread.join()

    # Check tool selection result
    with tool_result["lock"]:
        if tool_result["should_exit"]:
            return None
        selected_tool = tool_result["selected_tool"]

    if selected_tool is None:
        print("[Error] No tool selected.")
        return None

    # Type cast: selected_tool is guaranteed to be non-None after the check above
    selected_tool = cast(dict[str, Any], selected_tool)
    selected_tool_name = selected_tool.get("name", "")
    if not selected_tool_name:
        print("[Error] Selected tool missing 'name' field.")
        return None

    print(f"\nSelected tool: {selected_tool_name}")
    return selected_tool


def wait_for_tool_selection(
    all_tools: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """
    Start tool selection in a background thread and wait for user selection.

    Convenience function that combines start_tool_selection_thread and get_tool_selection_result.

    Args:
        all_tools: List of available tools to choose from.

    Returns:
        Selected tool dictionary, or None if user chose to exit or no tool was selected.
    """
    tool_thread, tool_result = start_tool_selection_thread(all_tools)
    return get_tool_selection_result(tool_thread, tool_result)


def initialize_tool_if_needed(tool: dict[str, Any]) -> None:
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


# ============================================================================
# Tool Execution
# ============================================================================


def execute_tool_call(
    tool_call: dict[str, Any], tools_lookup: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """
    Execute a tool call and return the result.

    Args:
        tool_call: Parsed tool call dictionary with 'name' and 'arguments' keys.
        tools_lookup: Dictionary mapping tool names to tool metadata.

    Returns:
        Tool execution result dictionary with 'ok' key and either 'result' or 'error'.
    """
    tool_name = str(tool_call.get("name", "")).strip()
    args = tool_call.get("arguments", {})
    logger.info("TOOL CALL: %s", tool_name)
    logger.debug("Tool call details - name: %s", tool_name)
    logger.debug("Tool call arguments:\n%s", json.dumps(args, indent=2, ensure_ascii=False))

    selected = tools_lookup.get(tool_name)
    if not selected:
        available = ", ".join(sorted(tools_lookup.keys()))
        logger.error(f"Unknown tool '{tool_name}'. Available: {available}")
        return {"ok": False, "error": f"Unknown tool '{tool_name}'. Available: {available}"}

    runner = selected.get("runner")
    if not callable(runner):
        logger.error(f"Tool '{tool_name}' is missing an executable runner.")
        return {"ok": False, "error": f"Tool '{tool_name}' is missing an executable runner."}

    try:
        result = runner(args)  # type: ignore[misc]
        logger.debug("TOOL EXECUTION RESULT:\n%s", json.dumps(result, indent=2, ensure_ascii=False))
        return result
    except Exception as exc:
        result = {"ok": False, "error": f"Tool raised exception: {exc}"}
        logger.error("Tool execution raised exception: %s", exc)
        logger.debug("Tool exception result:\n%s", json.dumps(result, indent=2, ensure_ascii=False))
        return result


def print_tool_result(result: dict[str, Any]) -> None:
    """
    Print tool execution result to the user.

    Args:
        result: Tool execution result dictionary with 'ok' key.
    """
    if result.get("ok"):
        logger.info("Tool execution: SUCCESS")
        tool_result_text = result.get("result", "")
        if tool_result_text:
            print(f"\n[Tool] {tool_result_text}\n")
    else:
        logger.info("Tool execution: FAILED - %s", result.get("error", "Unknown error"))
        tool_error = result.get("error", "Unknown error")
        print(f"\n[Tool Error] {tool_error}\n")


# ============================================================================
# Context Management for Tool Results
# ============================================================================


def add_tool_result_to_context(
    llm: LLM,
    system_text: str,
    user_text: str,
    tool_result: dict[str, Any],
    need_system_prompt: bool,
) -> bool:
    """
    Add tool result to LLM context without generating a response.

    This maintains conversation history for future interactions.

    Args:
        llm: The LLM instance.
        system_text: System prompt text.
        user_text: Original user query.
        tool_result: Tool execution result dictionary.
        need_system_prompt: Whether system prompt is needed.

    Returns:
        True if system prompt is needed after this operation, False otherwise.
    """
    # Tool result has been printed directly to user
    # Add the tool result to LLM context for conversation continuity
    tool_result_text = json.dumps(tool_result, ensure_ascii=False)
    tool_response_message = f"<tool_response>{tool_result_text}</tool_response>"
    logger.debug("Adding tool result to LLM context:\n%s", tool_response_message)

    # Check if we need to trim context before adding tool result
    context_cleared = check_and_trim_context(llm)
    if context_cleared:
        need_system_prompt = True

    # Add tool result to context without generating a response
    # This maintains conversation history for future interactions
    if context_cleared:
        # Context was cleared, need to rebuild: system, user query, tool result
        prompt = [
            messages_system(system_text),
            messages_user(user_text),
            messages_user(tool_response_message),
        ]
        need_system_prompt = False
    else:
        # LLM has context, just add the tool result
        prompt = [messages_user(tool_response_message)]

    # Add to context by making a minimal generation (just to update context)
    # We don't print this since we already showed the result to the user
    logger.debug("Updating LLM context with tool result")
    try:
        # Generate a single token to update context, then discard the output
        for _ in llm.generate(prompt=prompt, max_generated_tokens=1):
            break  # Just need to trigger context update
    except Exception as e:
        logger.debug("Context update failed (non-critical): %s", e)

    return need_system_prompt


# ============================================================================
# Context Caching
# ============================================================================


def get_context_cache_path(tool_name: str) -> Path:
    """
    Get the path to the context cache file for a given tool.

    Args:
        tool_name: Name of the tool.

    Returns:
        Path to the context cache file.
    """
    current_dir = Path(__file__).parent
    cache_filename = f"context_{tool_name}.cache"
    return current_dir / cache_filename


def save_context_to_cache(llm: LLM, tool_name: str) -> bool:
    """
    Save LLM context to a cache file for faster future loading.

    Args:
        llm: The LLM instance with context to save.
        tool_name: Name of the tool (used for cache file naming).

    Returns:
        True if context was saved successfully, False otherwise.
    """
    try:
        cache_path = get_context_cache_path(tool_name)
        logger.debug("Saving context to cache file: %s", cache_path)

        # Get context data from LLM
        context_data = llm.save_context()

        # Save context data to file (binary format)
        with open(cache_path, 'wb') as f:
            f.write(context_data)

        logger.info("Context cache saved successfully for tool '%s'", tool_name)
        return True
    except Exception as e:
        logger.warning("Failed to save context cache for tool '%s': %s", tool_name, e)
        return False


def load_context_from_cache(llm: LLM, tool_name: str) -> bool:
    """
    Load LLM context from a cache file if it exists.

    Args:
        llm: The LLM instance to load context into.
        tool_name: Name of the tool (used for cache file naming).

    Returns:
        True if context was loaded successfully, False if file doesn't exist or load failed.
    """
    try:
        cache_path = get_context_cache_path(tool_name)

        if not cache_path.exists():
            logger.info("No context cache found for tool '%s' at %s", tool_name, cache_path)
            return False

        logger.debug("Loading context from cache file: %s", cache_path)

        # Read context data from file (binary format)
        with open(cache_path, 'rb') as f:
            context_data = f.read()

        # Load context data into LLM
        llm.load_context(context_data)

        logger.info("Context cache loaded successfully for tool '%s'", tool_name)
        return True
    except Exception as e:
        logger.warning("Failed to load context cache for tool '%s': %s", tool_name, e)
        return False


def initialize_system_prompt_context(llm: LLM, system_text: str) -> None:
    """
    Initialize LLM context with system prompt by generating a minimal response.

    This adds the system prompt to the LLM's context by sending it and generating
    a single token. We instruct the model to respond with only the end token to
    avoid adding unnecessary content to the context.

    Args:
        llm: The LLM instance to initialize.
        system_text: The system prompt text to add to context.
    """
    try:
        logger.info("Initializing system prompt in context...")

        # Build prompt with system message and a request for minimal response
        prompt = [
            messages_system(system_text + " Respond with only a single space character."),
        ]

        # Generate a single token to add the system prompt to context
        # We discard the output since we only need it in context
        generated_tokens = []
        for token in llm.generate(prompt=prompt, max_generated_tokens=1):
            generated_tokens.append(token)

        # Log what was generated for debugging
        generated_text = "".join(generated_tokens)
        logger.debug("System prompt initialization generated token: %s", repr(generated_text))
        logger.info("System prompt successfully added to context")

    except Exception as e:
        logger.warning("Failed to initialize system prompt context: %s", e)
        # Don't raise - allow the application to continue
        # The system prompt will be added normally on first user message


# ============================================================================
# Resource Cleanup
# ============================================================================


def cleanup_resources(
    llm: LLM | None, vdevice: Any | None, tool_module: Any | None
) -> None:
    """
    Clean up Hailo resources and tool resources.

    Args:
        llm: LLM instance to clean up (can be None).
        vdevice: VDevice instance to clean up (can be None).
        tool_module: Tool module with optional cleanup_tool function (can be None).
    """
    # Cleanup: call tool cleanup if available
    if tool_module and hasattr(tool_module, "cleanup_tool"):
        try:
            tool_module.cleanup_tool()
        except Exception as e:
            logger.debug("Tool cleanup failed: %s", e)

    # Cleanup Hailo resources with error handling
    if llm:
        try:
            llm.clear_context()
        except Exception as e:
            logger.debug("Error clearing LLM context: %s", e)

        try:
            llm.release()
        except Exception as e:
            logger.debug("Error releasing LLM: %s", e)

    if vdevice:
        try:
            vdevice.release()
        except Exception as e:
            logger.debug("Error releasing VDevice: %s", e)

