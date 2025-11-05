"""Configuration module: loads defaults, file config, CLI overrides, and merges them."""

import sys
from pathlib import Path

import yaml

from hailo_apps.python.core.common.hailo_logger import get_logger

from .defines import (
    DEFAULT_RESOURCES_SYMLINK_PATH,
    HAILO_ARCH_DEFAULT,
    HAILO_ARCH_KEY,
    # Default values
    HAILORT_VERSION_DEFAULT,
    # Config keys
    HAILORT_VERSION_KEY,
    HOST_ARCH_DEFAULT,
    HOST_ARCH_KEY,
    MODEL_ZOO_VERSION_DEFAULT,
    MODEL_ZOO_VERSION_KEY,
    RESOURCES_PATH_KEY,
    SERVER_URL_DEFAULT,
    SERVER_URL_KEY,
    TAPPAS_VARIANT_DEFAULT,
    TAPPAS_VARIANT_KEY,
    TAPPAS_VERSION_DEFAULT,
    TAPPAS_VERSION_KEY,
    VALID_HAILO_ARCH,
    # Valid choices
    VALID_HAILORT_VERSION,
    VALID_HOST_ARCH,
    VALID_MODEL_ZOO_VERSION,
    VALID_SERVER_URL,
    VALID_TAPPAS_VARIANT,
    VALID_TAPPAS_VERSION,
    VIRTUAL_ENV_NAME_DEFAULT,
    VIRTUAL_ENV_NAME_KEY,
)

hailo_logger = get_logger(__name__)


def load_config(path: Path) -> dict:
    """Load YAML file or exit if missing."""
    hailo_logger.debug(f"Attempting to load config file from: {path}")
    if not path.is_file():
        hailo_logger.error(f"Config file not found at {path}")
        print(f"❌ Config file not found at {path}", file=sys.stderr)
        sys.exit(1)
    try:
        config_data = yaml.safe_load(path.read_text()) or {}
        hailo_logger.debug(f"Loaded config: {config_data}")
        return config_data
    except Exception as e:
        hailo_logger.error(f"Error loading config from {path}: {e}")
        raise


def load_default_config() -> dict:
    """Return the built-in default config values."""
    default_cfg = {
        HAILORT_VERSION_KEY: HAILORT_VERSION_DEFAULT,
        TAPPAS_VERSION_KEY: TAPPAS_VERSION_DEFAULT,
        MODEL_ZOO_VERSION_KEY: MODEL_ZOO_VERSION_DEFAULT,
        HOST_ARCH_KEY: HOST_ARCH_DEFAULT,
        HAILO_ARCH_KEY: HAILO_ARCH_DEFAULT,
        SERVER_URL_KEY: SERVER_URL_DEFAULT,
        TAPPAS_VARIANT_KEY: TAPPAS_VARIANT_DEFAULT,
        RESOURCES_PATH_KEY: DEFAULT_RESOURCES_SYMLINK_PATH,
        VIRTUAL_ENV_NAME_KEY: VIRTUAL_ENV_NAME_DEFAULT,
    }
    hailo_logger.debug(f"Loaded default configuration: {default_cfg}")
    return default_cfg


def validate_config(config: dict) -> bool:
    """Validate each config value against its valid choices."""
    hailo_logger.debug(f"Validating configuration: {config}")
    valid_config = True
    valid_map = {
        HAILORT_VERSION_KEY: VALID_HAILORT_VERSION,
        TAPPAS_VERSION_KEY: VALID_TAPPAS_VERSION,
        MODEL_ZOO_VERSION_KEY: VALID_MODEL_ZOO_VERSION,
        HOST_ARCH_KEY: VALID_HOST_ARCH,
        HAILO_ARCH_KEY: VALID_HAILO_ARCH,
        SERVER_URL_KEY: VALID_SERVER_URL,
        TAPPAS_VARIANT_KEY: VALID_TAPPAS_VARIANT,
    }
    for key, valid_choices in valid_map.items():
        val = config.get(key)
        if val not in valid_choices:
            hailo_logger.warning(
                f"Invalid value for {key}: '{val}'. Valid options: {valid_choices}"
            )
            valid_config = False
            print(f"Invalid value '{val}'. Valid options: {valid_choices}")
    hailo_logger.debug(f"Configuration validation result: {valid_config}")
    return valid_config


def load_and_validate_config(config_path: str | None = None) -> dict:
    """Load and validate the configuration file.
    Returns the loaded configuration as a dictionary.
    """
    hailo_logger.debug(f"load_and_validate_config called with path: {config_path}")
    if config_path is None or not Path(config_path).is_file():
        hailo_logger.info("No valid config path provided. Loading default configuration.")
        return load_default_config()
    cfg_path = Path(config_path)
    config = load_config(cfg_path)
    if not validate_config(config):
        hailo_logger.error("Invalid configuration detected. Exiting.")
        print("❌ Invalid configuration. Please check the config file.")
        sys.exit(1)
    hailo_logger.info("Configuration loaded and validated successfully.")
    return config
