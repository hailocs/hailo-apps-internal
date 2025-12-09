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

# =============================================================================
# Resources Config Utilities
# =============================================================================

_RESOURCES_CONFIG_CACHE: dict | None = None


def _load_resources_config() -> dict:
    """Load the resources configuration file (cached)."""
    global _RESOURCES_CONFIG_CACHE
    if _RESOURCES_CONFIG_CACHE is not None:
        return _RESOURCES_CONFIG_CACHE
    
    try:
        from hailo_apps.python.core.common.defines import DEFAULT_RESOURCES_CONFIG_PATH
    except ImportError:
        current_file = Path(__file__).resolve()
        DEFAULT_RESOURCES_CONFIG_PATH = str(
            current_file.parent.parent / "config" / "resources_config.yaml"
        )
    
    config_path = Path(DEFAULT_RESOURCES_CONFIG_PATH)
    if not config_path.is_file():
        hailo_logger.warning(f"Resources config not found at {config_path}")
        return {}
    
    _RESOURCES_CONFIG_CACHE = load_config(config_path)
    return _RESOURCES_CONFIG_CACHE


def _get_config(resources_config: dict | None) -> dict:
    """Get config from parameter or load from default."""
    return resources_config if resources_config is not None else _load_resources_config()


def _is_none(value) -> bool:
    """Check if value is None or YAML 'None' string."""
    return value is None or (isinstance(value, str) and value.lower() == "none")


def _get_arch_models(config: dict, app_name: str, arch: str | None = None) -> dict | None:
    """Get arch_models dict for an app. If arch is None, returns models_config."""
    app_config = config.get(app_name)
    if not isinstance(app_config, dict) or "models" not in app_config:
        return None
    
    models_config = app_config["models"]
    if arch is None:
        return models_config
    
    arch_models = models_config.get(arch)
    return arch_models if isinstance(arch_models, dict) else None


def _normalize_model_entries(entries) -> list:
    """Convert model entries to a flat list (handles single entry, list, or None)."""
    if _is_none(entries):
        return []
    return entries if isinstance(entries, list) else [entries]


def _extract_names(entries) -> list[str]:
    """Extract model names from entries list."""
    names = []
    for entry in _normalize_model_entries(entries):
        if _is_none(entry):
            continue
        name = entry.get("name") if isinstance(entry, dict) else entry
        if name and not _is_none(name):
            names.append(name)
    return names


def _has_source(entries, source: str) -> bool:
    """Check if any entry has the specified source."""
    for entry in _normalize_model_entries(entries):
        if isinstance(entry, dict) and entry.get("source") == source:
            return True
    return False


def _find_model_entry(entries, model_name: str) -> dict | None:
    """Find a model entry by name, return as normalized dict."""
    for entry in _normalize_model_entries(entries):
        if _is_none(entry):
            continue
        if isinstance(entry, dict) and entry.get("name") == model_name:
            return entry
        if isinstance(entry, str) and entry == model_name:
            return {"name": model_name, "source": "mz"}
    return None


# =============================================================================
# Public API
# =============================================================================

def get_available_apps(resources_config: dict | None = None) -> list[str]:
    """Get list of all available app names from resources config."""
    config = _get_config(resources_config)
    shared_keys = {"videos", "images"}
    return sorted(k for k, v in config.items() if isinstance(v, dict) and k not in shared_keys)


def get_supported_architectures_for_app(app_name: str, resources_config: dict | None = None) -> list[str]:
    """Get architectures that have valid models for an app."""
    config = _get_config(resources_config)
    models_config = _get_arch_models(config, app_name)
    if not models_config:
        return []
    
    supported = []
    for arch, arch_models in models_config.items():
        if isinstance(arch_models, dict):
            if _extract_names(arch_models.get("default")) or _extract_names(arch_models.get("extra")):
                supported.append(arch)
    return sorted(supported)


def get_default_models_for_app_and_arch(app_name: str, arch: str, resources_config: dict | None = None) -> list[str]:
    """Get default model names for an app and architecture."""
    config = _get_config(resources_config)
    arch_models = _get_arch_models(config, app_name, arch)
    return _extract_names(arch_models.get("default")) if arch_models else []


def get_extra_models_for_app_and_arch(app_name: str, arch: str, resources_config: dict | None = None) -> list[str]:
    """Get extra model names for an app and architecture."""
    config = _get_config(resources_config)
    arch_models = _get_arch_models(config, app_name, arch)
    return _extract_names(arch_models.get("extra")) if arch_models else []


def get_all_models_for_app_and_arch(app_name: str, arch: str, resources_config: dict | None = None) -> list[str]:
    """Get all model names (default + extra) for an app and architecture."""
    config = _get_config(resources_config)
    return get_default_models_for_app_and_arch(app_name, arch, config) + \
           get_extra_models_for_app_and_arch(app_name, arch, config)


def get_default_model_for_app_and_arch(app_name: str, arch: str, resources_config: dict | None = None) -> str | None:
    """Get first default model name for an app and architecture."""
    models = get_default_models_for_app_and_arch(app_name, arch, resources_config)
    return models[0] if models else None


def get_model_info(app_name: str, arch: str, model_name: str, resources_config: dict | None = None) -> dict | None:
    """Get full model info (name, source, url) for a specific model."""
    config = _get_config(resources_config)
    arch_models = _get_arch_models(config, app_name, arch)
    if not arch_models:
        return None
    
    # Search in default, then extra
    return _find_model_entry(arch_models.get("default"), model_name) or \
           _find_model_entry(arch_models.get("extra"), model_name)


def is_gen_ai_app(app_name: str, resources_config: dict | None = None) -> bool:
    """Check if an app has any gen-ai-mz source models."""
    config = _get_config(resources_config)
    models_config = _get_arch_models(config, app_name)
    if not models_config:
        return False
    
    for arch_models in models_config.values():
        if isinstance(arch_models, dict):
            if _has_source(arch_models.get("default"), "gen-ai-mz") or \
               _has_source(arch_models.get("extra"), "gen-ai-mz"):
                return True
    return False

