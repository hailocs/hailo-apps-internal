"""
Configuration constants for the chat agent.

Users can modify these values to customize LLM behavior, context management, and model paths.
"""

import logging
import os

from hailo_apps.python.core.common.core import get_resource_path
from hailo_apps.python.core.common.defines import LLM_CODER_MODEL_NAME_H10, RESOURCES_MODELS_DIR_NAME

# LLM Generation Parameters
TEMPERATURE = 0.1
SEED = 42
MAX_GENERATED_TOKENS = 200

# Context Management
CONTEXT_THRESHOLD = 0.80  # Clear context when usage reaches this percentage


# Logging Configuration
# Default log level (DEBUG, INFO, WARNING, ERROR)
# - DEBUG: Shows all data passed between agent and tools (prompts, responses, tool calls/results)
# - INFO (default): Shows only tool call indications
DEFAULT_LOG_LEVEL = "DEBUG"

# Hardware Configuration
HARDWARE_MODE = "real"  # "real" or "simulator"
# SPI configuration for NeoPixel (Raspberry Pi 5)
# SPI uses MOSI pin (GPIO 10) automatically - no pin configuration needed
NEOPIXEL_SPI_BUS = 0  # SPI bus number (0 = /dev/spidev0.x)
NEOPIXEL_SPI_DEVICE = 0  # SPI device number (0 = /dev/spidev0.0)
NEOPIXEL_COUNT = 1  # Number of LEDs in strip
FLASK_PORT = 5000  # Port for simulator web server
SERVO_PWM_CHANNEL = 0  # Hardware PWM channel (0 or 1). Channel 0 = GPIO 18, Channel 1 = GPIO 19
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
    """
    Set up logging level from configuration.

    Creates a custom handler with a simple format for cleaner output,
    while preserving the framework's detailed logging for other components.
    """
    log_level_str = DEFAULT_LOG_LEVEL.upper()
    log_level = getattr(logging, log_level_str, logging.INFO)
    LOGGER.setLevel(log_level)
    # Also set root logger to ensure messages are shown
    logging.root.setLevel(log_level)

    # Add a custom handler with simple format for our logger
    # This gives us clean output without interfering with framework logging
    if not any(isinstance(h, logging.StreamHandler) and getattr(h, '_chat_agent_handler', False)
               for h in LOGGER.handlers):
        import sys
        simple_handler = logging.StreamHandler(sys.stdout)
        simple_handler._chat_agent_handler = True  # Mark as our custom handler
        # Simple format: just level and message
        simple_formatter = logging.Formatter("%(levelname)s: %(message)s")
        simple_handler.setFormatter(simple_formatter)
        simple_handler.setLevel(log_level)
        LOGGER.addHandler(simple_handler)
        # Prevent propagation to root logger to avoid duplicate messages
        LOGGER.propagate = False

    print(f"Logging level set to {log_level_str}")


def get_hef_path() -> str:
    """
    Get HEF path from configuration.

    Checks for HAILO_HEF_PATH environment variable first, then falls back to
    resources directory using get_resource_path() (similar to detection app).

    Returns:
        Absolute path to the HEF file as a string
    """
    hef_path = str(get_resource_path(pipeline_name=None, resource_type=RESOURCES_MODELS_DIR_NAME, model=LLM_CODER_MODEL_NAME_H10))
    if hef_path is None:
        raise ValueError(
            f"Could not find HEF file for model '{LLM_CODER_MODEL_NAME_H10}'. "
            "Set HAILO_HEF_PATH environment variable to a valid .hef path."
        )
    return str(hef_path)

