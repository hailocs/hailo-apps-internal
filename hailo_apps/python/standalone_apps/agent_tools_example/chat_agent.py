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

import json
import logging
import os
import sys
import traceback
from pathlib import Path

from hailo_platform import VDevice
from hailo_platform.genai import LLM

from hailo_apps.python.core.gen_ai_utils.llm_utils import (
    agent_utils,
    context_manager,
    message_formatter,
    streaming,
    tool_discovery,
    tool_execution,
    tool_parsing,
    tool_selection,
)

try:
    from . import config, system_prompt
except ImportError:
    # Add the script's directory to sys.path so we can import from the same directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    import config
    import system_prompt

logger = config.LOGGER


def main() -> None:
    # Set up logging level from environment variable
    config.setup_logging()

    # Validate configuration
    try:
        config.validate_config()
    except ValueError as e:
        print(f"[Configuration Error] {e}")
        return

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
    try:
        # Pass the directory of this script to find tools in the same folder
        modules = tool_discovery.discover_tool_modules(tool_dir=Path(__file__).parent)
        all_tools = tool_discovery.collect_tools(modules)
    except Exception as e:
        print(f"[Error] Failed to discover tools: {e}")
        logger.debug(traceback.format_exc())
        return

    if not all_tools:
        print("No tools found. Add 'tool_*.py' modules that define TOOLS_SCHEMA and a run() function.")
        return

    # Start tool selection in background thread (runs in parallel with LLM initialization)
    tool_thread, tool_result = tool_selection.start_tool_selection_thread(all_tools)

    # Initialize Hailo in main thread (runs in parallel with tool selection)
    try:
        vdevice = VDevice()
        llm = LLM(vdevice, HEF_PATH)
    except Exception as e:
        print(f"[Error] Failed to initialize Hailo LLM: {e}")
        # Wait for thread to avoid orphan threads
        tool_thread.join()
        return

    # Wait for tool selection to complete
    selected_tool = tool_selection.get_tool_selection_result(tool_thread, tool_result)
    if selected_tool is None:
        return

    # Initialize tool if it has an initialize_tool function
    tool_execution.initialize_tool_if_needed(selected_tool)
    selected_tool_name = selected_tool.get("name", "")
    tool_module = selected_tool.get("module")

    try:
        # Single conversation loop; type '/exit' to quit.
        # Only load the selected tool to save context
        system_text = system_prompt.create_system_prompt([selected_tool])
        logger.debug("SYSTEM PROMPT:\n%s", system_text)

        # Try to load cached context for this tool
        # If cache exists, we don't need to send system prompt on first message
        # NOTE: We assume cache dir is in the same directory as this script for now,
        # or could be configured.
        cache_dir = Path(os.path.dirname(os.path.abspath(__file__)))

        try:
            context_loaded = context_manager.load_context_from_cache(llm, selected_tool_name, cache_dir, logger)
        except Exception as e:
            logger.warning("Failed to load context cache: %s", e)
            context_loaded = False

        if context_loaded:
            # Context was loaded from cache, system prompt already in context
            logger.info("Using cached context for tool '%s'", selected_tool_name)
        else:
            # No cache found, initialize system prompt and save context
            logger.info("No cache found, initializing system prompt for tool '%s'", selected_tool_name)
            try:
                prompt = [message_formatter.messages_system(system_text)]
                context_manager.add_to_context(llm, prompt, logger)
                context_manager.save_context_to_cache(llm, selected_tool_name, cache_dir, logger)
                # System prompt is now in context
            except Exception as e:
                logger.error("Failed to initialize system context: %s", e)
                print(f"[Error] Failed to initialize AI context: {e}")

        # Create a lookup dict for execution (only selected tool)
        tools_lookup = {selected_tool_name: selected_tool}

        print("\nChat started. Type '/exit' to quit. Use '/clear' to reset context. Type '/context' to show stats.")
        print(f"Tool in use: {selected_tool_name}\n")
        while True:
            print("You: ", end="", flush=True)
            try:
                user_text = sys.stdin.readline().strip()
            except KeyboardInterrupt:
                print("\nInterrupted. Type '/exit' to quit properly.")
                continue

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
                    context_reloaded = context_manager.load_context_from_cache(llm, selected_tool_name, cache_dir, logger)
                    if context_reloaded:
                        logger.info("Context reloaded from cache after clear")
                    else:
                        logger.info("No cache available after clear, will reinitialize on next message")
                except Exception as e:
                    print(f"[Error] Failed to clear context: {e}")
                continue
            if user_text.lower() in {"/context"}:
                try:
                    context_manager.print_context_usage(llm, show_always=True, logger_instance=logger)
                except Exception as e:
                    print(f"[Error] Failed to get context usage: {e}")
                continue

            # Check if we need to trim context based on actual token usage
            if context_manager.is_context_full(llm, context_threshold=config.CONTEXT_THRESHOLD, logger_instance=logger):
                logger.info("Context limit reached. Clearing context and reloading from cache...")
                context_manager.load_context_from_cache(llm, selected_tool_name, cache_dir, logger)
            prompt = [message_formatter.messages_user(user_text)]
            logger.debug("Sending user message to LLM:\n%s", json.dumps(prompt, indent=2, ensure_ascii=False))

            try:
                # Use generate() for streaming output with on-the-fly filtering
                is_debug = logger.level == logging.DEBUG
                raw_response = streaming.generate_and_stream_response(
                    llm=llm,
                    prompt=prompt,
                    prefix="Assistant: ",
                    debug_mode=is_debug,
                )
                logger.debug("LLM RAW RESPONSE (before filtering):\n%s", raw_response)
            except Exception as e:
                print(f"\n[Error] LLM generation failed: {e}")
                logger.error("LLM generation error: %s", traceback.format_exc())
                continue

            # Parse tool call from raw response (before cleaning, as tool_call parsing needs the XML tags)
            tool_call = tool_parsing.parse_function_call(raw_response)
            if tool_call is None:
                # No tool call; assistant answered directly
                logger.debug("No tool call detected - LLM responded directly")
                # Response already printed above (streaming with filtering)
                # Continue to next user input (LLM already has the response in context)
                continue

            # Tool call detected - initial response was already filtered and displayed
            # (The tool_call XML was suppressed during streaming)

            # Execute tool call
            result = tool_execution.execute_tool_call(tool_call, tools_lookup)
            if not result.get("ok"):
                # If tool execution failed, continue to next input
                tool_execution.print_tool_result(result)
                continue

            # Print tool result directly to user
            tool_execution.print_tool_result(result)

            # Add tool result to LLM context for conversation continuity
            agent_utils.update_context_with_tool_result(llm, result, logger)
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        agent_utils.cleanup_resources(llm, vdevice, tool_module, logger)


if __name__ == "__main__":
    main()
