"""
Voice-controlled mouse agent for Hailo-10H.

Continuously listens for voice commands via microphone, transcribes with Whisper
on Hailo-10H, sends to LLM on Hailo-10H for interpretation, and executes mouse
actions using pyautogui.

Usage:
    python3 -m hailo_apps.python.gen_ai_apps.voice_mouse_agent.voice_mouse_agent

    # With VAD for better speech detection
    python3 -m hailo_apps.python.gen_ai_apps.voice_mouse_agent.voice_mouse_agent --vad

    # Debug mode (shows raw LLM output and tool calls)
    python3 -m hailo_apps.python.gen_ai_apps.voice_mouse_agent.voice_mouse_agent --debug
"""

import argparse
import json
import signal
import sys
import traceback
from io import StringIO
from contextlib import redirect_stderr
from pathlib import Path
from typing import Any, Dict

from hailo_platform import VDevice
from hailo_platform.genai import LLM

from hailo_apps.python.core.common.core import (
    get_standalone_parser,
    handle_list_models_flag,
    resolve_hef_path,
)
from hailo_apps.python.core.common.defines import (
    AGENT_APP,
    HAILO10H_ARCH,
    SHARED_VDEVICE_GROUP_ID,
)
from hailo_apps.python.core.common.hailo_logger import (
    get_logger,
    init_logging,
    level_from_args,
)
from hailo_apps.python.gen_ai_apps.gen_ai_utils.llm_utils import (
    context_manager,
    message_formatter,
    streaming,
    tool_discovery,
    tool_execution,
    tool_parsing,
)
from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.speech_to_text import (
    SpeechToTextProcessor,
)
from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.vad import add_vad_args

try:
    from hailo_apps.python.gen_ai_apps.agent_tools_example.system_prompt import (
        create_system_prompt,
    )
    from hailo_apps.python.gen_ai_apps.agent_tools_example.yaml_config import (
        load_yaml_config,
    )
except ImportError:
    create_system_prompt = None
    load_yaml_config = None

logger = get_logger(__name__)

# LLM generation parameters (tuned for short tool-call responses)
TEMPERATURE: float = 0.1
SEED: int = 42
MAX_GENERATED_TOKENS: int = 150


class VoiceMouseAgent:
    """
    Voice-controlled mouse agent.

    Listens for voice commands, transcribes with Whisper, interprets with LLM,
    and executes mouse actions.
    """

    def __init__(
        self,
        llm_hef_path: Path,
        tool: Dict[str, Any],
        debug: bool = False,
        vad_enabled: bool = False,
        vad_aggressiveness: int = 3,
        vad_energy_threshold: float = 0.005,
    ):
        self.debug = debug
        self.vad_enabled = vad_enabled
        self.vad_aggressiveness = vad_aggressiveness
        self.vad_energy_threshold = vad_energy_threshold
        self.tool = tool
        self.tools_lookup = {tool["name"]: tool}
        self.interaction = None

        print("Initializing AI components...")

        # Suppress ALSA noise during initialization
        with redirect_stderr(StringIO()):
            # 1. VDevice
            params = VDevice.create_params()
            params.group_id = SHARED_VDEVICE_GROUP_ID
            self.vdevice = VDevice(params)

            # 2. Speech-to-Text (Whisper on Hailo)
            self.stt = SpeechToTextProcessor(self.vdevice)

            # 3. LLM (on Hailo)
            self.llm = LLM(self.vdevice, str(llm_hef_path))

        # 4. Initialize LLM context with system prompt and few-shot examples
        self._init_context()

        print("AI components ready!")

    def _init_context(self) -> None:
        """Initialize the LLM context with system prompt and few-shot examples."""
        # Load YAML config for few-shot examples
        yaml_config = None
        config_path = self.tool.get("config_path")
        if config_path and Path(config_path).exists() and load_yaml_config is not None:
            yaml_config = load_yaml_config(Path(config_path))
            if yaml_config:
                logger.debug("Loaded YAML config: %s", config_path)

        # Build system prompt
        if create_system_prompt is not None:
            system_text = create_system_prompt(
                [self.tool],
                yaml_config=yaml_config,
            )
        else:
            # Fallback: minimal system prompt
            tool_def_json = json.dumps(self.tool["tool_def"], separators=(",", ":"))
            system_text = (
                "You are a voice-controlled mouse assistant. "
                "When the user gives a mouse command, call the mouse_control tool.\n\n"
                f"<tools>\n[{tool_def_json}]\n</tools>\n\n"
                "To call a tool, output:\n"
                "<tool_call>\n"
                '{"name": "mouse_control", "arguments": {...}}\n'
                "</tool_call>\n"
            )

        logger.debug("System prompt: %d chars", len(system_text))

        messages = [message_formatter.messages_system(system_text)]

        # Add few-shot examples
        if yaml_config and yaml_config.few_shot_examples:
            logger.info(
                "Adding %d few-shot examples to context",
                len(yaml_config.few_shot_examples),
            )
            from hailo_apps.python.gen_ai_apps.agent_tools_example.system_prompt import (
                prepare_few_shot_examples_messages,
            )

            few_shot_messages = prepare_few_shot_examples_messages(
                yaml_config.few_shot_examples
            )
            messages.extend(few_shot_messages)

        context_manager.add_to_context(self.llm, messages, logger)

        # Save context state for reload between queries
        try:
            self._saved_context = self.llm.save_context()
        except Exception as e:
            logger.warning("Could not save initial context: %s", e)
            self._saved_context = None

    def _reload_context(self) -> None:
        """Reload saved context state for a fresh query."""
        if self._saved_context:
            try:
                self.llm.load_context(self._saved_context)
            except Exception as e:
                logger.warning("Context reload failed: %s", e)

    def on_audio_ready(self, audio) -> None:
        """
        Callback when voice audio is ready from VoiceInteractionManager.

        Args:
            audio: Recorded audio data (numpy array).
        """
        # Transcribe
        try:
            user_text = self.stt.transcribe(audio)
        except Exception as e:
            logger.error("Transcription failed: %s", e)
            return

        if not user_text:
            print("(no speech detected)")
            if self.interaction:
                self.interaction.start_listening()
            return

        print(f"\nYou said: {user_text}")

        # Process the command
        self._process_command(user_text)

        # Restart listening
        if self.interaction:
            self.interaction.start_listening()

    def _process_command(self, user_text: str) -> None:
        """
        Process a voice command through the LLM and execute any tool calls.

        Args:
            user_text: Transcribed voice command text.
        """
        # Reload fresh context for each command (single-turn)
        self._reload_context()

        prompt = [message_formatter.messages_user(user_text)]

        # Generate LLM response
        try:
            raw_response = streaming.generate_and_stream_response(
                llm=self.llm,
                prompt=prompt,
                temperature=TEMPERATURE,
                seed=SEED,
                max_tokens=MAX_GENERATED_TOKENS,
                prefix="LLM: ",
                show_raw_stream=self.debug,
            )
        except Exception as e:
            logger.error("LLM generation failed: %s", e)
            logger.debug("Traceback: %s", traceback.format_exc())
            print(f"[Error] LLM generation failed: {e}")
            return

        # Parse tool call from response
        tool_call = tool_parsing.parse_function_call(raw_response)

        if tool_call is None:
            if self.debug and ("<tool_call>" in raw_response or '{"name"' in raw_response):
                logger.warning("Tool call detected in response but parsing failed")
            print("[No action taken]")
            return

        # Log tool call
        tool_name = tool_call.get("name", "unknown")
        tool_args = tool_call.get("arguments", {})
        action = tool_args.get("action", "unknown")
        logger.debug("Tool call: %s, action: %s, args: %s", tool_name, action, json.dumps(tool_args))

        if self.debug:
            print(f"[Tool Call] {tool_name}: {json.dumps(tool_args)}")

        # Execute the tool
        try:
            result = tool_execution.execute_tool_call(tool_call, self.tools_lookup)
            tool_execution.print_tool_result(result)
        except Exception as e:
            logger.error("Tool execution failed: %s", e)
            print(f"[Error] Tool execution failed: {e}")

    def on_processing_start(self) -> None:
        """Callback when processing starts."""
        pass

    def on_clear_context(self) -> None:
        """Handle context clear request."""
        self._reload_context()
        print("Context reloaded.")

    def run(self) -> None:
        """Run the voice interaction loop."""
        from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.interaction import (
            VoiceInteractionManager,
        )

        self.interaction = VoiceInteractionManager(
            title="Voice Mouse Controller",
            on_audio_ready=self.on_audio_ready,
            on_processing_start=self.on_processing_start,
            on_clear_context=self.on_clear_context,
            on_shutdown=self.close,
            debug=self.debug,
            vad_enabled=self.vad_enabled,
            vad_aggressiveness=self.vad_aggressiveness,
            vad_energy_threshold=self.vad_energy_threshold,
            tts=None,  # No TTS - terminal text feedback only
        )

        self.interaction.run()

    def close(self) -> None:
        """Clean up all resources."""
        try:
            self.llm.clear_context()
        except Exception:
            pass
        try:
            self.llm.release()
        except Exception:
            pass
        try:
            self.vdevice.release()
        except Exception:
            pass
        logger.info("Cleanup complete")


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser."""
    parser = get_standalone_parser()
    parser.description = "Voice-controlled mouse agent (Hailo-10H)"
    # Note: --debug is already provided by get_standalone_parser()
    add_vad_args(parser)
    return parser


def main() -> None:
    """Main entry point."""
    # Graceful shutdown on Ctrl+C
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))

    parser = create_parser()
    handle_list_models_flag(parser, AGENT_APP)
    args = parser.parse_args()

    init_logging(level=level_from_args(args))

    # Resolve LLM HEF path (reuse agent app model)
    llm_hef_path = resolve_hef_path(
        hef_path=args.hef_path,
        app_name=AGENT_APP,
        arch=HAILO10H_ARCH,
    )
    if llm_hef_path is None:
        logger.error("Failed to resolve HEF path for LLM model.")
        sys.exit(1)

    logger.info("Using LLM HEF: %s", llm_hef_path)

    # Discover tools from our tools/ directory
    try:
        modules = tool_discovery.discover_tool_modules(
            tool_dir=Path(__file__).parent
        )
        all_tools = tool_discovery.collect_tools(modules)
    except Exception as e:
        logger.error("Failed to discover tools: %s", e)
        logger.debug(traceback.format_exc())
        sys.exit(1)

    if not all_tools:
        logger.error("No tools found in tools/ directory.")
        sys.exit(1)

    # Find the mouse_control tool
    mouse_tool = None
    for tool in all_tools:
        if tool.get("name") == "mouse_control":
            mouse_tool = tool
            break

    if not mouse_tool:
        logger.error("mouse_control tool not found.")
        sys.exit(1)

    # Initialize tool
    tool_execution.initialize_tool_if_needed(mouse_tool)

    print("\n=== Voice Mouse Controller ===")
    print("Speak mouse commands into your microphone.")
    print("Examples: 'move left 200 pixels', 'click', 'scroll down', 'drag right 300'")
    print("Press Ctrl+C to quit.\n")

    try:
        app = VoiceMouseAgent(
            llm_hef_path=llm_hef_path,
            tool=mouse_tool,
            debug=args.debug,
            vad_enabled=args.vad,
            vad_aggressiveness=args.vad_aggressiveness,
            vad_energy_threshold=args.vad_energy_threshold,
        )
        app.run()
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        logger.error("Agent failed: %s", e)
        logger.debug(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
