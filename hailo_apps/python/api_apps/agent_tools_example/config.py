"""
Configuration constants for the chat agent.

Users can modify these values to customize LLM behavior, context management, and model paths.
"""

import logging
import os

# LLM Generation Parameters
TEMPERATURE = 0.1
SEED = 42
MAX_GENERATED_TOKENS = 200

# Context Management
CONTEXT_THRESHOLD = 0.80  # Clear context when usage reaches this percentage

# Default HEF Path
DEFAULT_HEF_PATH = "/home/giladn/tappas_apps/repos/genai-demos/hefs/Qwen2.5-Coder-1.5B-Instruct.hef"

# Logging Configuration
# Default log level (DEBUG, INFO, WARNING, ERROR)
# - DEBUG: Shows all data passed between agent and tools (prompts, responses, tool calls/results)
# - INFO (default): Shows only tool call indications
DEFAULT_LOG_LEVEL = "DEBUG"

# Hardware Configuration
HARDWARE_MODE = "simulator"  # "real" or "simulator"
NEOPIXEL_PIN = 18  # GPIO pin for NeoPixel data line
NEOPIXEL_COUNT = 1  # Number of LEDs in strip
FLASK_PORT = 5000  # Port for simulator web server
SERVO_PIN = 17  # GPIO pin for servo control signal
SERVO_SIMULATOR_PORT = 5001  # Port for servo simulator web server
SERVO_MIN_ANGLE = -90.0  # Minimum servo angle in degrees
SERVO_MAX_ANGLE = 90.0  # Maximum servo angle in degrees

# Logger Setup
LOGGER = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)


def setup_logging() -> None:
    """Set up logging level from configuration."""
    log_level_str = DEFAULT_LOG_LEVEL.upper()
    log_level = getattr(logging, log_level_str, logging.INFO)
    LOGGER.setLevel(log_level)
    # Also set root logger to ensure messages are shown
    logging.root.setLevel(log_level)


def get_hef_path() -> str:
    """
    Get HEF path from configuration.

    Returns:
        Absolute path to the HEF file
    """
    hef_path = os.path.abspath(DEFAULT_HEF_PATH) if not os.path.isabs(DEFAULT_HEF_PATH) else DEFAULT_HEF_PATH
    return hef_path

