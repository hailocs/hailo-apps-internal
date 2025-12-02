"""
Voice-enabled Interactive CLI chat agent.

Combines voice input/output capabilities with the tool-using chat agent.

Usage:
  python -m hailo_apps.python.standalone_apps.agent_tools_example.voice_chat_agent
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import traceback
from pathlib import Path

from hailo_platform import VDevice
from hailo_platform.genai import LLM

from hailo_apps.python.core.gen_ai_utils.voice_processing.interaction import VoiceInteractionManager
from hailo_apps.python.core.gen_ai_utils.voice_processing.speech_to_text import SpeechToTextProcessor
from hailo_apps.python.core.gen_ai_utils.voice_processing.text_to_speech import TextToSpeechProcessor
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
from hailo_apps.python.core.common.defines import SHARED_VDEVICE_GROUP_ID

try:
    from . import config, system_prompt
except ImportError:
    # Add the script's directory to sys.path
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    import config
    import system_prompt


logger = config.LOGGER


class VoiceAgentApp:
    def __init__(self, hef_path, selected_tool, debug=False, no_tts=False):
        self.debug = debug
        self.no_tts = no_tts
        self.selected_tool = selected_tool
        self.selected_tool_name = selected_tool.get("name", "")

        # Initialize tools lookup
        self.tools_lookup = {self.selected_tool_name: selected_tool}

        print("Initializing AI components...")

        # Initialize Hailo VDevice and Models
        try:
            params = VDevice.create_params()
            params.group_id = SHARED_VDEVICE_GROUP_ID # Support multiple processes using the same VDevice
            self.vdevice = VDevice(params)
        except Exception as e:
            print(f"[Error] Failed to create VDevice: {e}")
            raise

        # LLM
        try:
            self.llm = LLM(self.vdevice, hef_path)
        except Exception as e:
            print(f"[Error] Failed to initialize LLM: {e}")
            self.vdevice.release()
            raise

        # S2T
        try:
            self.s2t = SpeechToTextProcessor(self.vdevice)
        except Exception as e:
            print(f"[Error] Failed to initialize Speech-to-Text: {e}")
            self.llm.release()
            self.vdevice.release()
            raise

        # TTS
        self.tts = None
        if not no_tts:
            try:
                self.tts = TextToSpeechProcessor()
            except Exception as e:
                print(f"[Warning] Failed to initialize TTS: {e}")
                print("Continuing without TTS support.")

        # Initialize Context
        self._init_context()

        print("✅ AI components ready!")

    def _init_context(self):
        system_text = system_prompt.create_system_prompt([self.selected_tool])
        logger.debug("SYSTEM PROMPT:\n%s", system_text)

        cache_dir = Path(os.path.dirname(os.path.abspath(__file__)))
        try:
            context_loaded = context_manager.load_context_from_cache(self.llm, self.selected_tool_name, cache_dir, logger)
        except Exception as e:
            logger.warning("Failed to load context cache: %s", e)
            context_loaded = False

        if not context_loaded:
            logger.info("Initializing system prompt...")
            try:
                prompt = [message_formatter.messages_system(system_text)]
                context_manager.add_to_context(self.llm, prompt, logger)
                context_manager.save_context_to_cache(self.llm, self.selected_tool_name, cache_dir, logger)
            except Exception as e:
                logger.error("Failed to initialize system context: %s", e)
        else:
            logger.info("Loaded cached context.")

        self.system_text = system_text

    def on_processing_start(self):
        if self.tts:
            try:
                self.tts.interrupt()
            except Exception as e:
                logger.warning("Failed to interrupt TTS: %s", e)

    def on_audio_ready(self, audio):
        # 1. Transcribe
        try:
            user_text = self.s2t.transcribe(audio)
        except Exception as e:
            print(f"[Error] Transcription failed: {e}")
            return

        if not user_text:
            print("No speech detected.")
            return

        print(f"\nYou: {user_text}")

        # 2. Process with LLM and Tools
        self.process_interaction(user_text)

    def on_clear_context(self):
        if self.llm:
            try:
                self.llm.clear_context()
                print("Context cleared.")

                # Try to reload cached context after clearing
                cache_dir = Path(os.path.dirname(os.path.abspath(__file__)))
                context_reloaded = context_manager.load_context_from_cache(
                    self.llm, self.selected_tool_name, cache_dir, logger
                )
                if context_reloaded:
                    logger.info("Context reloaded from cache after clear")
                else:
                    logger.info("No cache available after clear, will reinitialize on next message")
            except Exception as e:
                print(f"[Error] Failed to clear context: {e}")

    def process_interaction(self, user_text):
        # Check if we need to trim context based on actual token usage
        if context_manager.is_context_full(self.llm, context_threshold=config.CONTEXT_THRESHOLD, logger_instance=logger):
            logger.info("Context limit reached. Clearing context and reloading from cache...")
            self.llm.clear_context()
            cache_dir = Path(os.path.dirname(os.path.abspath(__file__)))

            if context_manager.load_context_from_cache(self.llm, self.selected_tool_name, cache_dir, logger):
                logger.info("Context restored from cache")
            else:
                logger.warning("Context cleared but failed to restore from cache")

        prompt = [message_formatter.messages_user(user_text)]
        logger.debug("Sending user message to LLM:\n%s", json.dumps(prompt, indent=2, ensure_ascii=False))

        # Prepare for streaming response
        current_gen_id = None
        # Using a mutable container to track state inside inner function
        state = {
            'sentence_buffer': "",
            'first_chunk_sent': False
        }

        if self.tts:
            # Clear any pending speech to respond to new input immediately
            self.tts.clear_interruption()
            current_gen_id = self.tts.get_current_gen_id()

        def tts_callback(chunk: str):
            if self.tts:
                state['sentence_buffer'] += chunk
                # Chunk speech
                state['sentence_buffer'] = self.tts.chunk_and_queue(
                    state['sentence_buffer'], current_gen_id, not state['first_chunk_sent']
                )

                if not state['first_chunk_sent'] and not self.tts.speech_queue.empty():
                    state['first_chunk_sent'] = True

        try:
            # Use generate() for streaming output with on-the-fly filtering and TTS callback
            is_debug = logger.level == logging.DEBUG
            raw_response = streaming.generate_and_stream_response(
                llm=self.llm,
                prompt=prompt,
                temperature=config.TEMPERATURE,
                prefix="Assistant: ",
                debug_mode=is_debug,
                token_callback=tts_callback
            )
        except Exception as e:
            print(f"\n[Error] LLM generation failed: {e}")
            logger.error("LLM generation error: %s", traceback.format_exc())
            return

        # Flush remaining speech
        if self.tts and state['sentence_buffer'].strip():
            self.tts.queue_text(state['sentence_buffer'].strip(), current_gen_id)

        # Check for tool calls
        tool_call = tool_parsing.parse_function_call(raw_response)
        if tool_call:
            self.handle_tool_call(tool_call)

    def handle_tool_call(self, tool_call):
        # Execute tool
        result = tool_execution.execute_tool_call(tool_call, self.tools_lookup)
        tool_execution.print_tool_result(result)

        if self.tts:
            if result.get("ok"):
                res_str = str(result.get("result", ""))
                # Speak result if it's short enough, or a summary
                if len(res_str) < 200:
                    self.tts.queue_text(f"The result is {res_str}")
                else:
                    self.tts.queue_text("I have calculated the result.")
            else:
                self.tts.queue_text("There was an error executing the tool.")

        agent_utils.update_context_with_tool_result(self.llm, result, logger)

    def close(self):
        if self.tts:
            try:
                self.tts.stop()
            except Exception:
                pass

        # Cleanup shared resources (LLM, VDevice, Tool)
        tool_module = self.selected_tool.get("module")
        agent_utils.cleanup_resources(
            getattr(self, 'llm', None),
            getattr(self, 'vdevice', None),
            tool_module,
            logger
        )


def main():
    config.setup_logging()

    # Validate configuration
    try:
        config.validate_config()
    except ValueError as e:
        print(f"[Configuration Error] {e}")
        return

    parser = argparse.ArgumentParser(description='Voice-enabled AI Tool Agent')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    parser.add_argument('--no-tts', action='store_true', help='Disable TTS')
    args = parser.parse_args()

    # Get HEF
    try:
        hef_path = config.get_hef_path()
    except ValueError as e:
        print(f"[Error] {e}")
        return

    if not os.path.exists(hef_path):
        print("[Error] HEF file not found.")
        return

    # Tool Selection
    try:
        modules = tool_discovery.discover_tool_modules(tool_dir=Path(__file__).parent)
        all_tools = tool_discovery.collect_tools(modules)
    except Exception as e:
        print(f"[Error] Failed to discover tools: {e}")
        logger.debug(traceback.format_exc())
        return

    if not all_tools:
        print("No tools found.")
        return

    tool_thread, tool_result = tool_selection.start_tool_selection_thread(all_tools)
    selected_tool = tool_selection.get_tool_selection_result(tool_thread, tool_result)

    if not selected_tool:
        return

    tool_execution.initialize_tool_if_needed(selected_tool)

    # Start App
    try:
        app = VoiceAgentApp(hef_path, selected_tool, debug=args.debug, no_tts=args.no_tts)
    except Exception:
        # Error already printed in __init__
        return

    interaction = VoiceInteractionManager(
        title="Voice-Enabled Tool Agent",
        on_audio_ready=app.on_audio_ready,
        on_processing_start=app.on_processing_start,
        on_clear_context=app.on_clear_context,
        on_shutdown=app.close,
        debug=args.debug
    )

    interaction.run()


if __name__ == "__main__":
    main()
