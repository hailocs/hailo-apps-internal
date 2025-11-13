"""
Interactive CLI chat agent that uses Hailo LLM with tool/function calling.

Usage:
  python -m hailo_apps.hailo_app_python.tools.chat_agent

Behavior:
- Discovers tools from modules named 'tool_*.py' in this folder
- Builds a tools-aware system prompt (Qwen-style) similar to tool_usage_example
- Runs a simple REPL: you type a message, model can call a tool, agent executes it, then model answers

References:
- Hailo LLM tutorial patterns
- The function calling flow inspired by your existing tool_usage_example.py
"""

from __future__ import annotations
import os
import json
import logging
import sys
from pathlib import Path

from hailo_platform import VDevice
from hailo_platform.genai import LLM

# Handle both relative imports (when run as module) and absolute imports (when run directly)
# This allows the script to work from any directory and both execution methods
try:
    # Try relative imports first (works when run as module: python -m ...)
    from . import agent_utils
    from . import config
except ImportError:
    # Relative imports failed - we're running directly (python chat_agent.py)
    # Add the script's directory to sys.path so we can import from the same directory
    # This works from any directory because __file__ always points to the script location
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    # Now use absolute imports (works from any directory)
    import agent_utils
    import config

logger = config.LOGGER


def main() -> None:
    # Set up logging level from environment variable
    config.setup_logging()

    # Get HEF path from config
    try:
        HEF_PATH = config.get_hef_path()
    except ValueError as e:
        print(f"[Error] {e}")
        return

    print(f"Using HEF: {HEF_PATH}")
    if not os.path.exists(HEF_PATH):
        print(
            "[Error] HEF file not found. "
            "Set HAILO_HEF_PATH environment variable to a valid .hef path."
        )
        return

    # Discover and collect tools
    modules = agent_utils.discover_tool_modules()
    all_tools = agent_utils.collect_tools(modules)
    if not all_tools:
        print("No tools found. Add 'tool_*.py' modules that define TOOLS_SCHEMA and a run() function.")
        return

    # Let user select a tool at startup
    print("\nAvailable tools:")
    for idx, tool_info in enumerate(all_tools, start=1):
        print(f"  {idx}. {tool_info['name']}: {tool_info['display_description']}")

    while True:
        choice = input("\nSelect a tool by number (or 'q' to quit): ").strip()
        if choice.lower() in {"q", "quit", "exit"}:
            print("Bye.")
            return
        try:
            tool_idx = int(choice) - 1
            if 0 <= tool_idx < len(all_tools):
                selected_tool = all_tools[tool_idx]
                break
            print(f"Invalid selection. Please choose 1-{len(all_tools)}.")
        except ValueError:
            print("Invalid input. Please enter a number or 'q' to quit.")

    selected_tool_name = selected_tool["name"]
    print(f"\nSelected tool: {selected_tool_name}")

    # Initialize tool if it has an initialize_tool function
    tool_module = selected_tool.get("module")
    if tool_module and hasattr(tool_module, "initialize_tool"):
        try:
            tool_module.initialize_tool()
        except Exception as e:
            logger.warning("Tool initialization failed: %s", e)

    # Initialize Hailo
    vdevice = VDevice()
    print("Loading model...")
    llm = LLM(vdevice, HEF_PATH)

    try:
        # Single conversation loop; type '/exit' to quit.
        # Only load the selected tool to save context
        system_text = agent_utils.create_system_prompt([selected_tool])
        logger.debug("SYSTEM PROMPT:\n%s", system_text)
        # Track if we need to send system prompt (first time or after context clear)
        need_system_prompt = True

        # Create a lookup dict for execution (only selected tool)
        tools_lookup = {selected_tool_name: selected_tool}

        print("\nChat started. Type '/exit' to quit. Use '/clear' to reset context. Type '/context' to show stats.")
        print(f"Tool in use: {selected_tool_name}\n")
        while True:
            print("You: ", end="", flush=True)
            user_text = sys.stdin.readline().strip()
            if not user_text:
                continue
            if user_text.lower() in {"/exit", ":q", "quit", "exit"}:
                print("Bye.")
                break
            if user_text.lower() in {"/clear"}:
                try:
                    llm.clear_context()
                    need_system_prompt = True
                    print("[Info] Context cleared.")
                except Exception as e:
                    print(f"[Error] Failed to clear context: {e}")
                continue
            if user_text.lower() in {"/context"}:
                agent_utils.print_context_usage(llm, show_always=True)
                continue

            # Check if we need to trim context based on actual token usage
            context_cleared = agent_utils.check_and_trim_context(llm)
            if context_cleared:
                need_system_prompt = True
                logger.info("Context cleared due to token usage threshold")

            # Log user input
            logger.debug("USER INPUT: %s", user_text)

            # Build prompt: include system message if needed
            # LLM maintains context internally, so we only send new messages
            if need_system_prompt:
                prompt = [
                    agent_utils.messages_system(system_text),
                    agent_utils.messages_user(user_text),
                ]
                need_system_prompt = False
                logger.debug("Sending prompt to LLM (with system prompt):\n%s", json.dumps(prompt, indent=2, ensure_ascii=False))
            else:
                # Pass only the new user message (LLM maintains context internally)
                prompt = [agent_utils.messages_user(user_text)]
                logger.debug("Sending user message to LLM:\n%s", json.dumps(prompt, indent=2, ensure_ascii=False))

            # Use generate() for streaming output with on-the-fly filtering
            is_debug = logger.level == logging.DEBUG
            raw_response = agent_utils.generate_and_stream_response(
                llm=llm,
                prompt=prompt,
                prefix="Assistant: ",
                debug_mode=is_debug,
            )
            logger.debug("LLM RAW RESPONSE (before filtering):\n%s", raw_response)

            # Parse tool call from raw response (before cleaning, as tool_call parsing needs the XML tags)
            tool_call = agent_utils.parse_function_call(raw_response)
            if tool_call is None:
                # No tool call; assistant answered directly
                logger.debug("No tool call detected - LLM responded directly")
                # Response already printed above (streaming with filtering)
                # Continue to next user input (LLM already has the response in context)
                continue

            # Tool call detected - initial response was already filtered and displayed
            # (The tool_call XML was suppressed during streaming)

            # Execute tool call
            tool_name = str(tool_call.get("name", "")).strip()
            args = tool_call.get("arguments", {})
            logger.info("TOOL CALL: %s", tool_name)
            logger.debug("Tool call details - name: %s", tool_name)
            logger.debug("Tool call arguments:\n%s", json.dumps(args, indent=2, ensure_ascii=False))

            selected = tools_lookup.get(tool_name)
            if not selected:
                available = ", ".join(sorted(tools_lookup.keys()))
                logger.error(f"Unknown tool '{tool_name}'. Available: {available}")
                continue
            runner = selected.get("runner")
            if not callable(runner):
                logger.error(f"Tool '{tool_name}' is missing an executable runner.")
                continue
            try:
                result = runner(args)  # type: ignore[misc]
                logger.debug("TOOL EXECUTION RESULT:\n%s", json.dumps(result, indent=2, ensure_ascii=False))

                # Print tool result directly to user
                if result.get("ok"):
                    logger.info("Tool execution: SUCCESS")
                    tool_result = result.get("result", "")
                    if tool_result:
                        print(f"\n[Tool] {tool_result}\n")
                else:
                    logger.info("Tool execution: FAILED - %s", result.get("error", "Unknown error"))
                    tool_error = result.get("error", "Unknown error")
                    print(f"\n[Tool Error] {tool_error}\n")
            except Exception as exc:
                result = {"ok": False, "error": f"Tool raised exception: {exc}"}
                logger.error("Tool execution raised exception: %s", exc)
                logger.debug("Tool exception result:\n%s", json.dumps(result, indent=2, ensure_ascii=False))
                logger.info("Tool execution: FAILED - Exception raised")
                print(f"\n[Tool Error] {result['error']}\n")

            # Tool result has been printed directly to user
            # Add the tool result to LLM context for conversation continuity
            tool_result_text = json.dumps(result, ensure_ascii=False)
            tool_response_message = f"<tool_response>{tool_result_text}</tool_response>"
            logger.debug("Adding tool result to LLM context:\n%s", tool_response_message)

            # Check if we need to trim context before adding tool result
            context_cleared = agent_utils.check_and_trim_context(llm)
            if context_cleared:
                need_system_prompt = True

            # Add tool result to context without generating a response
            # This maintains conversation history for future interactions
            if context_cleared:
                # Context was cleared, need to rebuild: system, user query, tool result
                prompt = [
                    agent_utils.messages_system(system_text),
                    agent_utils.messages_user(user_text),
                    agent_utils.messages_user(tool_response_message),
                ]
                need_system_prompt = False
            else:
                # LLM has context, just add the tool result
                prompt = [agent_utils.messages_user(tool_response_message)]

            # Add to context by making a minimal generation (just to update context)
            # We don't print this since we already showed the result to the user
            logger.debug("Updating LLM context with tool result")
            try:
                # Generate a single token to update context, then discard the output
                for _ in llm.generate(prompt=prompt, max_generated_tokens=1):
                    break  # Just need to trigger context update
            except Exception as e:
                logger.debug("Context update failed (non-critical): %s", e)

    finally:
        # Cleanup: call tool cleanup if available
        if tool_module and hasattr(tool_module, "cleanup_tool"):
            try:
                tool_module.cleanup_tool()
            except Exception as e:
                logger.debug("Tool cleanup failed: %s", e)

        # Cleanup Hailo resources with error handling
        try:
            llm.clear_context()
        except Exception as e:
            logger.debug("Error clearing LLM context: %s", e)

        try:
            llm.release()
        except Exception as e:
            logger.debug("Error releasing LLM: %s", e)

        try:
            vdevice.release()
        except Exception as e:
            logger.debug("Error releasing VDevice: %s", e)


if __name__ == "__main__":
    main()


