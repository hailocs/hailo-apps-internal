"""
Configuration constants for the chat agent.

Users can modify these values to customize LLM behavior, context management, and model paths.
"""

import logging
import os
import sys

from hailo_apps.python.core.common.core import get_resource_path, resolve_hef_path
from hailo_apps.python.core.common.defines import (
    AGENT_APP,
    LLM_CODER_MODEL_NAME_H10,
    RESOURCES_MODELS_DIR_NAME,
    HAILO10H_ARCH,
)

# LLM Generation Parameters
TEMPERATURE: float = 0.1
SEED: int = 42
MAX_GENERATED_TOKENS: int = 200

# Context Management
CONTEXT_THRESHOLD: float = 0.95  # Clear context when usage reaches this percentage

# Model Configuration
# NOTE: This tool calling API was built for Qwen 2.5 Coder. Not all LLMs support this tool API format.
# To use a different model, change DEFAULT_LLM_MODEL_NAME or set HAILO_HEF_PATH environment variable.
DEFAULT_LLM_MODEL_NAME: str = LLM_CODER_MODEL_NAME_H10

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


def get_hef_path(hef_path_arg: str | None = None) -> str:
    """
    Get HEF path from configuration with auto-download support.

    Resolves the HEF path using resolve_hef_path() which will automatically
    download the model if not found locally.

    NOTE: This tool calling API was built for Qwen 2.5 Coder. Not all LLMs support this tool API format.

    USER CONFIGURATION:
    To use a custom HEF model:
    1. Set the HAILO_HEF_PATH environment variable to the absolute path of your .hef file.
       Example: export HAILO_HEF_PATH=/path/to/my/model.hef
    2. OR use --hef-path argument
    3. OR modify DEFAULT_LLM_MODEL_NAME in this config file to use a different model name.

    Args:
        hef_path_arg: Optional HEF path from command line argument

    Returns:
        str: Absolute path to the HEF file as a string

    Raises:
        ValueError: If HEF file cannot be found.
    """
    # Check if user provided a custom path via environment variable
    custom_path = os.environ.get("HAILO_HEF_PATH")
    if custom_path:
        return custom_path

    # Check if user provided a path via argument
    if hef_path_arg:
        custom_path = hef_path_arg

    # Use resolve_hef_path which handles auto-download
    # Agent is Hailo-10H only
    hef_path = resolve_hef_path(
        custom_path,
        app_name=AGENT_APP,
        arch=HAILO10H_ARCH
    )

    if hef_path is None:
        raise ValueError(
            f"Could not find or download HEF file for agent model. "
            f"Please run: hailo-download-resources --group agent"
        )
    return str(hef_path)
