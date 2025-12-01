"""
Configuration constants for the chat agent.

Users can modify these values to customize LLM behavior, context management, and model paths.
"""

import logging
import os
import sys

from hailo_apps.python.core.common.core import get_resource_path
from hailo_apps.python.core.common.defines import LLM_CODER_MODEL_NAME_H10, RESOURCES_MODELS_DIR_NAME

# LLM Generation Parameters
TEMPERATURE: float = 0.1
SEED: int = 42
MAX_GENERATED_TOKENS: int = 200

# Context Management
CONTEXT_THRESHOLD: float = 0.95  # Clear context when usage reaches this percentage


# Logging Configuration
# Default log level (DEBUG, INFO, WARNING, ERROR)
# - DEBUG: Shows all data passed between agent and tools (prompts, responses, tool calls/results)
# - INFO (default): Shows only tool call indications
DEFAULT_LOG_LEVEL: str = "INFO"

# Hardware Configuration
HARDWARE_MODE: str = "simulator"  # "real" or "simulator"
# SPI configuration for NeoPixel (Raspberry Pi 5)
# SPI uses MOSI pin (GPIO 10) automatically - no pin configuration needed
NEOPIXEL_SPI_BUS: int = 0  # SPI bus number (0 = /dev/spidev0.x)
NEOPIXEL_SPI_DEVICE: int = 0  # SPI device number (0 = /dev/spidev0.0)
NEOPIXEL_COUNT: int = 1  # Number of LEDs in strip
FLASK_PORT: int = 5000  # Port for simulator web server
SERVO_PWM_CHANNEL: int = 0  # Hardware PWM channel (0 or 1). Channel 0 = GPIO 18, Channel 1 = GPIO 19
SERVO_SIMULATOR_PORT: int = 5001  # Port for servo simulator web server
SERVO_MIN_ANGLE: float = -90.0  # Minimum servo angle in degrees
SERVO_MAX_ANGLE: float = 90.0  # Maximum servo angle in degrees
ELEVATOR_SIMULATOR_PORT: int = 5002  # Port for elevator simulator web server

# Voice Configuration
ENABLE_VOICE: bool = True
ENABLE_TTS: bool = True

# Logger Setup
LOGGER: logging.Logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)


def validate_config() -> None:
    """
    Validate configuration values on startup.

    Raises:
        ValueError: If any configuration value is invalid.
    """
    # Validate Hardware Mode
    if HARDWARE_MODE.lower() not in ("real", "simulator"):
        raise ValueError(f"Invalid HARDWARE_MODE '{HARDWARE_MODE}'. Must be 'real' or 'simulator'.")

    # Validate Ports
    ports = {
        "FLASK_PORT": FLASK_PORT,
        "SERVO_SIMULATOR_PORT": SERVO_SIMULATOR_PORT,
        "ELEVATOR_SIMULATOR_PORT": ELEVATOR_SIMULATOR_PORT
    }

    for name, port in ports.items():
        if not (1024 <= port <= 65535):
            raise ValueError(f"Invalid {name} {port}. Must be between 1024 and 65535.")

    # Check for port conflicts
    if len(set(ports.values())) != len(ports):
        raise ValueError(f"Port conflict detected in configuration: {ports}")

    # Validate Servo Angles
    if SERVO_MIN_ANGLE >= SERVO_MAX_ANGLE:
        raise ValueError(f"Invalid servo angles: MIN ({SERVO_MIN_ANGLE}) must be less than MAX ({SERVO_MAX_ANGLE})")

    # Validate Context Threshold
    if not (0.1 <= CONTEXT_THRESHOLD <= 1.0):
        raise ValueError(f"Invalid CONTEXT_THRESHOLD {CONTEXT_THRESHOLD}. Must be between 0.1 and 1.0.")


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
    # agent_utils also uses this same logger, so it will get the same format

    # Simple format: just level and message
    simple_formatter = logging.Formatter("%(levelname)s: %(message)s")

    if not any(isinstance(h, logging.StreamHandler) and getattr(h, '_chat_agent_handler', False)
               for h in LOGGER.handlers):
        simple_handler = logging.StreamHandler(sys.stdout)
        simple_handler._chat_agent_handler = True  # type: ignore # Mark as our custom handler
        simple_handler.setFormatter(simple_formatter)
        simple_handler.setLevel(log_level)
        LOGGER.addHandler(simple_handler)
        # Prevent propagation to root logger to avoid duplicate messages
        LOGGER.propagate = False

    print(f"Logging level set to {log_level_str}")


def get_hef_path() -> str:
    """
    Get HEF path from configuration.

    Resolves the HEF path using get_resource_path().

    USER CONFIGURATION:
    To use a custom HEF model:
    1. Set the HAILO_HEF_PATH environment variable to the absolute path of your .hef file.
       Example: export HAILO_HEF_PATH=/path/to/my/model.hef
    2. OR modify the code below to return your custom path string directly.

    Returns:
        str: Absolute path to the HEF file as a string

    Raises:
        ValueError: If HEF file cannot be found.
    """
    # Check if user provided a custom path via environment variable
    custom_path = os.environ.get("HAILO_HEF_PATH")
    if custom_path:
        return custom_path

    # Default: Use the standard model from resources
    hef_path = get_resource_path(
        pipeline_name=None,
        resource_type=RESOURCES_MODELS_DIR_NAME,
        model=LLM_CODER_MODEL_NAME_H10
    )

    if hef_path is None:
        raise ValueError(
            f"Could not find HEF file for model '{LLM_CODER_MODEL_NAME_H10}'."
        )
    return str(hef_path)
