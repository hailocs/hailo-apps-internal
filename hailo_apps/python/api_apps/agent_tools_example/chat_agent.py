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

    # Start tool selection in background thread (runs in parallel with LLM initialization)
    tool_thread, tool_result = agent_utils.start_tool_selection_thread(all_tools)

    # Initialize Hailo in main thread (runs in parallel with tool selection)
    vdevice = VDevice()
    llm = LLM(vdevice, HEF_PATH)

    # Wait for tool selection to complete
    selected_tool = agent_utils.get_tool_selection_result(tool_thread, tool_result)
    if selected_tool is None:
        return

    # Initialize tool if it has an initialize_tool function
    agent_utils.initialize_tool_if_needed(selected_tool)
    selected_tool_name = selected_tool.get("name", "")
    tool_module = selected_tool.get("module")


    try:
        # Single conversation loop; type '/exit' to quit.
        # Only load the selected tool to save context
        system_text = agent_utils.create_system_prompt([selected_tool])
        logger.debug("SYSTEM PROMPT:\n%s", system_text)

        # Try to load cached context for this tool
        # If cache exists, we don't need to send system prompt on first message
        context_loaded = agent_utils.load_context_from_cache(llm, selected_tool_name)

        if context_loaded:
            # Context was loaded from cache, system prompt already in context
            need_system_prompt = False
            logger.info("Using cached context for tool '%s'", selected_tool_name)
        else:
            # No cache found, initialize system prompt and save context
            logger.info("No cache found, initializing system prompt for tool '%s'", selected_tool_name)
            agent_utils.initialize_system_prompt_context(llm, system_text)
            agent_utils.save_context_to_cache(llm, selected_tool_name)
            # System prompt is now in context
            need_system_prompt = False

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
                    print("[Info] Context cleared.")

                    # Try to reload cached context after clearing
                    context_reloaded = agent_utils.load_context_from_cache(llm, selected_tool_name)
                    if context_reloaded:
                        need_system_prompt = False
                        logger.info("Context reloaded from cache after clear")
                    else:
                        need_system_prompt = True
                        logger.info("No cache available after clear, will reinitialize on next message")
                except Exception as e:
                    print(f"[Error] Failed to clear context: {e}")
                    need_system_prompt = True
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
            result = agent_utils.execute_tool_call(tool_call, tools_lookup)
            if not result.get("ok"):
                # If tool execution failed, continue to next input
                agent_utils.print_tool_result(result)
                continue

            # Print tool result directly to user
            agent_utils.print_tool_result(result)

            # Add tool result to LLM context for conversation continuity
            need_system_prompt = agent_utils.add_tool_result_to_context(
                llm=llm,
                system_text=system_text,
                user_text=user_text,
                tool_result=result,
                need_system_prompt=need_system_prompt,
            )

    finally:
        # Cleanup resources
        agent_utils.cleanup_resources(llm, vdevice, tool_module)


if __name__ == "__main__":
    main()


