"""Configuration module: loads defaults, file config, CLI overrides, and merges them."""

import sys
from pathlib import Path

import yaml

# Try to import from hailo_apps, fallback to path-based import
try:
    from hailo_apps.python.core.common.hailo_logger import get_logger
except ImportError:
    # Fallback: create a simple logger if hailo_apps is not installed
    import logging
    def get_logger(name):
        logger = logging.getLogger(name)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
        return logger

# Try to import defines from hailo_apps, fallback to path-based import
try:
    from hailo_apps.python.core.common.defines import (
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
except ImportError:
    # Fallback: import from path
    import importlib.util
    current_file = Path(__file__).resolve()
    defines_path = current_file.parent.parent.parent / "python" / "core" / "common" / "defines.py"
    if defines_path.exists():
        spec = importlib.util.spec_from_file_location("defines", defines_path)
        defines_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(defines_module)
        # Import all needed constants
        DEFAULT_RESOURCES_SYMLINK_PATH = defines_module.DEFAULT_RESOURCES_SYMLINK_PATH
        HAILO_ARCH_DEFAULT = defines_module.HAILO_ARCH_DEFAULT
        HAILO_ARCH_KEY = defines_module.HAILO_ARCH_KEY
        HAILORT_VERSION_DEFAULT = defines_module.HAILORT_VERSION_DEFAULT
        HAILORT_VERSION_KEY = defines_module.HAILORT_VERSION_KEY
        HOST_ARCH_DEFAULT = defines_module.HOST_ARCH_DEFAULT
        HOST_ARCH_KEY = defines_module.HOST_ARCH_KEY
        MODEL_ZOO_VERSION_DEFAULT = defines_module.MODEL_ZOO_VERSION_DEFAULT
        MODEL_ZOO_VERSION_KEY = defines_module.MODEL_ZOO_VERSION_KEY
        RESOURCES_PATH_KEY = defines_module.RESOURCES_PATH_KEY
        SERVER_URL_DEFAULT = defines_module.SERVER_URL_DEFAULT
        SERVER_URL_KEY = defines_module.SERVER_URL_KEY
        TAPPAS_VARIANT_DEFAULT = defines_module.TAPPAS_VARIANT_DEFAULT
        TAPPAS_VARIANT_KEY = defines_module.TAPPAS_VARIANT_KEY
        TAPPAS_VERSION_DEFAULT = defines_module.TAPPAS_VERSION_DEFAULT
        TAPPAS_VERSION_KEY = defines_module.TAPPAS_VERSION_KEY
        VALID_HAILO_ARCH = defines_module.VALID_HAILO_ARCH
        VALID_HAILORT_VERSION = defines_module.VALID_HAILORT_VERSION
        VALID_HOST_ARCH = defines_module.VALID_HOST_ARCH
        VALID_MODEL_ZOO_VERSION = defines_module.VALID_MODEL_ZOO_VERSION
        VALID_SERVER_URL = defines_module.VALID_SERVER_URL
        VALID_TAPPAS_VARIANT = defines_module.VALID_TAPPAS_VARIANT
        VALID_TAPPAS_VERSION = defines_module.VALID_TAPPAS_VERSION
        VIRTUAL_ENV_NAME_DEFAULT = defines_module.VIRTUAL_ENV_NAME_DEFAULT
        VIRTUAL_ENV_NAME_KEY = defines_module.VIRTUAL_ENV_NAME_KEY
    else:
        raise ImportError(f"Could not find defines.py at {defines_path}")

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

